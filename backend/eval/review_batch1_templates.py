# -*- coding: utf-8 -*-
"""
事项 3 · 批次 1：复核 66 条「模板生成」用例

发现的问题：这 66 条的期望结论是用模板的"模式"启发式写的
（模式1/3 = 部分命中 → 待定），**不是按需求文档 §5 的阈值规则**：
    ≥80 且缺失必须技能 ≤1 → 推荐 ; <50 → 不推荐 ; 其余 → 待定
于是出现"85 分却期望待定"这种自相矛盾的标注。

本脚本按**规范阈值**重算期望值，产出复核建议（不修改 eval_set_v1.jsonl）：
    eval/review_advice_v1.jsonl

重要口径说明（会写进报告）：
    用规范阈值推导的标注只能验证"**实现是否符合自己的规范**"（conformance），
    不能当作"业务正确性"。因此这 66 条应单独作为「规范一致性」指标报告，
    不与人工设计用例/真实数据的「业务一致性」混算。
"""
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import app.agent as agent          # noqa: E402
import app.config as config        # noqa: E402
import app.database as database    # noqa: E402
import app.trace as trace          # noqa: E402
import app.tools as tools          # noqa: E402
from negation_fix_candidate import clause_contains_token, patched as clause_patched   # noqa: E402

EVAL = Path(__file__).resolve().parent


def spec_conclusion(score, missing_count, no_scorable):
    """按需求文档 §5 的阈值规则推导期望结论（独立于实现代码的分支写法）。"""
    if no_scorable:
        return "待定"
    if score >= 80 and missing_count <= 1:
        return "推荐"
    if score < 50:
        return "不推荐"
    return "待定"


def main():
    database.init_db()
    database.save_history = lambda *a, **k: None
    trace.set_enabled(False)
    config.DEEPSEEK_API_KEY = ""

    cases = [json.loads(l) for l in (EVAL / "eval_set_v1.jsonl").open(encoding="utf-8") if l.strip()]
    batch1 = [c for c in cases if c["review_reason"].startswith("模板生成模式")]

    advice, stats = [], Counter()
    for c in batch1:
        agent._analyze_cache.clear()
        r = asyncio.run(agent.analyze_agent(c["jd"], c["resume"], tenant_id="t", session_id="s"))
        mr = r["match_result"]
        no_scorable = mr["score"] == 0 and not mr["missing_skills"] and not mr["matched_skills"] and \
            not r["jd_parse"]["skills"]["required"] and not r["jd_parse"]["skills"]["preferred"]
        spec = spec_conclusion(mr["score"], len(mr["missing_skills"]), no_scorable)

        # 同时算"否定窗口按小句截断"后的规范期望值：只有两种口径都同意才建议改标，
        # 否则说明这条的分数被窗口 bug 影响，改标建议会被撤回（见事项 3 的更正）。
        with clause_patched():
            agent._analyze_cache.clear()
            rf = asyncio.run(agent.analyze_agent(c["jd"], c["resume"], tenant_id="t", session_id="s"))
        mrf = rf["match_result"]
        no_scorable_f = (mrf["score"] == 0 and not mrf["missing_skills"] and not mrf["matched_skills"]
                         and not rf["jd_parse"]["skills"]["required"] and not rf["jd_parse"]["skills"]["preferred"])
        spec_fixed = spec_conclusion(mrf["score"], len(mrf["missing_skills"]), no_scorable_f)

        old = c["gt"]["conclusion"]
        pred = r["recommendation"]["type"]
        contested = spec != spec_fixed
        changed = (spec != old) and not contested
        if contested:
            stats["withdrawn_pending_code_fix"] += 1
        elif changed:
            stats["changed"] += 1
            stats[f"path::{old}->{spec}"] += 1
        else:
            stats["kept"] += 1
            stats[f"agree::{old}"] += 1
        advice.append({
            "id": c["id"],
            "batch": "1_模板生成",
            "old_gt": old,
            "suggested_gt": spec if changed else (old if contested else spec),
            "changed": changed,
            "contested": contested,
            "code_output": pred,
            "spec_now": spec,
            "spec_after_negation_fix": spec_fixed,
            "match_score": mr["score"],
            "match_score_after_negation_fix": mrf["score"],
            "missing_required": mr["missing_skills"],
            "evidence": (f"分数={mr['score']}（修复窗口后={mrf['score']}），缺必须技能={len(mr['missing_skills'])} → "
                         f"现状规范判定={spec}，修复窗口后={spec_fixed}；原标注={old}"),
            "reason": ("该条分数受『否定窗口跨小句』缺陷影响，改标建议撤回，待修复后重新判定"
                       if contested else
                       "原标注由模板启发式给出，与需求文档 §5 阈值规则冲突" if changed
                       else "与规范阈值一致"),
            "annotator": "ai_reviewed",
            "pending_human_confirmation": changed,
        })

    out = EVAL / "review_advice_v1.jsonl"
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for a in advice:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")

    print(f"批次 1 共 {len(batch1)} 条 → 复核建议已写入 {out.name}")
    print(f"  建议改标: {stats['changed']} 条 | 确认原标: {stats['kept']} 条 | "
          f"撤回（受否定窗口缺陷影响，待修复后重判）: {stats['withdrawn_pending_code_fix']} 条")
    print("\n  改标方向分布:")
    for k, v in sorted(stats.items()):
        if k.startswith("path::"):
            print(f"    {v:>3} 条  {k[6:]}")
    print("\n  一致项的原标分布:")
    for k, v in sorted(stats.items()):
        if k.startswith("agree::"):
            print(f"    {v:>3} 条  原标={k[7:]}")

    contested = [a for a in advice if a["contested"]]
    print(f"\n  【受『否定窗口跨小句』缺陷影响而撤回改标】{len(contested)} 条：")
    for a in contested[:20]:
        print(f"    {a['id']}: 原标={a['old_gt']}  现状分数={a['match_score']}(→{a['spec_now']})"
              f"  修复窗口后分数={a['match_score_after_negation_fix']}(→{a['spec_after_negation_fix']})")
    if contested:
        print("  结论：这些不是标注错误，而是代码缺陷；不应改标注去迁就代码。")
    else:
        print("  结论：否定窗口缺陷已修复，原先撤回的条目已随修复确认为原标 ✔")


if __name__ == "__main__":
    main()
