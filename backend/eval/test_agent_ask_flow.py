# -*- coding: utf-8 -*-
"""
A4 + A5 验收：追问分支接线与状态机

覆盖：
  A. 信息不足 → 提前返回 need_more_info（1–3 条追问、0 次 LLM），session 记 round=1/insufficient
  B. HR 补充后重走 parse_jd 之后的链路：合并文本进 JD、结论**改善**、session 记 done
  C. A5 上限：追问 2 轮后仍不足 → insufficient_final + 待定 + 0 次 LLM（无死循环）
  D. 对照组 ASK_ENABLED=0：信息不足的 JD 行为与加 Agent 之前一致（不进分支）
  E. 主链路不变：信息充足的 JD 响应结构/字段与之前一致（无 ask 字段）

用法：python eval/test_agent_ask_flow.py
（只调 1 次 LLM——B 里补充信息后进入主链路；其余都短路或走分支）
"""
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import app.database as database          # noqa: E402
import app.trace as trace                # noqa: E402
from app.main import app                 # noqa: E402

SID_A = "a4-test-a-%d" % int(time.time())
SID_B = "a4-test-b-%d" % int(time.time())
SID_C = "a4-test-c-%d" % int(time.time())
VAGUE = "招聘后端工程师"
FULL = "招聘 Java 后端工程师。职责：负责交易系统服务端开发。"
FULL += "要求：精通 Java、Spring Boot、MySQL，3 年以上经验，本科及以上学历。"
RESUME = "本科，5 年 Java 后端开发经验，熟悉 Spring Boot、MySQL、Redis。"
ANSWERS = [{"question": "必须技能？", "answer": "Java、Spring Boot、MySQL"},
           {"question": "经验？", "answer": "3 年以上"},
           {"question": "学历？", "answer": "本科及以上"}]
JUNK = [{"question": "必须技能？", "answer": "不知道"}]

RESPONSES = []


def client():
    from fastapi.testclient import TestClient
    return TestClient(app)


def post(c, sid, jd=VAGUE, resume=RESUME, answers=None, enabled=None):
    old = os.environ.get("ASK_ENABLED")
    if enabled is None:
        os.environ.pop("ASK_ENABLED", None)
    else:
        os.environ["ASK_ENABLED"] = enabled
    try:
        payload = {"jd": jd, "resume": resume, "tenant_id": "t-a4", "session_id": sid, "role": "hr"}
        if answers is not None:
            payload["answers"] = answers
        r = c.post("/api/agent/analyze", json=payload)
    finally:
        if old is None:
            os.environ.pop("ASK_ENABLED", None)
        else:
            os.environ["ASK_ENABLED"] = old
    body = r.json() if r.status_code == 200 else {"_status_code": r.status_code}
    RESPONSES.append((sid, body))
    return body


