# -*- coding: utf-8 -*-
"""R3/R4 的零依赖兜底实现（降级路径 + 测试替身）。

定位（重要）：
- **默认后端仍是 Chroma + 中文检索模型**（见 `store.py` / `embedder.py`，执行书 R3/R4 的选定方案）
- 本文件只在第三方依赖不可用时兜底：让 R3「能编码/能存/能复现」与 R4「能写入/能检索/带 metadata」
  这两条验收在无依赖环境下也能被测量，同时作为混合检索的测试替身
- 实现是纯 Python 的 **字符 n-gram + 词元 TF-IDF**（稀疏向量 + 余弦），
  与主链路的关键词口径一致、结果确定可复现；但**不是预训练中文语义模型**，语义泛化弱于 bge

激活方式：`get_searcher()` 会优先尝试 Chroma+bge，失败才回落到这里，并如实返回 name。
"""
from __future__ import annotations

import io
import json
import math
import os
import re
from collections import Counter
from typing import Iterable, Sequence

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
INDEX_PATH = os.environ.get("RAG_FALLBACK_INDEX",
                            os.path.join(_BACKEND_DIR, ".rag_db", "fallback_tfidf_index.json"))

_ASCII_RE = re.compile(r"[a-z0-9+#.]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fa5]+")
NGRAM = (2, 3)


def tokenize(text: str) -> list[str]:
    """词元：ASCII 词 + 中文 2/3-gram（中文无空格，靠 n-gram 提供区分度）。"""
    low = (text or "").lower()
    tokens = _ASCII_RE.findall(low)
    for run in _CJK_RE.findall(low):
        for n in NGRAM:
            tokens.extend(run[i:i + n] for i in range(max(0, len(run) - n + 1)))
    return tokens


class TfidfVectorizer:
    """纯 Python TF-IDF：`fit` 建词表，`transform` 出 L2 归一化的稀疏向量。"""

    def __init__(self):
        self.idf: dict[str, float] = {}
        self.dim = 0

    def fit(self, docs: Sequence[str]) -> "TfidfVectorizer":
        df: Counter = Counter()
        for d in docs:
            df.update(set(tokenize(d)))
        n = len(docs)
        self.idf = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}
        self.dim = len(self.idf)
        return self

    def transform(self, text: str) -> dict[str, float]:
        tf = Counter(tokenize(text))
        vec = {}
        for t, c in tf.items():
            if t in self.idf:
                vec[t] = (1.0 + math.log(c)) * self.idf[t]
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """稀疏向量余弦（两者都已归一化，等价于点积）。"""
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(t, 0.0) for t, v in a.items())


def _match_where(meta: dict, where: dict | None) -> bool:
    if not where:
        return True
    for k, cond in where.items():
        if isinstance(cond, dict):
            if "$in" in cond and meta.get(k) not in cond["$in"]:
                return False
            if "$eq" in cond and meta.get(k) != cond["$eq"]:
                return False
        elif meta.get(k) != cond:
            return False
    return True


class TfidfVectorStore:
    """内存向量库（可持久化 JSON），接口与 Chroma 版对齐。"""

    name = "fallback:tfidf-ngram"

    def __init__(self):
        self.vectorizer = TfidfVectorizer()
        self.items: list[dict] = []

    def index_chunks(self, chunks: Sequence[dict]) -> int:
        self.vectorizer.fit([c["text"] for c in chunks])
        self.items = [{
            "chunk_id": c["chunk_id"],
            "text": c["text"],
            "metadata": dict(c["metadata"]),
            "vector": self.vectorizer.transform(c["text"]),
        } for c in chunks]
        return len(self.items)

    def search(self, query: str | Iterable[str], top_k: int = 20,
               where: dict | None = None) -> list[dict]:
        q = query if isinstance(query, str) else "、".join(query)
        qv = self.vectorizer.transform(q)
        out = []
        for it in self.items:
            if not _match_where(it["metadata"], where):
                continue
            s = cosine(qv, it["vector"])
            out.append({"chunk": {"chunk_id": it["chunk_id"], "text": it["text"],
                                  "metadata": it["metadata"]},
                        "score": round(s, 6), "distance": round(1.0 - s, 6)})
        out.sort(key=lambda x: (-x["score"], x["chunk"]["chunk_id"]))
        return out[:top_k]

    def save(self, path: str | None = None) -> str:
        p = path or INDEX_PATH
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with io.open(p, "w", encoding="utf-8") as f:
            json.dump({"name": self.name, "idf": self.vectorizer.idf, "items": self.items},
                      f, ensure_ascii=False)
        return p

    @classmethod
    def load(cls, path: str | None = None) -> "TfidfVectorStore":
        p = path or INDEX_PATH
        with io.open(p, encoding="utf-8") as f:
            d = json.load(f)
        store = cls()
        store.vectorizer.idf = d["idf"]
        store.vectorizer.dim = len(d["idf"])
        store.items = d["items"]
        return store


