# -*- coding: utf-8 -*-
"""R5：混合检索链路（向量 TopN + 关键词 TopN → RRF 融合 → TopK）。

设计要点（执行书 R5）：
- 向量管语义、关键词管精确；融合用 **RRF（倒数排名融合）**，不用加权求和
- 向量侧以「可注入的 callable」接入（R4 的向量库负责实现），本模块**不依赖任何第三方包**
- 关键词侧复用主链路的技能归一化与词边界判定（`app.tools._norm_skill` / `_token_hits`），
  保证与打分口径一致（"Java" 不会命中 "JavaScript"）
- 两级都为空时返回空列表：R6 注入必须容忍空结果
"""
from __future__ import annotations

import re
from typing import Callable, Iterable, Sequence

DEFAULT_TOP_N = 20
DEFAULT_FINAL_K = 5
DEFAULT_RRF_K = 60

# 关键词得分权重：metadata 精确命中 > 正文命中
W_SKILL_META = 3.0
W_SKILL_TEXT = 1.0

_TOOLS = None


def _tools():
    """延迟导入 app.tools，避免将来 R6 之后 tools <-> rag 的循环导入。"""
    global _TOOLS
    if _TOOLS is None:
        try:
            from .. import tools as _t
        except Exception:  # 独立运行（如评测脚本）时的兜底
            _t = None
        _TOOLS = _t
    return _TOOLS


def norm_skill(s: str) -> str:
    """写法归一（与主链路同口径）。"""
    t = _tools()
    if t is not None:
        return t._norm_skill(s)
    return re.sub(r"[\s.\-_/]", "", (s or "").lower())


def canonical_skill(s: str) -> str:
    """别名 → 规范名（如 k8s → Kubernetes）。"""
    t = _tools()
    key = (s or "").strip().lower()
    if t is not None:
        return t.SKILL_ALIASES.get(key, s)
    return s


def _token_hits(text: str, token: str) -> bool:
    """词边界感知的包含判定（与主链路同口径）。"""
    t = _tools()
    if t is not None:
        return t._token_hits(text.lower(), token)
    return token.lower() in text.lower()


def query_tokens(skill: str) -> list[str]:
    """把一个技能名展开成用于关键词匹配的写法集合（规范名 + 全部别名）。"""
    canon = canonical_skill(skill)
    forms = {canon, skill}
    t = _tools()
    if t is not None:
        forms.update(t.SKILL_ALIAS_REVERSE.get(canon, []))
    return [f for f in forms if f]


def keyword_search(query_skills: Sequence[str], chunks: Sequence[dict],
                   top_k: int = DEFAULT_TOP_N) -> list[dict]:
    """关键词召回：技能名与 chunk 的 metadata/正文做精确匹配。"""
    scored: list[dict] = []
    for ch in chunks:
        score = 0.0
        why: list[str] = []
        ch_skill_norm = norm_skill(ch["metadata"].get("skill", ""))
        ch_skill_canon = canonical_skill(ch["metadata"].get("skill", ""))
        for q in query_skills:
            if not q:
                continue
            q_canon = canonical_skill(q)
            hit = False
            # 1) metadata 精确命中（同技能的不同写法也算）
            if q_canon == ch_skill_canon or norm_skill(q) == ch_skill_norm:
                score += W_SKILL_META
                why.append("meta:" + q_canon)
                hit = True
            # 2) 正文命中（词边界感知）
            if not hit and any(_token_hits(ch["text"], tk) for tk in query_tokens(q)):
                score += W_SKILL_TEXT
                why.append("text:" + q_canon)
        if score > 0:
            scored.append({"chunk": ch, "score": round(score, 4), "why": why})
    # 稳定排序：分数降序，其次 chunk_id 升序（保证可复现）
    scored.sort(key=lambda x: (-x["score"], x["chunk"]["chunk_id"]))
    return scored[:top_k]


