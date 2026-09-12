# -*- coding: utf-8 -*-
"""
缺陷复现：缓存命中返回"原任务的 task_id"，一旦该历史行被删除，反馈就 404

由来：事项 5（第 8 步前端点击验证）的接口级 E2E 中意外撞到——
      第二次 analyze 命中缓存，返回的 task_id 与第一次完全相同；
      而清理（或用户在前端"删除历史记录"）删掉了那一行，
      于是点"采纳/改判"时 /api/agent/feedback 返回 404。

两条成因叠加：
  1) analyze_agent 命中缓存时**提前 return，不写历史行**；
  2) 缓存里存的是**最初那次任务的 task_id**（我在第 5 步为"可回溯 Trace"刻意这么设计的）。

本脚本只做复现与取证，不修改任何代码；结束时清理测试数据。
"""
import asyncio
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


def rows_by_task(task_id):
    con = sqlite3.connect(DB)
    n = con.execute("SELECT COUNT(*) FROM execution_history WHERE task_id=?", (task_id,)).fetchone()[0]
    con.close()
    return n


def main():
    database.init_db()
    trace.set_enabled(False)
    config.DEEPSEEK_API_KEY = ""          # 关 LLM，快
    # 注意：这里**故意不**屏蔽 save_history —— 本缺陷正是关于历史行
    created = []

    print("=== 复现步骤 ===")
    agent._analyze_cache.clear()
    r1 = asyncio.run(agent.analyze_agent(JD, RESUME, tenant_id="bugdemo", session_id="s1"))
    created.append(r1["task_id"])
    print(f"  第 1 次 analyze: task_id={r1['task_id']}  cache_hit={r1['cache_hit']}  "
          f"历史行数={rows_by_task(r1['task_id'])}")

    r2 = asyncio.run(agent.analyze_agent(JD, RESUME, tenant_id="bugdemo", session_id="s1"))
    created.append(r2["task_id"])
    print(f"  第 2 次 analyze: task_id={r2['task_id']}  cache_hit={r2['cache_hit']}  "
          f"历史行数={rows_by_task(r2['task_id'])}")
    same = r1["task_id"] == r2["task_id"]
    print(f"  → 两次返回的 task_id 是否相同: {same}（缓存命中复用了原任务标识）")

    print("\n  模拟用户在前端删除该条历史记录…")
    con = sqlite3.connect(DB)
    con.execute("DELETE FROM execution_history WHERE task_id=?", (r2["task_id"],))
    con.commit()
    con.close()
    print(f"  删除后该 task_id 的历史行数: {rows_by_task(r2['task_id'])}")

    print("\n  用户此时点击「采纳」→ 调用 set_feedback（等价于接口 404 判定）")
    res = database.set_feedback(r2["task_id"], '{"action":"采纳"}')
    print(f"  set_feedback 返回: {res}")
    bug = res["updated"] == 0
    print(f"  → 是否复现『反馈失败』: {bug}")

    # 清理
    con = sqlite3.connect(DB)
    for t in created:
        con.execute("DELETE FROM execution_history WHERE task_id=?", (t,))
        con.execute("DELETE FROM trace_events WHERE task_id=?", (t,))
    con.commit()
    left = con.execute("SELECT COUNT(*) FROM execution_history").fetchone()[0]
    con.close()
    print(f"\n  已清理测试数据；当前 history 行数={left}")

    print("\n=== 结论 ===")
    if bug:
        print("  缺陷成立：缓存命中返回原 task_id，且命中时不写历史行；")
        print("  该历史行一旦被删除（前端有删除/清空功能），反馈接口即 404。")
    else:
        print("  缺陷【已修复】：缓存命中会返回**新的 task_id** 并写入自己的历史行，")
        print("  因此删除最初那条历史后，反馈仍能成功（见 test_feedback_after_cache.py）。")
    return 0 if bug else 1


if __name__ == "__main__":
    sys.exit(main())
