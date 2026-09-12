# -*- coding: utf-8 -*-
"""
第 7 步冒烟测试：POST /api/agent/feedback

覆盖：
  1) 正常写入（action=改判 + new_conclusion）
  2) 参数校验：缺 action / action 非法 / 改判缺 new_conclusion / task_id 不存在
  3) 落库校验：execution_history.feedback / feedback_at / task_id
  4) 清理本次测试产生的历史行

用法：python eval/test_feedback_api.py
"""
import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import app.agent as agent          # noqa: E402
import app.config as config        # noqa: E402
import app.database as database    # noqa: E402
import app.trace as trace          # noqa: E402
from app.main import app           # noqa: E402

try:
    from fastapi.testclient import TestClient
except Exception as e:             # pragma: no cover
    print("无法导入 TestClient（需要 httpx）:", e)
    sys.exit(2)


def main():
    database.init_db()
    trace.set_enabled(False)
    client = TestClient(app)

    # 造一条真实分析记录（关 LLM，快且零成本；目的是拿 task_id）
    config.DEEPSEEK_API_KEY = ""
    agent._analyze_cache.clear()
    r = asyncio.run(agent.analyze_agent("招聘Java开发工程师，要求精通Java与SpringBoot。",
                                        "候选人，3年Java经验，精通Java与SpringBoot。"))
    task_id = r["task_id"]
    print(f"1) 造数据：task_id={task_id} 结论={r['recommendation']['type']}")

    ok = True

    # --- 正常写入 ---
    resp = client.post("/api/agent/feedback", json={
        "task_id": task_id, "action": "改判", "new_conclusion": "待定", "comment": "经验偏浅，建议先面"})
    print(f"2) 正常写入 HTTP={resp.status_code} body={resp.json()}")
    ok &= resp.status_code == 200 and resp.json().get("action") == "改判"

    row = database.fetch_history_by_task(task_id)
    fb = json.loads(row["feedback"]) if row and row["feedback"] else {}
    print(f"3) 落库校验 feedback={row['feedback']}")
    print(f"   feedback_at={row['feedback_at']}  task_id={row['task_id']}")
    ok &= bool(row) and fb.get("action") == "改判" and fb.get("new_conclusion") == "待定" \
        and fb.get("original_conclusion") == r["recommendation"]["type"] and bool(row["feedback_at"])

    # --- 覆盖写入（采纳）---
    resp2 = client.post("/api/agent/feedback", json={"task_id": task_id, "action": "采纳"})
    row2 = database.fetch_history_by_task(task_id)
    print(f"4) 覆盖写入 HTTP={resp2.status_code} feedback={row2['feedback']}")
    ok &= resp2.status_code == 200 and json.loads(row2["feedback"])["action"] == "采纳"

    # --- 参数校验 ---
    cases = [
        ({"action": "采纳"}, 400, "缺 task_id"),
        ({"task_id": task_id, "action": "点赞"}, 400, "action 非法"),
        ({"task_id": task_id, "action": "改判"}, 400, "改判缺 new_conclusion"),
        ({"task_id": task_id, "action": "改判", "new_conclusion": "很好"}, 400, "new_conclusion 非法"),
        ({"task_id": "tk_not_exist", "action": "采纳"}, 404, "task_id 不存在"),
    ]
    print("5) 参数校验：")
    for payload, expect, desc in cases:
        r3 = client.post("/api/agent/feedback", json=payload)
        good = r3.status_code == expect
        ok &= good
        print(f"   {'OK ' if good else 'FAIL'} {desc:<28} 期望{expect} 实际{r3.status_code}  {r3.json().get('detail','')}")

    # --- 清理测试数据 ---
    with database.get_conn() as conn:
        conn.execute("DELETE FROM execution_history WHERE task_id = ?", (task_id,))
        conn.execute("DELETE FROM trace_events WHERE task_id = ?", (task_id,))
    print(f"6) 已清理测试数据；该 task_id 残留记录数={database.fetch_history_by_task(task_id) is not None}")

    print("\n结果:", "全部通过 ✅" if ok else "存在失败 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
