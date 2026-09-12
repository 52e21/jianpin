# -*- coding: utf-8 -*-
"""R3：向量化 —— 用中文检索模型编码所有 chunk。

要点：
- 模型优先用**本地快照**（`backend/.models/<模型名>` 或环境变量 `RAG_EMBED_MODEL_PATH`）。
  原因：沙箱只允许写工作区内，sentence-transformers 直接下模型会写 `~/.cache/huggingface` 被拒。
- 编码统一 `normalize_embeddings=True`：余弦相似度可直接比较，且结果可复现。
- 依赖 `sentence-transformers`（可选依赖，**延迟导入**）：
  没装时只有真正调用编码才会报错，不影响主链路与其它 RAG 组件。
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Iterable, Sequence

# 中文检索模型；bge-small-zh-v1.5 是检索向（非对称 query/doc 用法），体积小、CPU 可跑
DEFAULT_MODEL = os.environ.get("RAG_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
# bge 系列官方建议的检索指令前缀（只在 query 侧使用）
QUERY_PREFIX = os.environ.get("RAG_QUERY_PREFIX", "为这个句子生成表示以用于检索相关文章：")

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
MODELS_DIR = os.environ.get("RAG_MODELS_DIR", os.path.join(_BACKEND_DIR, ".models"))

_MODEL = None


def local_model_path(model_name: str | None = None) -> str | None:
    """返回本地快照目录（存在才返回），用于离线加载。"""
    explicit = os.environ.get("RAG_EMBED_MODEL_PATH")
    if explicit and os.path.isdir(explicit):
        return explicit
    name = (model_name or DEFAULT_MODEL).replace("/", "__")
    cand = os.path.join(MODELS_DIR, name)
    return cand if os.path.isdir(cand) else None


def get_model(model_name: str | None = None):
    """加载模型（进程内单例）。"""
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer  # 延迟导入（可选依赖）
        path = local_model_path(model_name) or (model_name or DEFAULT_MODEL)
        _MODEL = SentenceTransformer(path)
    return _MODEL


def model_id() -> str:
    """当前实际使用的模型标识（本地快照路径或模型名）。"""
    return local_model_path() or DEFAULT_MODEL


def embedding_dim() -> int:
    return int(get_model().get_sentence_embedding_dimension())


def encode(texts: Sequence[str], batch_size: int = 16, is_query: bool = False) -> list[list[float]]:
    """编码文本 → 归一化向量（list[list[float]]，便于 JSON 落盘）。"""
    model = get_model()
    payload = [((QUERY_PREFIX + t) if is_query else t) for t in texts]
    vecs = model.encode(payload, batch_size=batch_size, normalize_embeddings=True,
                        convert_to_numpy=True, show_progress_bar=False)
    return [[float(x) for x in v] for v in vecs]


def encode_query(skills: Iterable[str]) -> list[float]:
    """把技能列表编码成一条 query 向量。"""
    text = "、".join([s for s in skills if s])
    return encode([text], is_query=True)[0]


def embed_chunks(chunks: Sequence[dict]) -> list[list[float]]:
    return encode([c["text"] for c in chunks])


def fingerprint(texts: Sequence[str]) -> str:
    """输入指纹：用于证明「同一输入 → 同一向量」，可复现。"""
    h = hashlib.sha256()
    for t in texts:
        h.update(t.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


if __name__ == "__main__":
    from .chunker import build_chunks

    chunks = build_chunks()
    texts = [c["text"] for c in chunks]
    vecs = embed_chunks(chunks)
    assert len(vecs) == len(chunks), "编码数量与 chunk 数不一致"
    dim = len(vecs[0])
    assert all(len(v) == dim for v in vecs), "向量维度不一致"
    # 归一化校验：模长应为 1
    norm_err = max(abs(sum(x * x for x in v) ** 0.5 - 1.0) for v in vecs)
    print("model      : %s" % model_id())
    print("chunks     : %d  dim=%d" % (len(vecs), dim))
    print("归一化误差 : %.2e (应接近 0)" % norm_err)
    print("输入指纹   : %s" % fingerprint(texts))

    out = os.path.join(_BACKEND_DIR, "eval", "rag_embeddings.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "model": model_id(),
            "dim": dim,
            "fingerprint": fingerprint(texts),
            "chunk_ids": [c["chunk_id"] for c in chunks],
            "vectors": vecs,
        }, f, ensure_ascii=False)
    print("已落盘     : %s (%d 向量)" % (out, len(vecs)))
