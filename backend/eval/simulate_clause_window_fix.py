# -*- coding: utf-8 -*-
"""
事项 3 关键验证：模拟"否定窗口按小句截断"修复，量化影响

用 monkeypatch 临时替换 _contains_token（不做永久改动），跑 200 条并对比：
  1) 与原始基线（baseline.json，用最初的标注）相比：一致率变化
  2) 批次 1 里被建议改标的 34 条，有多少会因为该修复而回到原标
     —— 若回到原标，说明那些"改标建议"是建立在 bug 之上的

用法：python eval/simulate_clause_window_fix.py
"""
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import app.agent as agent          # noqa: E402
import app.config as config        # noqa: E402
import app.database as database    # noqa: E402
import app.trace as trace          # noqa: E402
import app.tools as tools          # noqa: E402

EVAL = Path(__file__).resolve().parent

NEG = ("不会", "不懂", "没有", "未接触", "未使用", "没接触", "没用过", "不熟悉",
       "不了解", "缺乏", "缺少", "只有了解", "仅了解", "了解不多", "了解一点",
       "未掌握", "不精通", "刚学", "在学", "学习中", "未曾", "从未", "没用",
       "没怎么用", "不太会", "不怎么会")
PUNCT = "，。；;、,！!？?：:（）()\n"


def clause_contains_token(resume_text, token):
    """小句窗口版：否定词只在同一小句内生效（按标点截断，空格不算边界）。"""
    lower = (resume_text or "").lower()
    s = (token or "").lower()
    if not s:
        return False
    for start, end in tools._find_spans(lower, s):
        before = lower[max(0, start - 12):start]
        after = lower[end:end + 12]
        for i in range(len(before) - 1, -1, -1):
            if before[i] in PUNCT:
                before = before[i + 1:]
                break
        for i, ch in enumerate(after):
            if ch in PUNCT:
                after = after[:i]
                break
        if any(n in before or n in after for n in NEG):
            continue
        return True
    return False


def run_all(cases):
    preds = {}
    for c in cases:
        agent._analyze_cache.clear()
        r = asyncio.run(agent.analyze_agent(c["jd"], c["resume"], tenant_id="t", session_id="s"))
        preds[c["id"]] = (r["recommendation"]["type"], r["match_result"]["score"])
    return preds


def main():
    database.init_db()
    database.save_history = lambda *a, **k: None
    trace.set_enabled(False)
    config.DEEPSEEK_API_KEY = ""

    cases = [json.loads(l) for l in (EVAL / "eval_set_v1.jsonl").open(encoding="utf-8") if l.strip()]
    gt = {c["id"]: c["gt"]["conclusion"] for c in cases}
    base_pred = {c["id"]: c["pred_conclusion"] for c in
                 json.load((EVAL / "baseline.json").open(encoding="utf-8"))["cases"]}

    print("跑现状…")
    now = run_all(cases)
    print("跑『小句窗口』模拟…")
    original = tools._contains_token
    tools._contains_token = clause_contains_token          # 临时补丁
    try:
        fixed = run_all(cases)
    finally:
        tools._contains_token = original

    agree_now = sum(1 for i in gt if now[i][0] == gt[i])
    agree_fixed = sum(1 for i in gt if fixed[i][0] == gt[i])
    print(f"\n一致率（对原始标注）：现状 {agree_now}/200={agree_now/2:.1f}%  →  小句窗口 {agree_fixed}/200={agree_fixed/2:.1f}%")

    changed = [i for i in gt if now[i][0] != fixed[i][0]]
    print(f"\n结论发生变化的用例：{len(changed)} 条")
    for i in changed[:40]:
        s_now, s_fixed = now[i][1], fixed[i][1]
        c = next(x for x in cases if x["id"] == i)
        print(f"  {i}: {now[i][0]}({s_now}分) → {fixed[i][0]}({s_fixed}分)  期望={gt[i]}  JD={c['jd'][:26]!r}")

    # 关键：批次 1 建议改标的 34 条，有多少会回到原标
    adv_path = EVAL / "review_advice_v1.jsonl"
    if adv_path.exists():
        advice = [json.loads(l) for l in adv_path.open(encoding="utf-8") if l.strip()]
        changed_ids = {a["id"] for a in advice if a["changed"]}
        back = [a for a in advice if a["changed"] and fixed[a["id"]][0] == a["old_gt"]]
        print(f"\n=== 批次 1 的 34 条改标建议在小句窗口下重新评估 ===")
        print(f"  会回到【原标】的：{len(back)} 条（说明这些改标建议建立在 bug 之上）")
        for a in back[:20]:
            print(f"    {a['id']}: 原标={a['old_gt']}  建议改标={a['suggested_gt']}  "
                  f"→ 修复后实际={fixed[a['id']][0]}({fixed[a['id']][1]}分)")
        by_dir = Counter(f"{a['old_gt']}->{a['suggested_gt']}" for a in advice if a["changed"])
        back_dir = Counter(f"{a['old_gt']}->{a['suggested_gt']}" for a in back)
        print(f"  改标方向总计: {dict(by_dir)}")
        print(f"  其中被推翻  : {dict(back_dir)}")


if __name__ == "__main__":
    main()