_SEARCHER = None


def get_searcher(chunks: Sequence[dict] | None = None, prefer: str = "auto", force: bool = False):
    """返回可用检索后端（**进程内单例**，避免每次请求都重新编码与重建索引）。

    `prefer="chroma"` 时不回落。返回对象具备 `.name` 与 `.search(query_skills, top_k, where)`。
    优先 Chroma+bge（执行书选定方案）；依赖缺失时回落 TF-IDF 兜底并如实标注。
    """
    global _SEARCHER
    if _SEARCHER is not None and not force:
        return _SEARCHER
    from .chunker import build_chunks
    chunks = build_chunks() if chunks is None else chunks
    if prefer in ("auto", "chroma"):
        try:
            import chromadb  # noqa: F401
            from .embedder import embed_chunks
            from .store import get_collection, index_chunks as chroma_index
            already = get_collection().count()          # 已建好索引就不重复编码/写入
            if already != len(chunks):
                chroma_index(chunks, embed_chunks(chunks), reset=True)
            _SEARCHER = _ChromaSearcher()
            return _SEARCHER
        except Exception as e:
            if prefer == "chroma":
                raise
            reason = "%s: %s" % (type(e).__name__, str(e)[:60])
    else:
        reason = "prefer=%s" % prefer
    store = TfidfVectorStore()
    store.index_chunks(chunks)
    _SEARCHER = _FallbackSearcher(store, reason)
    return _SEARCHER


class _ChromaSearcher:
    name = "chroma+bge"

    def search(self, query_skills, top_k: int = 20, where: dict | None = None):
        from .store import vector_search
        return vector_search(query_skills, top_k=top_k, where=where)


class _FallbackSearcher:
    def __init__(self, store: TfidfVectorStore, reason: str = ""):
        self.store = store
        self.name = "%s（回落原因：%s）" % (store.name, reason) if reason else store.name

    def search(self, query_skills, top_k: int = 20, where: dict | None = None):
        return self.store.search(query_skills, top_k=top_k, where=where)


if __name__ == "__main__":
    from .chunker import build_chunks

    chunks = build_chunks()
    searcher = get_searcher(chunks)
    print("searcher  : %s" % searcher.name)
    print("维表大小  : %d" % searcher.store.vectorizer.dim)
    print("\n[1] 语义/词元检索：['Spring Boot','MySQL']")
    for r in searcher.search(["Spring Boot", "MySQL"], top_k=3):
        print("   %-12s score=%-8s %s" % (r["chunk"]["chunk_id"], r["score"], r["chunk"]["metadata"]["skill"]))
    print("\n[2] metadata 过滤：where={'skill':'Kubernetes'}")
    for r in searcher.search(["容器编排"], top_k=3, where={"skill": "Kubernetes"}):
        print("   %-12s %s" % (r["chunk"]["chunk_id"], r["chunk"]["metadata"]["skill"]))
    print("\n[3] 落盘 + 复现")
    p = searcher.store.save()
    again = TfidfVectorStore.load()
    print("   落盘: %s" % p)
    print("   重载后同一查询结果一致: %s" % (
        [x["chunk"]["chunk_id"] for x in again.search(["Spring Boot"], top_k=3)] ==
        [x["chunk"]["chunk_id"] for x in searcher.search(["Spring Boot"], top_k=3)]))
