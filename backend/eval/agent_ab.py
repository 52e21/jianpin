# -*- coding: utf-8 -*-
"""
A7：Agent 追问分支的前后对比（ASK_ENABLED=0 vs 1）

产出：
  eval/agent_ab_result.json  —— 完整数据（两组 report + 逐条差异 + 链路证据）
  eval/agent_ab_table.md     —— 可直接引用的对比表

对比项（执行书 A7）：
  追问后结论改善 / 不引死循环 / 追问轮数 ≤ 2 / 一致率不下降
外加：追问命中率、追问条数、LLM 成本（分支应为 0）

用法：python eval/agent_ab.py
"""
import asyncio
import io
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

EVAL = Path(__file__).resolve().parent
SET = EVAL / "eval_set_v1_2.jsonl"
VAGUE = "招聘后端工程师"
RESUME = "本科，5 年 Java 后端开发经验，熟悉 Spring Boot、MySQL、Redis。"
ANSWERS = [{"question": "必须技能？", "answer": "Java、Spring Boot、MySQL"},
           {"question": "经验？", "answer": "3 年以上"},
           {"question": "学历？", "answer": "本科及以上"}]
JUNK = [{"question": "必须技能？", "answer": "不知道"}]


def run_arm(enabled: str, out_name: str) -> dict:
    """用子进程跑一次评测（ASK_ENABLED 通过环境变量传入，避免污染本进程）。"""
    env = dict(os.environ)
    env["ASK_ENABLED"] = enabled
    out = EVAL / out_name
    r = subprocess.run([sys.executable, str(EVAL / "eval_runner.py"),
                        "--set", str(SET), "--out", str(out)],
                       cwd=str(BACKEND), env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("eval_runner 失败: %s" % (r.stderr[-400:] or r.stdout[-400:]))
    return json.load(io.open(out, encoding="utf-8"))


def per_case_diff(off: dict, on: dict):
    a = {c["id"]: c for c in off["cases"]}
    b = {c["id"]: c for c in on["cases"]}
    concl = [i for i in a if i in b and a[i]["pred_conclusion"] != b[i]["pred_conclusion"]]
    status = [i for i in a if i in b and (a[i].get("pred_status") or "") != (b[i].get("pred_status") or "")]
    got_worse = [i for i in concl if a[i]["pred_conclusion"] == a[i]["gt_conclusion"]
                 and b[i]["pred_conclusion"] != b[i]["gt_conclusion"]]
    got_better = [i for i in concl if a[i]["pred_conclusion"] != a[i]["gt_conclusion"]
                  and b[i]["pred_conclusion"] == b[i]["gt_conclusion"]]
    return sorted(concl), sorted(status), sorted(got_worse), sorted(got_better)


async def loop_evidence(session_id: str) -> list:
    """A5 证据：连续补充无效信息 3 次，记录每次的 (round, status)，验证 ≤2 轮且收口。"""
    import app.database as database

    database.upsert_ask_session = database.upsert_ask_session      # 保留真实写入（本脚本自行清理）
    from app.agent import analyze_agent

    seq = []
    for _ in range(3):
        r = await analyze_agent(VAGUE, RESUME, tenant_id="t-a7", session_id=session_id, role="hr",
                                answers=JUNK)
        seq.append((r.get("status") or "(正常返回)", (r.get("ask") or {}).get("round"),
                    len((r.get("ask") or {}).get("questions") or []), r.get("llm_calls")))
    database.delete_ask_session(session_id)
    return seq


async def improve_evidence(session_id: str) -> dict:
    """A4 证据：信息不足 → HR 补充 → 结论改善。"""
    import app.database as database
    from app.agent import analyze_agent

    before = await analyze_agent(VAGUE, RESUME, tenant_id="t-a7", session_id=session_id, role="hr")
    after = await analyze_agent(VAGUE, RESUME, tenant_id="t-a7", session_id=session_id, role="hr",
                                answers=ANSWERS)
    out = {
        "before": {"status": before.get("status"), "conclusion": (before.get("recommendation") or {}).get("type"),
                   "score": (before.get("match_result") or {}).get("score"),
                   "questions": (before.get("ask") or {}).get("questions")},
        "after": {"status": after.get("status") or "(正常返回)",
                  "conclusion": (after.get("recommendation") or {}).get("type"),
                  "score": (after.get("match_result") or {}).get("score"),
                  "llm_calls": after.get("llm_calls")},
    }
    database.delete_ask_session(session_id)
    return out


def main():
    import app.database as database
    import app.trace as trace
    database.init_db()
    # 纪律：本脚本不写历史/Trace（只在链路证据里用 session，且用完即删）
    database.save_history = lambda *a, **k: None
    trace.record = lambda *a, **k: None

    print("[1/4] 跑 ASK_ENABLED=0 组 ...")
    off = run_arm("0", "agent_ab_off.json")
    print("[2/4] 跑 ASK_ENABLED=1 组 ...")
    on = run_arm("1", "agent_ab_on.json")
    ro, rn = off["report"], on["report"]
    concl_diff, status_diff, got_worse, got_better = per_case_diff(off, on)

    print("[3/4] 追问轮数/死循环证据 ...")
    seq = asyncio.run(loop_evidence("a7-loop-%d" % os.getpid()))
    print("      (status, round, questions, llm) 序列 = %s" % seq)
    print("[4/4] 补充后改善证据（1 次 LLM）...")
    imp = asyncio.run(improve_evidence("a7-improve-%d" % os.getpid()))
    print("      %s -> %s" % (imp["before"]["conclusion"], imp["after"]["conclusion"]))

    rows = [
        ("结论一致率", "%s (%s)" % (ro["conclusion_agreement"], ro["conclusion_agreement_n"]),
         "%s (%s)" % (rn["conclusion_agreement"], rn["conclusion_agreement_n"])),
        ("追问命中率(10 条新用例)", "-",
         "%s/%s = %s" % ((rn.get("ask_branch") or {}).get("hit"), (rn.get("ask_branch") or {}).get("n"),
                         (rn.get("ask_branch") or {}).get("accuracy"))),
        ("追问条数范围", "-",
         "%s-%s（要求 1-3）" % ((rn.get("ask_branch") or {}).get("questions_min"),
                              (rn.get("ask_branch") or {}).get("questions_max"))),
        ("分支 LLM 调用（10 条）", "0", str((rn.get("ask_branch") or {}).get("llm_calls"))),
        ("总 LLM 调用", str(ro["total_tokens"] and "" or sum(c["llm_calls"] for c in off["cases"])),
         str(sum(c["llm_calls"] for c in on["cases"]))),
        ("错误数", str(ro["error_count"]), str(rn["error_count"])),
        ("结论发生变化的用例", "-", "%d 条 %s" % (len(concl_diff), concl_diff[:8])),
        ("其中 由对变错 / 由错变对", "-", "%d 条 / %d 条 %s" % (len(got_worse), len(got_better), got_better[:6])),
        ("状态新增/变化", "-", "%d 条 %s" % (len(status_diff), status_diff[:8])),
        ("追问轮数上限", "-", "2（第 3 次补充仍无效则收口为 %s）" % seq[-1][0]),
        ("死循环", "无", "无（序列 %s）" % [s[1] for s in seq]),
        ("补充后结论", "%s (score %s)" % (imp["before"]["conclusion"], imp["before"]["score"]),
         "%s (score %s)" % (imp["after"]["conclusion"], imp["after"]["score"])),
    ]
    print("\n指标                                   | ASK=0                | ASK=1")
    print("---------------------------------------|----------------------|---------------------")
    for a, b, c in rows:
        print("%-38s | %-20s | %s" % (a, b, c))

    lines = ["| 指标 | ASK_ENABLED=0（前）| ASK_ENABLED=1（后）|", "|---|---|---|"]
    lines += ["| %s | %s | %s |" % r for r in rows]
    lines += ["", "追问样例（信息不足 JD `%s`）：" % VAGUE]
    for q in imp["before"]["questions"] or []:
        lines.append("- %s" % q)
    (EVAL / "agent_ab_table.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    with io.open(EVAL / "agent_ab_result.json", "w", encoding="utf-8") as f:
        json.dump({"set": SET.name, "before": ro, "after": rn,
                   "conclusion_diff": concl_diff, "status_diff": status_diff,
                   "loop_sequence": seq, "improve": imp}, f, ensure_ascii=False, indent=2)
    print("\n已写出: eval/agent_ab_table.md, eval/agent_ab_result.json")

    ok = (len(got_worse) == 0
          and rn["conclusion_agreement"] >= ro["conclusion_agreement"]
          and (rn.get("ask_branch") or {}).get("accuracy") == 1.0
          and rn["error_count"] == 0
          and [s[1] for s in seq] == [1, 2, 2]
          and seq[-1][0] == "insufficient_final"
          and imp["after"]["conclusion"] == "推荐" and imp["before"]["conclusion"] == "待定")
    print("A7 结论: %s" % ("PASS ✅" if ok else "FAIL ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
