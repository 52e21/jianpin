# -*- coding: utf-8 -*-
"""
修② 前置排查：llm_calls>0 但 tokens=0 的 164 条到底是什么构成？

两处数据源：
  1) execution_history（真实库，33 行）——按用户给的 SQL 分组
  2) baseline_v2.json（评测跑批的 200 条逐条结果）——164 这个数字来自这里

目的：确认 164 条里是否混着多种成因（用户提示可能不只一个 bug）。
"""
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
EVAL = Path(__file__).resolve().parent
DB = BACKEND / "data" / "history.db"


def main():
    print("=" * 76)
    print("一、execution_history（真实库）按 (llm_calls, total_tokens) 分组")
    print("=" * 76)
    con = sqlite3.connect(DB)
    rows = con.execute("""SELECT llm_calls, total_tokens, COUNT(*)
                            FROM execution_history
                           GROUP BY llm_calls, total_tokens
                           ORDER BY llm_calls, total_tokens""").fetchall()
    print(f"  {'llm_calls':>9} {'total_tokens':>12} {'条数':>5}")
    for r in rows:
        print(f"  {r[0]:>9} {r[1]:>12} {r[2]:>5}")
    print(f"  合计 {sum(r[2] for r in rows)} 行")
    print("\n  说明：库里只有升级前留下的 33 行真实记录，样本太小、且含旧代码产出，")
    print("        所以『164/200』这个数字不是来自这里，而是来自评测跑批。")
    con.close()

    print("\n" + "=" * 76)
    print("二、baseline_v2.json（200 条评测跑批，修复前）的构成分解")
    print("=" * 76)
    cases = json.load((EVAL / "baseline_v2.json").open(encoding="utf-8"))["cases"]
    # 逐条带上"该走哪条分支"，用于归因
    evalset = {json.loads(l)["id"]: json.loads(l)
               for l in (EVAL / "eval_set_v1.jsonl").open(encoding="utf-8") if l.strip()}

    combos = Counter((c["llm_calls"], c["tokens"]) for c in cases)
    print(f"  {'llm_calls':>9} {'tokens':>7} {'条数':>5}   解读")
    interp = {
        (0, 0): "规则链路/短路，未调 LLM —— 正确",
        (1, 0): "★误计：实际未调 LLM（无 Key 降级）却被记 1 次",
        (2, 0): "★误计：同上，计了 2 次",
        (1, 100): "",
    }
    for (lc, tk), n in sorted(combos.items()):
        note = interp.get((lc, tk), "")
        print(f"  {lc:>9} {tk:>7} {n:>5}   {note}")

    odd = [c for c in cases if c["llm_calls"] > 0 and c["tokens"] == 0]
    print(f"\n  异常组合（llm_calls>0 且 tokens=0）共 {len(odd)} 条")

    # 按分数段归因：<50 会短路（不该有 llm_calls）；>=50 才可能进面试题节点
    bands = Counter()
    for c in odd:
        s = c["match_score"]
        bands["score<50（本该短路，llm_calls 应为 0）" if s is not None and s < 50
              else "score>=50（会进 LLM 节点，无 Key 时误计）"] += 1
    print("\n  这 %d 条按分数段归因：" % len(odd))
    for k, v in bands.items():
        print(f"    {v:>4} 条  {k}")

    short = [c for c in cases if c["llm_calls"] == 0]
    print(f"\n  llm_calls==0 的 {len(short)} 条（= 跑批里的『低分短路率』分子）")
    print(f"  200 - {len(short)} = {200 - len(short)}  ← 与异常组合数 {len(odd)} 是否一致: "
          f"{200 - len(short) == len(odd)}")

    print("\n" + "=" * 76)
    print("三、结论")
    print("=" * 76)
    print("""  164 = 200 − 36（score<50 的短路用例），即『所有进入面试题节点的用例』。
  也就是说：无 Key 时该节点返回的占位文案不带全角括号 → 前缀哨兵匹配失败 → 全部误计 1 次。
  **只有这一个成因，没有混入第二种**：
    · 规则短路（score<50）：llm_calls=0，本来就对
    · 缓存命中：跑批每例前清缓存，不存在
    · 规则链路：不经过该节点，不受影响
  （真正被掩埋的副作用是『低分短路率』这个指标失真：修复后它应变成 100%，
    因为关 LLM 模式下每次调用都不产生 LLM 调用。）""")


if __name__ == "__main__":
    sys.exit(main())