def rrf_fuse(rankings: Iterable[Sequence[dict]], k: int = DEFAULT_RRF_K,
             limit: int | None = None) -> list[dict]:
    """RRF 融合：score(d) = Σ_r 1/(k + rank_r(d))，rank 从 1 开始。

    rankings 为若干「已排序的 chunk 列表」（元素可带 chunk 键，也可直接是 chunk）。
    """
    agg: dict[str, dict] = {}
    for ri, ranking in enumerate(rankings):
        for rank, item in enumerate(ranking, start=1):
            ch = item.get("chunk", item) if isinstance(item, dict) else item
            cid = ch["chunk_id"]
            slot = agg.setdefault(cid, {"chunk": ch, "rrf": 0.0, "ranks": {}})
            slot["rrf"] += 1.0 / (k + rank)
            slot["ranks"]["r%d" % ri] = rank
    out = sorted(agg.values(), key=lambda x: (-x["rrf"], x["chunk"]["chunk_id"]))
    for item in out:
        item["rrf"] = round(item["rrf"], 6)
    return out[:limit] if limit else out


def hybrid_retrieve(query_skills: Sequence[str], chunks: Sequence[dict],
                    vector_search: Callable[[Sequence[str], int], Sequence[dict]] | None = None,
                    top_n: int = DEFAULT_TOP_N, final_k: int = DEFAULT_FINAL_K,
                    rrf_k: int = DEFAULT_RRF_K) -> dict:
    """混合检索：向量召回 TopN + 关键词召回 TopN → RRF → TopK。

    vector_search 为 None 或抛错时自动降级为「关键词 only」，并在 modes 里标注。
    """
    kw = keyword_search(query_skills, chunks, top_k=top_n)
    vec: list[dict] = []
    modes = ["keyword"]
    if vector_search is not None:
        try:
            vec = list(vector_search(query_skills, top_n))
            modes.insert(0, "vector")
        except Exception as e:  # 向量侧不可用不阻塞主流程
            modes.append("vector_unavailable:%s" % type(e).__name__)
    if not kw and not vec:
        return {"results": [], "modes": modes, "counts": {"keyword": 0, "vector": 0}}
    fused = rrf_fuse([r for r in (vec, kw) if r], k=rrf_k, limit=final_k)
    return {
        "results": fused,
        "modes": modes,
        "counts": {"keyword": len(kw), "vector": len(vec)},
    }


if __name__ == "__main__":
    from .chunker import build_chunks

    chunks = build_chunks()
    print("chunks: %d" % len(chunks))

    print("\n[1] 关键词召回 query=['Java','Spring Boot','MySQL','Redis']")
    for r in keyword_search(["Java", "Spring Boot", "MySQL", "Redis"], chunks, top_k=5):
        print("   %-12s %-12s score=%-5s %s" % (
            r["chunk"]["chunk_id"], r["chunk"]["metadata"]["skill"], r["score"], r["why"]))

    print("\n[2] 别名召回 query=['k8s']（应命中 Kubernetes）")
    for r in keyword_search(["k8s"], chunks, top_k=3):
        print("   %-12s %-12s score=%-5s %s" % (
            r["chunk"]["chunk_id"], r["chunk"]["metadata"]["skill"], r["score"], r["why"]))

    print("\n[3] RRF 数值核对（两路排序）")
    a = [chunks[0], chunks[1]]
    b = [chunks[1], chunks[2]]
    fused = rrf_fuse([a, b], k=60)
    expect = {
        chunks[1]["chunk_id"]: 1 / 62 + 1 / 61,
        chunks[0]["chunk_id"]: 1 / 61,
        chunks[2]["chunk_id"]: 1 / 62,
    }
    for item in fused:
        cid = item["chunk"]["chunk_id"]
        ok = abs(item["rrf"] - round(expect[cid], 6)) < 1e-9
        print("   %-12s rrf=%-9s expect=%-9s %s" % (
            cid, item["rrf"], round(expect[cid], 6), "OK" if ok else "MISMATCH"))

    print("\n[4] 空查询与向量侧缺失（应降级不报错）")
    print("   hybrid([]) ->", hybrid_retrieve([], chunks)["counts"])
    stub = lambda q, n: list(reversed(chunks))[:n]  # 模拟向量召回
    out = hybrid_retrieve(["Java"], chunks, vector_search=stub, final_k=3)
    print("   modes=%s counts=%s" % (out["modes"], out["counts"]))
    print("   top3=%s" % [x["chunk"]["chunk_id"] for x in out["results"]])
