# -*- coding: utf-8 -*-
"""
事项 1 验收：JD 无可评分维度时不得给 100 分 + 推荐

覆盖：
  A. match_resume 直接行为（分数 0 / 标记 / 结论 待定 / 原因文案）
  B. analyze_agent 全链路（结论 待定、不调 LLM、面试题为空、Trace 仍 4 行）
  C. SSE 链路 run_agent
  D. 200 条评测集差异：E012 / E017 专项 + 全量"从一致变不一致 / 从一致变不一致"清单

用法：python eval/test_no_scorable.py
"""
import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import app.agent as agent              # noqa: E402
import app.config as config            # noqa: E402
import app.database as database        # noqa: E402
import app.trace as trace              # noqa: E402
from app.tools import parse_jd, match_resume   # noqa: E402

EVAL = Path(__file__).resolve().parent
# 真实历史数据里出现过的那类 JD
JD_NO_SKILL = "人力专员"
RESUME = "候选人，2年HR经验，负责招聘渠道维护与员工关系处理。"

# 分类登记统一在 eval_registry.py（唯一来源，避免多处口径漂移）
sys.path.insert(0, str(EVAL))
from eval_registry import (KNOWN_LABEL_ISSUES, PENDING_ALIAS,   # noqa: E402
                           KNOWN_DICT_GAPS, ALLOWED_REGRESSIONS)


def part_a():
    print("=== A. match_resume 行为 ===")
    jd_parse = parse_jd(JD_NO_SKILL)
    mr = match_resume(jd_parse, RESUME)
    print(f"  JD={JD_NO_SKILL!r} → 识别技能: required={jd_parse['skills']['required']} preferred={jd_parse['skills']['preferred']}")
    print(f"  match_score={mr['match_score']}（原实现为 100）")
    print(f"  no_scorable_dimension={mr.get('no_scorable_dimension')}")
    print(f"  conclusion={mr.get('conclusion')!r}  reason={mr.get('reason')!r}")
    print(f"  dimensions={mr['dimensions']}")
    ok = (mr["match_score"] == 0 and mr.get("no_scorable_dimension") is True
          and mr.get("conclusion") == "待定" and "未识别出可评分维度" in mr.get("reason", ""))
    print(f"  A 结果: {'PASS' if ok else 'FAIL'}")
    return ok


def part_b():
    print("\n=== B. analyze_agent 全链路 ===")
    config.DEEPSEEK_API_KEY = ""          # 关 LLM
    agent._analyze_cache.clear()
    trace.set_enabled(True)               # 顺便验证 Trace 仍为 4 行
    database.init_db()
    r = asyncio.run(agent.analyze_agent(JD_NO_SKILL, RESUME, tenant_id="t", session_id="s"))
    rows = database.fetch_traces(trace_id=r["trace_id"])
    print(f"  分数={r['match_result']['score']}  结论={r['recommendation']['type']}  面试题={len(r['interview_questions'])}")
    print(f"  理由={r['recommendation']['reason']}")
    print(f"  llm_calls={r['llm_calls']}（应为 0）   Trace 行数={len(rows)}（应为 4）")
    ok = (r["recommendation"]["type"] == "待定" and r["match_result"]["score"] == 0
          and r["llm_calls"] == 0 and len(r["interview_questions"]) == 0 and len(rows) == 4)
    print(f"  B 结果: {'PASS' if ok else 'FAIL'}")
    trace.set_enabled(False)
    # 只清理**本次**产生的 Trace（按 trace_id 精确删除）。
    # 原实现是 `DELETE FROM trace_events`（整表清空）——它会抹掉其它任务/真实流量的 Trace，
    # 实测把浏览器点击验证产生的 4 行证据一起删了。测试绝不允许删除不是自己创建的行。
    with database.get_conn() as conn:
        conn.execute("DELETE FROM trace_events WHERE trace_id = ?", (r["trace_id"],))
    return ok


