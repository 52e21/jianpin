# -*- coding: utf-8 -*-
"""
A2 验收：JD 信息不足判定（规则优先，零 LLM）

覆盖：
  A. 规则判定：空 JD / 一句话 / 只有技能 / 词表没覆盖但有技能表述 / 完整 JD
  B. 阈值校准：200 条评测集上「字面规则 7 条 vs 校准规则 6 条」，并证明消歧生效（E056 不再被误判）
  C. 纯函数：不写库、不调 LLM（调用前后 DB 行数不变）
  D. A5 轮数口径：should_ask(round) 在 round<2 允许、>=2 不允许
  E. 未接线的 sufficient 路径：信息充足时主链路结论不受影响

用法：python eval/test_agent_insufficient.py
"""
import io
import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import app.database as database          # noqa: E402
import app.trace as trace                # noqa: E402
from app.ask import ROUND_LIMIT, should_ask, sufficiency   # noqa: E402
from app.tools import parse_jd           # noqa: E402

EVAL = Path(__file__).resolve().parent


def part_a():
    print("=== A. 规则判定 ===")
    cases = [
        ("空 JD", "", "insufficient"),
        ("只有一句话", "招聘前端。", "insufficient"),
        ("只有技能", "招聘前端工程师，要求精通 React。", "sufficient"),
        ("技能但词表没覆盖", "招聘测试工程师，要求熟悉自动化测试与 Selenium，了解 JMeter。", "sufficient"),
        ("完整 JD", "招聘 Java 后端工程师。职责：负责交易系统服务端开发。"
                    "要求：精通 Java、Spring Boot、MySQL，3 年以上经验，本科及以上学历。", "sufficient"),
    ]
    ok = True
    for name, jd, expect in cases:
        r = sufficiency(parse_jd(jd), jd)
        good = r["status"] == expect
        ok &= good
        print("  %-16s -> %-12s (期望 %-12s) %s  reason=%s" % (
            name, r["status"], expect, "✔" if good else "✘", r["reason"] or "-"))
    print("  A 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_b():
    print("\n=== B. 200 条评测集校准 ===")
    tot = literal = refined = 0
    avoid = []
    flagged = []
    for line in io.open(EVAL / "eval_set_v1_1.jsonl", encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        c = json.loads(line)
        r = sufficiency(parse_jd(c["jd"]), c["jd"])
        tot += 1
        if r["status"] == "insufficient":
            refined += 1
            flagged.append(c["id"])
        if r["doc_rule"]["status"] == "insufficient":
            literal += 1
            if r["status"] == "sufficient":
                avoid.append(c["id"])
    ok = tot == 200 and refined == 6 and literal == 7 and avoid == ["E056"]
    print("  样本 %d 条；字面规则 %d 条、校准规则 %d 条；消歧 %s" % (tot, literal, refined, avoid))
    print("  仍判不足: %s" % flagged)
    print("  B 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_c():
    print("\n=== C. 纯函数（不写库、零 LLM）===")
    def counts():
        with database.get_conn() as conn:
            return tuple(conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
                         for t in ("execution_history", "trace_events", "ask_sessions"))
    before = counts()
    for _ in range(50):
        sufficiency(parse_jd("招聘后端工程师。要求精通 Go。"), "招聘后端工程师。要求精通 Go。")
    after = counts()
    ok = before == after
    print("  调用 50 次前后 DB 行数: %s -> %s %s" % (before, after, "✔" if ok else "✘"))
    print("  C 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_d():
    print("\n=== D. A5 轮数口径（上限 %d 轮）===" % ROUND_LIMIT)
    seq = [("%d" % r, should_ask(r)) for r in range(ROUND_LIMIT + 2)]
    expect = [("0", True), ("1", True), ("2", False), ("3", False)]
    ok = seq == expect
    print("  should_ask: %s %s" % (seq, "✔" if ok else "✘"))
    print("  sufficient 时永不追问: %s" % (should_ask(0, "sufficient") is False))
    ok &= should_ask(0, "sufficient") is False
    print("  D 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_e():
    print("\n=== E. 信息充足时主链路不受影响（A2 尚未接线）===")
    from fastapi.testclient import TestClient
    from app.main import app

    sid = "a2-test-%d" % int(time.time())
    jd = "招聘前端工程师，要求精通 React 与 TypeScript，3 年经验。"
    resume = "会计专业，做过 5 年财务核算。"
    c = TestClient(app)
    r = c.post("/api/agent/analyze", json={"jd": jd, "resume": resume, "tenant_id": "t-a2",
                                          "session_id": sid, "role": "hr"})
    body = r.json() if r.status_code == 200 else {}
    r2 = sufficiency(parse_jd(jd), jd)
    ok = r.status_code == 200 and "recommendation" in body and r2["status"] == "sufficient"
    print("  HTTP %s 结论=%s；该 JD 判定=%s %s" % (
        r.status_code, (body.get("recommendation") or {}).get("type"), r2["status"], "✔" if ok else "✘"))
    # 清理
    tid = body.get("task_id")
    with database.get_conn() as conn:
        if tid:
            conn.execute("DELETE FROM execution_history WHERE task_id = ?", (tid,))
            conn.execute("DELETE FROM trace_events WHERE task_id = ?", (tid,))
    database.delete_ask_session(sid)
    print("  E 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":
    database.init_db()
    _save, _record = database.save_history, trace.record
    database.save_history = lambda *a, **k: None
    database.upsert_ask_session = lambda *a, **k: None   # A1/A4：测试不写追问会话状态
    trace.record = lambda *a, **k: None
    a = b = c_ = d = e = False
    try:
        a, b, c_, d, e = part_a(), part_b(), part_c(), part_d(), part_e()
    finally:
        database.save_history, trace.record = _save, _record
    allok = all([a, b, c_, d, e])
    print("\n总结果:", "全部通过 ✅" if allok else "存在失败 ❌")
    sys.exit(0 if allok else 1)
