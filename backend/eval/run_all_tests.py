# -*- coding: utf-8 -*-
"""
统一测试跑批器：跑 eval/test_*.py 全部测试，并对"测试写入的库行"做受控清理。

为什么需要它：
  项目纪律是"测试只能删自己创建的行"，但测试分散在各文件、很容易漏掉新增的写入
  （A1/A4 新加 ask_sessions 后，就出现了 2 行残留）。这里在每个测试前后快照
  execution_history / trace_events / ask_sessions，跑完删除"本次跑批新增"的行，
  并**按测试名归因**，便于后续把屏蔽补到源头。

用法：python eval/run_all_tests.py
"""
import io
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
EVAL = Path(__file__).resolve().parent
DB = BACKEND / "data" / "history.db"
TABLES = ("execution_history", "trace_events", "ask_sessions")
KEY = {"execution_history": "id", "trace_events": "id", "ask_sessions": "session_id"}


def snapshot() -> dict:
    out = {}
    with sqlite3.connect(DB) as c:
        for t in TABLES:
            out[t] = {r[0] for r in c.execute("SELECT %s FROM %s" % (KEY[t], t))}
    return out


def new_rows(before: dict, after: dict) -> dict:
    return {t: sorted(after[t] - before[t]) for t in TABLES if after[t] - before[t]}


def cleanup(inside: dict) -> int:
    """删除本次跑批期间新增的行（只删新增，不碰原有）。"""
    n = 0
    with sqlite3.connect(DB) as c:
        for t, vals in inside.items():
            for v in vals:
                n += c.execute("DELETE FROM %s WHERE %s = ?" % (t, KEY[t]), (v,)).rowcount
    return n


def main():
    tests = sorted(EVAL.glob("test_*.py"))
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("ASK_ENABLED", None)          # 用产品默认值（分支开启）
    env.pop("RAG_ENABLED", None)

    base = snapshot()
    results, leaks = [], {}
    for t in tests:
        before = snapshot()
        r = subprocess.run([sys.executable, str(t)], cwd=str(BACKEND), env=env,
                           capture_output=True, text=True)
        after = snapshot()
        made = new_rows(before, after)
        if made:
            leaks[t.name] = made
        results.append((t.name, r.returncode))
        # 逐个测试即时清理，避免后一个测试的快照被前一个的残留污染
        cleanup(made)
        print("  %-34s %s%s" % (t.name, "PASS" if r.returncode == 0 else "FAIL(%d)" % r.returncode,
                                ("   清理: " + ", ".join("%s=%d" % (k, len(v)) for k, v in made.items()))
                                if made else ""))

    print("\n=== 汇总 ===")
    ok = sum(1 for _, rc in results if rc == 0)
    print("  通过: %d / %d" % (ok, len(results)))
    print("  写入库的测试（需把屏蔽补到源头）: %s" % (
        ", ".join("%s[%s]" % (n, ";".join("%s=%d" % (k, len(v)) for k, v in d.items()))
                  for n, d in leaks.items()) or "无 ✔"))
    now = snapshot()
    print("  数据库终态: " + ", ".join("%s=%d" % (t, len(now[t])) for t in TABLES))
    print("  与跑批前一致: %s" % all(base[t] == now[t] for t in TABLES))
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
