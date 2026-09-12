# -*- coding: utf-8 -*-
"""R2：按结构分块（不按固定长度硬切）。

规则（执行书 R2）：
- 一条能力模型 = 一个 chunk
- 只有整条超过 MAX_CHARS 才二次切，且优先按段落、再按句子边界聚合
- 任何情况下都不做「每 150 字一刀」的定长硬切：语义完整性优先于块大小
"""
from __future__ import annotations

import io
import json
import os
import re
from typing import Iterable

MAX_CHARS = 500
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge", "capability_models.jsonl")

# 句子边界（保留分隔符）；再用逗号/顿号做最后一级兜底
_SENT_RE = re.compile(r"[^。！？；!?;]+[。！？；!?;]?")
_CLAUSE_RE = re.compile(r"[^，,、]+[，,、]?")


def load_models(path: str = DATA_PATH) -> list[dict]:
    """读取能力模型 JSONL。"""
    models: list[dict] = []
    with io.open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            for field in ("id", "role", "skill", "capability", "source"):
                if not rec.get(field):
                    raise ValueError("第 %d 行缺少字段 %s" % (lineno, field))
            models.append(rec)
    return models


def _pack(units: Iterable[str], max_chars: int) -> list[str]:
    """把若干语义单元贪心聚合成不超过 max_chars 的块（不切分单元本身）。"""
    out: list[str] = []
    buf = ""
    for u in units:
        if not u:
            continue
        if not buf:
            buf = u
        elif len(buf) + len(u) <= max_chars:
            buf += u
        else:
            out.append(buf)
            buf = u
    if buf:
        out.append(buf)
    return out


def split_long_text(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """超长文本按 段落 -> 句子 -> 分句 逐级聚合切分；单个句子本身超长时仍保持完整。"""
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    for para in [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]:
        if len(para) <= max_chars:
            pieces.append(para)
            continue
        for sent_group in _pack(_SENT_RE.findall(para), max_chars):
            if len(sent_group) <= max_chars:
                pieces.append(sent_group)
                continue
            for clause_group in _pack(_CLAUSE_RE.findall(sent_group), max_chars):
                pieces.append(clause_group)  # 兜底：仍超长也保留完整分句，不硬切
    return pieces


def chunk_model(rec: dict, max_chars: int = MAX_CHARS) -> list[dict]:
    """一条能力模型 -> 1~N 个 chunk（带 metadata）。"""
    text = rec["capability"].strip()
    pieces = split_long_text(text, max_chars)
    total = len(pieces)
    chunks = []
    for i, piece in enumerate(pieces):
        chunks.append({
            "chunk_id": "%s#%d" % (rec["id"], i),
            "text": "%s：%s" % (rec["skill"], piece) if i == 0 else piece,
            "metadata": {
                "id": rec["id"],
                "role": rec["role"],
                "skill": rec["skill"],
                "source": rec["source"],
                "part": i,
                "parts": total,
            },
        })
    return chunks


def build_chunks(models: list[dict] | None = None, max_chars: int = MAX_CHARS) -> list[dict]:
    models = load_models() if models is None else models
    out: list[dict] = []
    for rec in models:
        out.extend(chunk_model(rec, max_chars))
    return out


if __name__ == "__main__":
    models = load_models()
    chunks = build_chunks(models)
    per_model = {}
    for c in chunks:
        per_model[c["metadata"]["id"]] = per_model.get(c["metadata"]["id"], 0) + 1
    counts = sorted(per_model.values())
    print("models      : %d" % len(models))
    print("chunks      : %d" % len(chunks))
    print("每条的块数  : min=%d max=%d  分布=%s" % (
        counts[0], counts[-1], {n: counts.count(n) for n in sorted(set(counts))}))
    print("块文本长度  : min=%d max=%d (阈值 %d)" % (
        min(len(c["text"]) for c in chunks), max(len(c["text"]) for c in chunks), MAX_CHARS))
    worst = max(chunks, key=lambda c: len(c["text"]))
    print("最长块示例  : %s -> %s" % (worst["chunk_id"], worst["text"][:60]))
    print("metadata 键 : %s" % sorted(chunks[0]["metadata"].keys()))
