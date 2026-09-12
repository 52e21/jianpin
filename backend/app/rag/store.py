# -*- coding: utf-8 -*-
"""R4：向量库 —— Chroma 持久化集合（带 metadata，可过滤）。

选型（执行书 R4）：Chroma（上手快、原生支持 metadata 过滤），先跑通再考虑换 PGVector。
- 持久化目录：`backend/.rag_db`（可用环境变量 `RAG_DB_DIR` 覆盖）
- 距离度量：cosine（与 R3 的归一化向量配套）
- 依赖 `chromadb` 为**可选依赖**，延迟导入：没装时不影响主链路
"""
from __future__ import annotations

import os
from typing import Iterable, Sequence

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
DB_DIR = os.environ.get("RAG_DB_DIR", os.path.join(_BACKEND_DIR, ".rag_db"))
COLLECTION = os.environ.get("RAG_COLLECTION", "capability_models")

_CLIENT = None


def get_client(db_dir: str | None = None):
    global _CLIENT
    if _CLIENT is None:
        import chromadb  # 延迟导入（可选依赖）
        path = db_dir or DB_DIR
        os.makedirs(path, exist_ok=True)
        try:  # 关掉匿名遥测：沙箱/内网环境不应发起外部上报
            _CLIENT = chromadb.PersistentClient(
                path=path, settings=chromadb.config.Settings(anonymized_telemetry=False))
        except Exception:
            _CLIENT = chromadb.PersistentClient(path=path)
    return _CLIENT


def get_collection(reset: bool = False, db_dir: str | None = None):
    client = get_client(db_dir)
    if reset:
        try:
            client.delete_collection(COLLECTION)
        except Exception:
            pass
    return client.get_or_create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine", "note": "简聘岗位能力模型知识源（R1-R5）"},
    )


def index_chunks(chunks: Sequence[dict], embeddings: Sequence[Sequence[float]],
                 reset: bool = True, db_dir: str | None = None) -> int:
    """写入向量库：ids/documents/metadatas/embeddings 一一对应。"""
    assert len(chunks) == len(embeddings), "chunk 数与向量数不一致"
    col = get_collection(reset=reset, db_dir=db_dir)
    col.add(
        ids=[c["chunk_id"] for c in chunks],
        documents=[c["text"] for c in chunks],
        metadatas=[dict(c["metadata"]) for c in chunks],
        embeddings=[[float(x) for x in v] for v in embeddings],
    )
    return col.count()


def search(embedding: Sequence[float], top_k: int = 20,
           where: dict | None = None, db_dir: str | None = None) -> list[dict]:
    """向量检索，支持 metadata 过滤（where={"skill": "Kubernetes"}）。"""
    col = get_collection(db_dir=db_dir)
    res = col.query(query_embeddings=[[float(x) for x in embedding]],
                    n_results=top_k, where=where or None,
                    include=["documents", "metadatas", "distances"])
    out: list[dict] = []
    ids = (res.get("ids") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    for i, cid in enumerate(ids):
        out.append({
            "chunk": {"chunk_id": cid, "text": docs[i], "metadata": metas[i]},
            "distance": float(dists[i]) if i < len(dists) else None,
        })
    return out


def vector_search(query_skills: Iterable[str], top_k: int = 20,
                  where: dict | None = None, db_dir: str | None = None) -> list[dict]:
    """R5 的向量侧注入点：技能列表 → 向量 → TopK（返回已排序 chunk 列表）。"""
    from .embedder import encode_query
    emb = encode_query(query_skills)
    return search(emb, top_k=top_k, where=where, db_dir=db_dir)


if __name__ == "__main__":
    from .chunker import build_chunks
    from .embedder import embed_chunks, model_id

    chunks = build_chunks()
    emb = embed_chunks(chunks)
    n = index_chunks(chunks, emb, reset=True)
    print("collection : %s @ %s" % (COLLECTION, DB_DIR))
    print("model      : %s" % model_id())
    print("写入条数   : %d" % n)
    print("metadata 键: %s" % sorted(chunks[0]["metadata"].keys()))

    print("\n[1] 语义检索示例：'服务端并发与连接池' (无技能名直接命中)")
    for r in vector_search(["服务端并发与连接池"], top_k=3):
        print("   %-12s d=%-8.4f %s" % (
            r["chunk"]["chunk_id"], r["distance"], r["chunk"]["metadata"]["skill"]))

    print("\n[2] metadata 过滤：where={'skill': 'Kubernetes'}")
    for r in vector_search(["容器编排"], top_k=3, where={"skill": "Kubernetes"}):
        print("   %-12s %s" % (r["chunk"]["chunk_id"], r["chunk"]["metadata"]["skill"]))

    print("\n[3] 技能列表检索：['Spring Boot','MySQL']")
    for r in vector_search(["Spring Boot", "MySQL"], top_k=3):
        print("   %-12s d=%-8.4f %s" % (
            r["chunk"]["chunk_id"], r["distance"], r["chunk"]["metadata"]["skill"]))
