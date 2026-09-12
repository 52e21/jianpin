# -*- coding: utf-8 -*-
"""
修复验收：「点采纳 404」——缓存命中返回悬空 task_id

原缺陷（事项 5 验证时发现）：
  1) analyze_agent 命中缓存时提前 return，**不写历史行**；
  2) 缓存里存的是**最初那次任务的 task_id**。
  → 该历史行一旦被删除（前端有单条删除/清空功能），点「采纳/改判」即 404。

修复后应满足：
  A. 缓存命中也返回**自己的新 task_id**（与最初那次不同）
  B. 缓存命中也**写一条历史行**（cache_hit=1），该 task_id 可被反馈接口命中
  C. 返回体保留 cache_source_task_id，可回溯最初那次运行
  D. 删掉最初那条历史行后，对新 task_id 提交反馈仍然成功（不再 404）
  E. 结论/分数与最初那次一致（缓存语义不变）

用法：python eval/test_feedback_after_cache.py
"""
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import app.agent as agent          # noqa: E402
import app.config as config        # noqa: E402
import app.database as database    # noqa: E402
import app.trace as trace          # noqa: E402

DB = BACKEND / "data" / "history.db"
JD = "招聘Java开发工程师，要求精通Java与SpringBoot。"
RESUME = "候选人，3年Java经验，精通Java与SpringBoot。"


def hist(task_id):
    con = sqlite3.connect(DB)
    row = con.execute("SELECT task_id, cache_hit, feedback, feedback_at FROM execution_history "
                      "WHERE task_id=?", (task_id,)).fetchone()
    con.close()
    return row


def main():
    database.init_db()
    trace.set_enabled(False)
    config.DEEPSEEK_API_KEY = ""
    ok = True

    agent._analyze_cache.clear()
    r1 = asyncio.run(agent.analyze_agent(JD, RESUME, tenant_id="fixtest", session_id="s1"))
    r2 = asyncio.run(agent.analyze_agent(JD, RESUME, tenant_id="fixtest", session_id="s1"))

    print("=== 修复验收 ===")
    print(f"  第1次: task_id={r1['task_id']}  cache_hit={r1['cache_hit']}")
    print(f"  第2次: task_id={r2['task_id']}  cache_hit={r2['cache_hit']}  "
          f"cache_source_task_id={r2.get('cache_source_task_id')}")

    a = r2["task_id"] != r1["task_id"]
    b = hist(r2["task_id"]) is not None and hist(r2["task_id"])[1] == 1
    c = r2.get("cache_source_task_id") == r1["task_id"]
    e = (r1["recommendation"]["type"] == r2["recommendation"]["type"]
         and r1["match_result"]["score"] == r2["match_result"]["score"])
    print(f"  {'OK  ' if a else 'FAIL'} A 命中缓存返回新 task_id")
    print(f"  {'OK  ' if b else 'FAIL'} B 命中缓存也写历史行（cache_hit=1）")
    print(f"  {'OK  ' if c else 'FAIL'} C 保留 cache_source_task_id 可回溯")
    print(f"  {'OK  ' if e else 'FAIL'} E 结论与分数与首次一致（缓存语义不变）")
    ok &= a and b and c and e

    # D. 删掉最初那条历史 → 对新 task_id 提交反馈仍成功
    con = sqlite3.connect(DB)
    con.execute("DELETE FROM execution_history WHERE task_id=?", (r1["task_id"],))
    con.commit()
    con.close()
    print(f"\n  已删除最初那条历史（task_id={r1['task_id']}）")
    res = database.set_feedback(r2["task_id"], json.dumps({"action": "采纳"}, ensure_ascii=False))
    d = res["updated"] == 1
    print(f"  对新 task_id 提交反馈: updated={res['updated']} → {'成功 ✔' if d else '仍失败 ✘'}")
    ok &= d
    print(f"  {'OK  ' if d else 'FAIL'} D 兜底：删掉原历史后反馈不再 404")

    # 清理
    con = sqlite3.connect(DB)
    for t in (r1["task_id"], r2["task_id"]):
        con.execute("DELETE FROM execution_history WHERE task_id=?", (t,))
        con.execute("DELETE FROM trace_events WHERE task_id=?", (t,))
    con.commit()
    left = con.execute("SELECT COUNT(*) FROM execution_history").fetchone()[0]
    con.close()
    print(f"\n  已清理测试数据；当前 history 行数={left}")

    print("\n总结果:", "全部通过 ✅" if ok else "存在失败 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