def part_c():
    print("\n=== C. SSE 链路 run_agent ===")

    async def collect():
        out = []
        async for chunk in agent.run_agent(JD_NO_SKILL, RESUME, {}, "t", "s", "hr"):
            out.append(chunk)
        return "".join(out)

    agent._result_cache.clear()
    text = asyncio.run(collect())
    lines = [l for l in text.splitlines() if l.startswith(("结论：", "理由："))]
    print(f"  输出结论行: {lines}")
    ok = "结论：待定" in text and "未识别出可评分维度" in text and "推荐" not in text.split("结论：")[-1]
    print(f"  C 结果: {'PASS' if ok else 'FAIL'}")
    return ok


def part_d():
    print("\n=== D. 200 条评测集差异 ===")
    cases = [json.loads(l) for l in (EVAL / "eval_set_v1.jsonl").open(encoding="utf-8") if l.strip()]
    baseline = {c["id"]: c["pred_conclusion"] for c in
                json.load((EVAL / "baseline.json").open(encoding="utf-8"))["cases"]}
    gt = {c["id"]: c["gt"]["conclusion"] for c in cases}

    config.DEEPSEEK_API_KEY = ""
    trace.set_enabled(False)
    preds = {}
    for c in cases:
        agent._analyze_cache.clear()
        r = asyncio.run(agent.analyze_agent(c["jd"], c["resume"], tenant_id="t", session_id="s"))
        preds[c["id"]] = r["recommendation"]["type"]

    old_agree = sum(1 for i in gt if baseline.get(i) == gt[i])
    new_agree = sum(1 for i in gt if preds.get(i) == gt[i])
    print(f"  结论一致率: 升级前 {old_agree}/200 = {old_agree/2:.1f}%  →  现在 {new_agree}/200 = {new_agree/2:.1f}%")

    fixed = [i for i in gt if baseline.get(i) != gt[i] and preds.get(i) == gt[i]]
    broke = [i for i in gt if baseline.get(i) == gt[i] and preds.get(i) != gt[i]]
    real_broke = [i for i in broke if i not in ALLOWED_REGRESSIONS]
    dict_gaps = [i for i in broke if i in KNOWN_DICT_GAPS]

    print("\n  【真缺陷修复】从『不一致』变『一致』：")
    for i in fixed:
        case = next(c for c in cases if c["id"] == i)
        print(f"    {i}: {baseline.get(i)} → {preds.get(i)}（期望 {gt[i]}）  JD={case['jd'][:26]!r}")
    print(f"    小计 {len(fixed)} 条")

    print("\n  【真缺陷回归】从『一致』变『不一致』（应为空）：")
    print(f"    {real_broke if real_broke else '无 ✔'}")

    print("\n  【词表/标注类已登记项，非缺陷】：")
    for i in broke:
        if i in dict_gaps:
            label = "词表覆盖不足（业务决定）"
        elif i in KNOWN_LABEL_ISSUES:
            label = "标注口径待复核（事项 3）"
        else:
            label = "别名写法缺口（待确认批次）"
        case = next(c for c in cases if c["id"] == i)
        print(f"    {i}: {baseline.get(i)} → {preds.get(i)}（期望 {gt[i]}）  【{label}】 JD={case['jd'][:30]!r}")

    print("\n  --- 验收专项：E012 / E017 ---")
    ok_special = True
    for cid in ("E012", "E017"):
        case = next(c for c in cases if c["id"] == cid)
        good = preds[cid] == gt[cid]
        ok_special &= good
        print(f"    {cid}: 期望={gt[cid]}  升级前={baseline.get(cid)}  现在={preds[cid]}  "
              f"{'一致 ✔' if good else '仍不一致 ✘'}  | JD={case['jd'][:20]!r}")

    print(f"\n  D 结果: {'PASS' if (ok_special and not real_broke) else 'FAIL'}")
    return ok_special and not real_broke


if __name__ == "__main__":
    database.init_db()
    database.save_history = lambda *a, **k: None
    a, b, c, d = part_a(), part_b(), part_c(), part_d()
    print("\n总结果:", "全部通过 ✅" if (a and b and c and d) else "存在失败 ❌")
    sys.exit(0 if (a and b and c and d) else 1)
