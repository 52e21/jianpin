# -*- coding: utf-8 -*-
"""R6 的注入格式层（纯函数，尚未接线到主链路）。

格式（执行书 R6）：
    岗位能力参考：
    - Spring Boot：能独立搭建 REST 服务，理解 IoC 和 AOP
    - MySQL：能优化慢查询，理解索引原理

约束：
- **只注入面试题生成节点**；不注入 match_resume（匹配打分必须可复现）
- 注入量有上限（条数 + 字符数），避免 token 失控（R7 要对比 token 增幅）
- 检索为空时返回空串，调用方按「无 RAG」路径走（保证可降级）
"""
from __future__ import annotations

from typing import Iterable, Sequence

MAX_ITEMS = 5
MAX_CHARS = 400
HEADER = "岗位能力参考："


def _strip_skill_prefix(text: str, skill: str) -> str:
    """去掉 chunk 正文首部的「技能：」前缀，避免出现重复的技能名。"""
    if skill and text.startswith(skill + "："):
        return text[len(skill) + 1:]
    return text


def format_capability_context(items: Sequence[dict]) -> str:
    """把检索结果格式化成可拼进 prompt 的文本块；空结果返回空串。"""
    lines: list[str] = []
    used = len(HEADER)
    for it in items[:MAX_ITEMS]:
        ch = it.get("chunk", it) if isinstance(it, dict) else it
        meta = ch.get("metadata", {}) or {}
        skill = meta.get("skill", "") or ""
        body = _strip_skill_prefix(ch.get("text", "") or "", skill)
        line = "- %s：%s" % (skill, body) if skill else "- %s" % body
        if used + len(line) + 1 > MAX_CHARS:      # 按「整条」截断，不切半句
            break
        lines.append(line)
        used += len(line) + 1
    if not lines:
        return ""
    return HEADER + "\n" + "\n".join(lines)


def capability_context_for_skills(skills: Iterable[str],
                                  chunks: Sequence[dict] | None = None,
                                  vector_search=None,
                                  top_k: int = MAX_ITEMS) -> dict:
    """技能列表 → 混合检索 → 注入文本块（返回文本 + 诊断信息）。"""
    from .chunker import build_chunks
    from .retriever import hybrid_retrieve

    skills = [s for s in skills if s]
    if not skills:
        return {"text": "", "ids": [], "modes": ["empty_query"], "chars": 0}
    chunks = build_chunks() if chunks is None else chunks
    out = hybrid_retrieve(skills, chunks, vector_search=vector_search, final_k=top_k)
    text = format_capability_context(out["results"])
    return {
        "text": text,
        "ids": [r["chunk"]["chunk_id"] for r in out["results"]][:MAX_ITEMS],
        "modes": out["modes"],
        "chars": len(text),
    }


if __name__ == "__main__":
    from .embedder import encode_query  # noqa: F401  （仅当依赖可用时用于联调）

    demo = capability_context_for_skills(["Spring Boot", "MySQL"])
    print("modes : %s" % demo["modes"])
    print("ids   : %s" % demo["ids"])
    print("chars : %d" % demo["chars"])
    print("---- 注入块预览 ----")
    print(demo["text"])
