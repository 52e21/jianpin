# -*- coding: utf-8 -*-
"""
A1 验收：用 session_id 挂载追问状态，并且**能查到**

覆盖：
  A. 挂载：带 session_id 的 /analyze 之后，GET /api/agent/session/{id} 能查到该会话（role/tenant/长度/轮数）
  B. 更新：同一 session_id 再带新 JD → 挂载状态被更新（长度变化），轮数等字段不被普通请求重置
  C. 未挂载的 session → 404
  D. 不影响主链路：同输入不同 session_id，结论与分数完全一致
  E. A5 依赖的约束：普通请求不得重置 round/status/pending_questions（由 A4 显式推进）

用法：python eval/test_agent_session.py
（用会触发低分短路的输入，避免真实调用 LLM；只清理本测试自己创建的 session 与历史行）
"""
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import app.database as database          # noqa: E402
import app.trace as trace                # noqa: E402
from app.main import app                 # noqa: E402

SID = "a1-test-%d" % int(time.time())
SID2 = SID + "-b"
JD = "招聘前端工程师，要求精通 React 与 TypeScript，3 年经验。"
RESUME = "会计专业，做过 5 年财务核算与报销流程。"
JD2 = JD + "另外要求熟悉 Node.js 与 Webpack 构建优化。"

RESPONSES = []
_orig_save = database.save_history
_orig_record = trace.record


def client():
    from fastapi.testclient import TestClient
    return TestClient(app)


def analyze(c, sid, jd=JD, resume=RESUME):
    r = c.post("/api/agent/analyze", json={"jd": jd, "resume": resume, "tenant_id": "t-a1",
                                          "session_id": sid, "role": "hr"})
    assert r.status_code == 200, r.text
    RESPONSES.append((sid, r.json()))
    return r.json()


def part_a(c):
    print("=== A. 挂载后可查 ===")
    body = analyze(c, SID)
    got = c.get("/api/agent/session/%s" % SID)
    ok = got.status_code == 200
    print("  GET session -> HTTP %s" % got.status_code)
    if ok:
        d = got.json()
        ok = (d["session_id"] == SID and d["tenant_id"] == "t-a1" and d["role"] == "hr"
              and d["jd_chars"] == len(JD) and d["resume_chars"] == len(RESUME)
              and d["round"] == 0 and d["status"] == "idle")
        print("  %s" % {k: d[k] for k in ("session_id", "tenant_id", "role", "round", "status",
                                          "jd_chars", "resume_chars", "round_limit")})
    print("  分析结论=%s（llm_calls=%s，应为 0 次以省成本）" % (
        body["recommendation"]["type"] if "recommendation" in body else "?", body.get("llm_calls")))
    print("  A 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_b(c):
    print("\n=== B. 同一 session 更新 + round 不可被重置 + 充足后闭环 ===")
    database.upsert_ask_session(SID, round_no=1, status="insufficient",
                               pending_questions=["这个岗位需要几年经验？"], merged_jd="")
    analyze(c, SID, jd=JD2)
    d = c.get("/api/agent/session/%s" % SID).json()
    len_ok = d["jd_chars"] == len(JD2)
    round_ok = d["round"] == 1                       # round 只累积、绝不被普通请求重置
    # A4 语义：本次 JD 信息充足 → 追问闭环（status=done、pending 清空）
    closed_ok = d["status"] == "done" and d["pending_questions"] == []
    print("  JD 长度已更新: %s (%d -> %d)" % (len_ok, len(JD), d["jd_chars"]))
    print("  round 未被重置: %s (round=%s)" % (round_ok, d["round"]))
    print("  充足后闭环: %s (status=%s pending=%s)" % (closed_ok, d["status"], d["pending_questions"]))
    # 再发一次「信息不足」的 JD：round 应在 1 基础上累加为 2，而不是回退
    analyze(c, SID, jd="招聘后端工程师")
    d2 = c.get("/api/agent/session/%s" % SID).json()
    acc_ok = d2["round"] == 2 and d2["status"] == "insufficient" and bool(d2["pending_questions"])
    print("  再次不足 → round 累加: %s (round=%s status=%s pending=%d)" % (
        acc_ok, d2["round"], d2["status"], len(d2["pending_questions"] or [])))
    ok = len_ok and round_ok and closed_ok and acc_ok
    print("  B 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_c(c):
    print("\n=== C. 未挂载的 session → 404 ===")
    r = c.get("/api/agent/session/%s" % (SID + "-nonexistent"))
    ok = r.status_code == 404
    print("  HTTP %s %s" % (r.status_code, "✔" if ok else "✘"))
    print("  C 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_d(c):
    print("\n=== D. 不影响主链路（同输入不同 session_id）===")
    a = analyze(c, SID2)
    b = analyze(c, SID2 + "-2")
    same = (a["recommendation"]["type"] == b["recommendation"]["type"]
            and a["match_result"]["score"] == b["match_result"]["score"]
            and a["llm_calls"] == b["llm_calls"])
    print("  结论 %s/%s 分数 %s/%s llm_calls %s/%s %s" % (
        a["recommendation"]["type"], b["recommendation"]["type"],
        a["match_result"]["score"], b["match_result"]["score"],
        a["llm_calls"], b["llm_calls"], "✔" if same else "✘"))
    print("  D 结果: %s" % ("PASS" if same else "FAIL"))
    return same


def cleanup():
    n_hist = n_trace = 0
    for sid, body in RESPONSES:
        tid = body.get("task_id")
        if not tid:
            continue
        with database.get_conn() as conn:
            n_hist += conn.execute("DELETE FROM execution_history WHERE task_id = ?", (tid,)).rowcount
            n_trace += conn.execute("DELETE FROM trace_events WHERE task_id = ?", (tid,)).rowcount
    n_sess = 0
    for sid in {SID, SID2, SID2 + "-2"}:
        try:
            n_sess += 1 if database.delete_ask_session(sid) else 0
        except Exception as e:
            print("  清理 session 失败(忽略): %s" % e)
    print("\n清理（只删本测试自己创建的）: session=%d history=%d trace=%d" % (n_sess, n_hist, n_trace))


if __name__ == "__main__":
    # 纪律：测试不写历史/Trace；但 **保留 session 挂载**（那正是本项验收对象），最后统一清理
    database.save_history = lambda *a, **k: None
    trace.record = lambda *a, **k: None
    a = b = cc = d = False
    try:
        database.init_db()          # TestClient 不用 with 上下文时 lifespan 不跑，需显式建表
        c = client()
        a, b, cc, d = part_a(c), part_b(c), part_c(c), part_d(c)
    finally:
        database.save_history = _orig_save
        trace.record = _orig_record
        cleanup()
    allok = all([a, b, cc, d])
    print("\n总结果:", "全部通过 ✅" if allok else "存在失败 ❌")
    sys.exit(0 if allok else 1)