def part_a(c):
    print("=== A. 信息不足 → 提前返回追问 ===")
    b = post(c, SID_A)
    ok = (b.get("status") == "need_more_info" and 1 <= len(b.get("ask", {}).get("questions", [])) <= 3
          and b.get("llm_calls") == 0 and b.get("match_result") is None
          and b.get("interview_questions") == []
          and b.get("recommendation", {}).get("type") == "待定")
    print("  status=%s questions=%d llm_calls=%s 结论=%s" % (
        b.get("status"), len(b.get("ask", {}).get("questions", [])), b.get("llm_calls"),
        b.get("recommendation", {}).get("type")))
    for q in b.get("ask", {}).get("questions", []):
        print("    - %s" % q)
    s = database.fetch_ask_session(SID_A) or {}
    sess_ok = s.get("round") == 1 and s.get("status") == "insufficient" and bool(s.get("pending_questions"))
    print("  session: round=%s status=%s pending=%s %s" % (
        s.get("round"), s.get("status"), bool(s.get("pending_questions")), "✔" if sess_ok else "✘"))
    ok &= sess_ok
    print("  A 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_b(c):
    print("\n=== B. 补充后重走 parse_jd 之后的链路（结论改善）===")
    b = post(c, SID_A, answers=ANSWERS)
    mr = b.get("match_result") or {}
    improved = b.get("status") != "need_more_info" and mr.get("score") is not None
    rec = (b.get("recommendation") or {}).get("type")
    print("  status=%s（无 status 即正常返回）score=%s 结论=%s llm_calls=%s" % (
        b.get("status", "-"), mr.get("score"), rec, b.get("llm_calls")))
    ok = improved and mr.get("score", 0) >= 80 and rec == "推荐"
    s = database.fetch_ask_session(SID_A) or {}
    merged_ok = "【HR 补充信息】" in (s.get("merged_jd") or "")
    print("  session: status=%s round=%s merged_jd 含补充块=%s %s" % (
        s.get("status"), s.get("round"), merged_ok, "✔" if merged_ok else "✘"))
    ok &= merged_ok
    print("  B 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_c(c):
    print("\n=== C. A5 上限：追问 2 轮后走待定（无死循环）===")
    b1 = post(c, SID_B, answers=JUNK)          # 第 1 轮追问（round=1）
    b2 = post(c, SID_B, answers=JUNK)          # 第 2 轮追问（round=2）
    b3 = post(c, SID_B, answers=JUNK)          # 超过上限 → final
    r1 = (b1.get("ask") or {}).get("round")
    r2 = (b2.get("ask") or {}).get("round")
    r3 = (b3.get("ask") or {}).get("round")
    final_ok = (b3.get("status") == "insufficient_final"
                and (b3.get("recommendation") or {}).get("type") == "待定"
                and b3.get("llm_calls") == 0
                and (b3.get("ask") or {}).get("questions") == [])
    print("  第1次 round=%s status=%s；第2次 round=%s status=%s；第3次 round=%s status=%s" % (
        r1, b1.get("status"), r2, b2.get("status"), r3, b3.get("status")))
    ok = r1 == 1 and r2 == 2 and r1 is not None and final_ok
    s = database.fetch_ask_session(SID_B) or {}
    print("  终态: status=%s round=%s；llm_calls=%s %s" % (
        s.get("status"), s.get("round"), b3.get("llm_calls"), "✔" if ok else "✘"))
    print("  C 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_d(c):
    print("\n=== D. 对照组 ASK_ENABLED=0（不进分支）===")
    b = post(c, SID_C, enabled="0")
    ok = (b.get("status") != "need_more_info" and b.get("match_result") is not None
          and "ask" not in b)
    print("  status=%s match_score=%s 结论=%s %s" % (
        b.get("status", "-"), (b.get("match_result") or {}).get("score"),
        (b.get("recommendation") or {}).get("type"), "✔" if ok else "✘"))
    print("  D 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_e(c):
    print("\n=== E. 信息充足时主链路结构不变 ===")
    sid = SID_C + "-full"
    b = post(c, sid, jd=FULL)
    need = ("jd_parse", "match_result", "interview_questions", "recommendation",
            "llm_calls", "total_tokens", "cache_hit", "task_id", "trace_id")
    ok = all(k in b for k in need) and "ask" not in b and b.get("status") is None
    print("  字段齐全=%s 无 ask 字段=%s 结论=%s score=%s %s" % (
        all(k in b for k in need), "ask" not in b,
        (b.get("recommendation") or {}).get("type"), (b.get("match_result") or {}).get("score"),
        "✔" if ok else "✘"))
    print("  E 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def cleanup():
    n_h = n_t = n_s = 0
    for sid, body in RESPONSES:
        tid = body.get("task_id")
        with database.get_conn() as conn:
            if tid:
                n_h += conn.execute("DELETE FROM execution_history WHERE task_id = ?", (tid,)).rowcount
                n_t += conn.execute("DELETE FROM trace_events WHERE task_id = ?", (tid,)).rowcount
    for sid in {SID_A, SID_B, SID_C, SID_C + "-full"}:
        try:
            n_s += 1 if database.delete_ask_session(sid) else 0
        except Exception:
            pass
    print("\n清理（只删本测试创建）: session=%d history=%d trace=%d" % (n_s, n_h, n_t))


if __name__ == "__main__":
    database.init_db()
    _save, _record = database.save_history, trace.record
    database.save_history = lambda *a, **k: None
    trace.record = lambda *a, **k: None
    a = b = cc = d = e = False
    try:
        c = client()
        a, b, cc, d, e = part_a(c), part_b(c), part_c(c), part_d(c), part_e(c)
    finally:
        database.save_history, trace.record = _save, _record
        cleanup()
    allok = all([a, b, cc, d, e])
    print("\n总结果:", "全部通过 ✅" if allok else "存在失败 ❌")
    sys.exit(0 if allok else 1)
