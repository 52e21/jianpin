# -*- coding: utf-8 -*-
"""
事项 3 · 批次 2：27 条人工设计用例的复核建议（逐条判定，判定结果内嵌）

判定分三类，严格区分"改标注"和"登记问题"：
  - label_error        ：我的标注错了 → 建议改标
  - code_defect        ：代码真缺陷 → **保留标注**，登记缺陷
  - spec_gap           ：代码符合规范，但规范本身缺一条 → **保留标注**，登记规范缺口
  - code_capability_gap：代码能力不足（语义/蕴含层面）→ **保留标注**，登记能力缺口

原则：**不为了让评测集变绿而改标注**。只有确实是标注错误才改。
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

EVAL = Path(__file__).resolve().parent

# 逐条判定（id → (类别, 建议动作, 理由)）
VERDICTS = {
    "E024": ("code_capability_gap", "保留 gt=推荐",
             "业务上长期用 MySQL/PostgreSQL 的人确实会 SQL（上位概念蕴含），"
             "但代码只做词形匹配。不改标注去迁就代码。"),
    "E031": ("spec_gap", "保留 gt=待定",
             "JD 写「本科以上」而简历未写学历（edu=60），89 分直接推荐。"
             "规范只做加权、没有「硬性条件未满足/未知」的门槛规则。"),
    "E032": ("spec_gap", "保留 gt=待定",
             "JD 要求硕士、简历本科（edu=70），92 分仍推荐。同类规范缺口。"),
    "E034": ("spec_gap", "保留 gt=待定",
             "JD 为硬性「统招本科」(is_strict)、简历大专（edu=70），92 分仍推荐。同类规范缺口。"),
    "E035": ("spec_gap", "保留 gt=待定",
             "JD 要求 5 年、简历 4 年（exp=75），90 分仍推荐。年限门槛未生效；"
             "门槛严格度属业务策略，需业务确认「差几年算不达标」。"),
    "E036": ("code_capability_gap", "保留 gt=不推荐",
             "JD「精通 Java」vs 简历「了解 Java 基础语法」被当作同等命中（skills=100），"
             "叠加 exp=0 仍得 62 分。语境强度（精通/熟悉/了解）未参与判定。"),
    "E041": ("code_defect", "保留 gt=待定",
             "★真缺陷：简历「精通 Java 与 Spring Boot，不熟悉 MySQL」中，"
             "Spring Boot 的后置否定窗口(12字符)跨过标点吃到了「不熟悉」，"
             "导致 Spring Boot 被判缺失（skills=33）。否定窗口不得跨小句。"),
    "E054": ("code_defect", "保留 gt=待定",
             "★真缺陷：同上（「精通 Java 与 Spring Boot，不熟悉 MySQL 与 Redis」），skills=30。"),
    "E051": ("label_error", "建议改标为 待定",
             "空 JD 在接口层已由 /api/agent/analyze 返回 400；"
             "本用例直接调管线，内部给出待定是合理行为。原标「不推荐」无依据。"),
}


def diagnose_negation_window(cases):
    """诊断：技能字面存在于简历、却没被判命中（疑似否定窗口跨小句误伤）。"""
    hits = []
    for c in cases:
        agent._analyze_cache.clear()
        r = asyncio.run(agent.analyze_agent(c["jd"], c["resume"], tenant_id="t", session_id="s"))
        matched = set(r["match_result"]["matched_skills"])
        all_skills = set(r["jd_parse"]["skills"]["required"]) | set(r["jd_parse"]["skills"]["preferred"])
        resume_low = c["resume"].lower()
        for s in all_skills:
            if s.lower() in resume_low and s not in matched:
                hits.append((c["id"], s, c["resume"][:60]))
    return hits


def main():
    database.init_db()
    database.save_history = lambda *a, **k: None
    trace.set_enabled(False)
    config.DEEPSEEK_API_KEY = ""

    cases = [json.loads(l) for l in (EVAL / "eval_set_v1.jsonl").open(encoding="utf-8") if l.strip()]
    batch2 = [c for c in cases if c["needs_human_review"]
              and not c["review_reason"].startswith("模板生成模式")]

    advice, stats = [], Counter()
    for c in batch2:
        agent._analyze_cache.clear()
        r = asyncio.run(agent.analyze_agent(c["jd"], c["resume"], tenant_id="t", session_id="s"))
        old, pred = c["gt"]["conclusion"], r["recommendation"]["type"]
        agree = old == pred
        if agree:
            cat, action, why = "confirm", "确认原标", "与代码输出一致"
        else:
            cat, action, why = VERDICTS.get(c["id"], ("unreviewed", "待定", "未判定"))
        stats[cat] += 1
        advice.append({
            "id": c["id"], "batch": "2_人工设计",
            "old_gt": old, "code_output": pred, "agree": agree,
            "match_score": r["match_result"]["score"],
            "category": cat, "action": action, "reason": why,
            "suggested_gt": "待定" if c["id"] == "E051" else old,
            "annotator": "ai_reviewed",
            "pending_human_confirmation": c["id"] == "E051",
        })

    out = EVAL / "review_advice_v2.jsonl"
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for a in advice:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")

    print(f"批次 2 共 {len(batch2)} 条 → 复核建议写入 {out.name}")
    for k, v in sorted(stats.items()):
        print(f"  {k:<22} {v:>3} 条")
    print("\n  【不一致条目逐条判定】")
    for a in advice:
        if not a["agree"]:
            print(f"    {a['id']}  期望={a['old_gt']} 实际={a['code_output']} 分数={a['match_score']}")
            print(f"        类别={a['category']}  动作={a['action']}")
            print(f"        理由={a['reason']}")

    diag = diagnose_negation_window(cases)
    print(f"\n  【诊断】技能字面在简历里、却没被判命中的用例：{len(diag)} 处")
    for cid, skill, snippet in diag[:15]:
        print(f"    {cid}: 「{skill}」在简历中字面存在但未命中 | {snippet}")
    return advice


if __name__ == "__main__":
    main()
