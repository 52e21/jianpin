# -*- coding: utf-8 -*-
"""
事项 3 诊断：把"技能字面存在却没命中"拆成【正确未命中】与【窗口误伤】

方法：对每一对 (用例, 技能)，取技能在简历中的每次出现，分别用
  - 现状窗口：前后各 12 字符
  - 小句窗口：先按标点截断，再取前后各 12 字符
判断是否命中，对比两者差异。差异即"否定窗口跨小句造成的误伤"。
"""
import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

EVAL = Path(__file__).resolve().parent

NEG = ("不会", "不懂", "没有", "未接触", "未使用", "没接触", "没用过", "不熟悉",
       "不了解", "缺乏", "缺少", "只有了解", "仅了解", "了解不多", "了解一点",
       "未掌握", "不精通", "刚学", "在学", "学习中", "未曾", "从未", "没用",
       "没怎么用", "不太会", "不怎么会")
# 小句边界只算真正的标点与换行；**空格不算**——"不会 React" 是合法的相邻否定，
# 若把空格当边界就会把它误判成"窗口误伤"（我第一版就犯了这个错）。
PUNCT = "，。；;、,！!？?：:（）()\n"

from app.tools import _find_spans   # noqa: E402


def negated(text_low, start, end, clause_bounded):
    before = text_low[max(0, start - 12):start]
    after = text_low[end:end + 12]
    if clause_bounded:
        # 往前截到最后一个标点之后；往后截到第一个标点之前
        for i in range(len(before) - 1, -1, -1):
            if before[i] in PUNCT:
                before = before[i + 1:]
                break
        for i, ch in enumerate(after):
            if ch in PUNCT:
                after = after[:i]
                break
    return any(n in before or n in after for n in NEG)


def matches(text, skill, clause_bounded):
    low = text.lower()
    for s, e in _find_spans(low, skill):
        if not negated(low, s, e, clause_bounded):
            return True
    return False


def main():
    from app.tools import parse_jd
    cases = [json.loads(l) for l in (EVAL / "eval_set_v1.jsonl").open(encoding="utf-8") if l.strip()]

    literal_but_missing, fixable, legit = [], [], []
    for c in cases:
        jp = parse_jd(c["jd"])
        skills = list(jp["skills"]["required"]) + list(jp["skills"]["preferred"])
        resume = c["resume"] or ""
        for s in skills:
            if not _find_spans(resume.lower(), s):
                continue                      # 字面不存在 → 与窗口无关
            now = matches(resume, s, clause_bounded=False)
            fixed = matches(resume, s, clause_bounded=True)
            if now and not fixed:
                print(f"  ⚠ 反向：{c['id']} 技能={s} 现状命中、小句窗口不命中（需检查）")
            if not now and fixed:
                literal_but_missing.append((c["id"], s))
                fixable.append((c["id"], s, c["resume"][:64]))
            elif not now:
                legit.append((c["id"], s))

    print("=== 结论 ===")
    print(f"  「字面存在但未命中」总实例：{len(literal_but_missing) + len(legit)}")
    print(f"    其中【正确未命中】(真实否定 / 词形严格匹配)：{len(legit)}")
    print(f"    其中【否定窗口跨小句误伤】：{len(fixable)}  ← 这才是缺陷")
    print("\n  误伤明细（改成小句窗口即可命中）：")
    for cid, s, snippet in fixable:
        print(f"    {cid}: 「{s}」 | {snippet}")
    print("\n  正确未命中抽样（前 12 条，证明不是缺陷）：")
    for cid, s in legit[:12]:
        print(f"    {cid}: 「{s}」")


if __name__ == "__main__":
    main()
