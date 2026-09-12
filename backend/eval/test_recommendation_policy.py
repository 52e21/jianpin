# -*- coding: utf-8 -*-
"""
推荐口径闸门（"拍口径"的落地）

口径（已拍定）：需求文档 §5 `匹配度 ≥80 且缺失必须技能 ≤1 → 推荐`
    → **允许缺 1 项必须技能仍推荐**（技能维度只占 40% 权重，其余维度足以支撑 ≥80 分）。

本测试有两层作用：
  1. 锁住常量值 —— 谁要改口径，必须先改这里，形成"改口径要过闸门"的约束；
  2. 锁住行为 —— 分界点的四象限都要断言，避免规则被无意改动。

注意：中间区间（50–79）在**无 Key** 时会走规则兜底为"待定"，因此断言写"不得为推荐"。

用法：python eval/test_recommendation_policy.py
"""
import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import app.config as config        # noqa: E402
import app.database as database    # noqa: E402
import app.trace as trace          # noqa: E402
from app.tools import (MAX_MISSING_REQUIRED_FOR_RECOMMEND,   # noqa: E402
                       summarize_recommendation)

# 分界点四象限：(分数, 缺失必须技能数, 期望结论)
CASES = [
    (95, 0, "推荐"),
    (85, 1, "推荐"),      # ★ 口径锁定点：缺 1 项仍推荐
    (85, 2, "非推荐"),    # 缺 2 项 → 不得推荐（无 Key 时落到待定）
    (80, 1, "推荐"),      # 边界：恰好 80
    (79, 0, "非推荐"),    # 边界：差 1 分
    (79, 1, "非推荐"),
    (60, 0, "非推荐"),
    (49, 0, "不推荐"),
    (0, 0, "不推荐"),
]


def main():
    database.init_db()
    database.save_history = lambda *a, **k: None
    trace.set_enabled(False)
    config.DEEPSEEK_API_KEY = ""          # 关 LLM：关注规则分支
    ok = True

    print("=== 口径闸门 ===")
    gate = MAX_MISSING_REQUIRED_FOR_RECOMMEND == 1
    ok &= gate
    print(f"  {'OK  ' if gate else 'FAIL'} MAX_MISSING_REQUIRED_FOR_RECOMMEND = "
          f"{MAX_MISSING_REQUIRED_FOR_RECOMMEND}（期望 1：允许缺 1 项仍推荐）")
    print("  说明：改成 0 等于「必须技能一项都不能缺」，属产品决策，需同步更新本测试与升级报告。")

    print("\n=== 行为断言（分界点四象限）===")
    print(f"  {'分数':>4} {'缺失必须技能':>12} {'期望':<6} {'实际':<6} 结果")
    for score, n_missing, expect in CASES:
        missing = [f"技能{i}" for i in range(n_missing)]
        rec = asyncio.run(summarize_recommendation(score, ["命中技能"], missing, ["Q"], {}))
        got = rec["conclusion"]
        if expect == "非推荐":
            good = got != "推荐"
        else:
            good = got == expect
        ok &= good
        print(f"  {score:>4} {n_missing:>12} {expect:<6} {got:<6} {'OK' if good else 'FAIL'}")

    print("\n总结果:", "全部通过 ✅" if ok else "存在失败 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
