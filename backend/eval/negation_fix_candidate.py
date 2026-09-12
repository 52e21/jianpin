# -*- coding: utf-8 -*-
"""
「否定窗口按小句截断」修复候选实现（尚未合入 app/tools.py）

现状：_contains_token 取前后各 12 字符找否定词，**会跨过标点**，于是
      "精通 Java 与 Spring Boot，不熟悉 MySQL" 里的 Spring Boot 被邻居的"不熟悉"误伤。

本模块提供小句窗口版实现 + 一个上下文管理器，供诊断/模拟/复核脚本临时接入。
标点才算小句边界，**空格不算**（否则"不会 React"这种合法相邻否定会被漏掉）。
"""
from contextlib import contextmanager

import app.tools as tools

NEG = ("不会", "不懂", "没有", "未接触", "未使用", "没接触", "没用过", "不熟悉",
       "不了解", "缺乏", "缺少", "只有了解", "仅了解", "了解不多", "了解一点",
       "未掌握", "不精通", "刚学", "在学", "学习中", "未曾", "从未", "没用",
       "没怎么用", "不太会", "不怎么会")
PUNCT = "，。；;、,！!？?：:（）()\n"


def clause_contains_token(resume_text, token):
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


@contextmanager
def patched():
    """临时启用小句窗口版否定判定。"""
    original = tools._contains_token
    tools._contains_token = clause_contains_token
    try:
        yield
    finally:
        tools._contains_token = original
