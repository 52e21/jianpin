# -*- coding: utf-8 -*-
"""
RAG 子模块验收：R1 知识源 / R2 分块 / R5 混合检索（关键词 + RRF）

覆盖：
  A. R1/R2：20 条能力模型，字段完整，每条 1–3 块，块长 ≤ 500
  B. R5 关键词召回：技能名精确命中、别名命中（k8s→Kubernetes）、
     子串不误命中（Java 不得命中 JavaScript 块）
  C. R5 RRF 融合：数值等于 Σ 1/(k+rank)，且排序可复现
  D. 降级：空查询、向量侧抛异常时不得崩，并在 modes 里标注
  E. R3/R4（需第三方依赖）：编码维度/归一化、Chroma 写入与 metadata 过滤；
     依赖未安装时记为 SKIP（不计失败）

用法：python eval/test_rag_retrieval.py
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.rag.chunker import MAX_CHARS, build_chunks, load_models   # noqa: E402
from app.rag.retriever import DEFAULT_RRF_K, hybrid_retrieve, keyword_search, rrf_fuse  # noqa: E402
from app.rag.inject import (MAX_CHARS as CTX_MAX_CHARS, MAX_ITEMS as CTX_MAX_ITEMS,  # noqa: E402
                            capability_context_for_skills, format_capability_context)

CHUNKS = build_chunks()


def part_a():
    print("=== A. R1 知识源 + R2 分块 ===")
    models = load_models()
    ok = True
    ok &= len(models) == 20
    print("  知识条数: %d (要求 20) %s" % (len(models), "✔" if len(models) == 20 else "✘"))
    fields_ok = all(all(m.get(f) for f in ("id", "role", "skill", "capability", "source")) for m in models)
    print("  字段完整: %s" % ("✔" if fields_ok else "✘"))
    ok &= fields_ok
    per_model = {}
    for c in CHUNKS:
        per_model[c["metadata"]["id"]] = per_model.get(c["metadata"]["id"], 0) + 1
    counts = sorted(per_model.values())
    in_range = 1 <= counts[0] and counts[-1] <= 3
    print("  每条块数: min=%d max=%d (要求 1–3) %s" % (counts[0], counts[-1], "✔" if in_range else "✘"))
    ok &= in_range
    longest = max(len(c["text"]) for c in CHUNKS)
    print("  最长块: %d 字 (阈值 %d) %s" % (longest, MAX_CHARS, "✔" if longest <= MAX_CHARS else "✘"))
    ok &= longest <= MAX_CHARS
    print("  A 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_b():
    print("\n=== B. 关键词召回（精确 + 别名 + 不误命中）===")
    ok = True
    res = keyword_search(["Java", "Spring Boot", "MySQL", "Redis"], CHUNKS, top_k=5)
    got = [r["chunk"]["metadata"]["skill"] for r in res]
    exp = {"Java", "Spring Boot", "MySQL", "Redis"}
    hit_ok = exp.issubset(set(got))
    print("  四条技能召回: %s %s" % (got, "✔" if hit_ok else "✘"))
    ok &= hit_ok
    alias = keyword_search(["k8s"], CHUNKS, top_k=1)
    alias_ok = alias and alias[0]["chunk"]["metadata"]["skill"] == "Kubernetes"
    print("  别名 k8s → %s %s" % (alias[0]["chunk"]["metadata"]["skill"] if alias else "无",
                                  "✔" if alias_ok else "✘"))
    ok &= bool(alias_ok)
    java_hits = [r["chunk"]["metadata"]["skill"] for r in keyword_search(["Java"], CHUNKS, top_k=20)]
    no_js = "JavaScript" not in java_hits
    print("  Java 不得命中 JavaScript 块: %s %s" % (java_hits, "✔" if no_js else "✘"))
    ok &= no_js
    print("  B 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_c():
    print("\n=== C. RRF 融合（数值 + 可复现）===")
    a = [CHUNKS[0], CHUNKS[1]]
    b = [CHUNKS[1], CHUNKS[2]]
    fused = rrf_fuse([a, b], k=DEFAULT_RRF_K)
    expect = {
        CHUNKS[1]["chunk_id"]: 1 / (DEFAULT_RRF_K + 2) + 1 / (DEFAULT_RRF_K + 1),
        CHUNKS[0]["chunk_id"]: 1 / (DEFAULT_RRF_K + 1),
        CHUNKS[2]["chunk_id"]: 1 / (DEFAULT_RRF_K + 2),
    }
    ok = True
    for item in fused:
        cid = item["chunk"]["chunk_id"]
        same = abs(item["rrf"] - round(expect[cid], 6)) < 1e-9
        ok &= same
        print("  %-12s rrf=%-9s 期望=%-9s %s" % (cid, item["rrf"], round(expect[cid], 6), "✔" if same else "✘"))
    order1 = [x["chunk"]["chunk_id"] for x in keyword_search(["Java", "Redis"], CHUNKS, top_k=5)]
    order2 = [x["chunk"]["chunk_id"] for x in keyword_search(["Java", "Redis"], CHUNKS, top_k=5)]
    repro = order1 == order2
    print("  同输入两次排序一致: %s %s" % (repro, "✔" if repro else "✘"))
    ok &= repro
    print("  C 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_d():
    print("\n=== D. 降级（空输入 / 向量侧异常）===")
    ok = True
    empty = hybrid_retrieve([], CHUNKS)
    e_ok = empty["results"] == [] and empty["counts"] == {"keyword": 0, "vector": 0}
    print("  空查询: counts=%s %s" % (empty["counts"], "✔" if e_ok else "✘"))
    ok &= e_ok

    def boom(_q, _n):
        raise RuntimeError("vector down")

    deg = hybrid_retrieve(["Java"], CHUNKS, vector_search=boom, final_k=3)
    tagged = any(m.startswith("vector_unavailable") for m in deg["modes"])
    d_ok = tagged and len(deg["results"]) > 0
    print("  向量侧抛错: modes=%s results=%d %s" % (deg["modes"], len(deg["results"]), "✔" if d_ok else "✘"))
    ok &= d_ok
    print("  D 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_e():
    print("\n=== E. R3 向量化 + R4 向量库（需第三方依赖）===")
    try:
        import chromadb  # noqa: F401
        from sentence_transformers import SentenceTransformer  # noqa: F401
    except Exception as e:
        print("  SKIP：依赖未安装（%s）" % type(e).__name__)
        return True
    try:
        from app.rag.embedder import embed_chunks, model_id
        from app.rag.store import index_chunks, vector_search
    except Exception as e:
        print("  SKIP：模块导入失败（%s: %s）" % (type(e).__name__, e))
        return True
    ok = True
    try:
        vecs = embed_chunks(CHUNKS)
    except Exception as e:
        print("  SKIP：模型不可用（%s: %s）" % (type(e).__name__, str(e)[:80]))
        return True
    dim_ok = len({len(v) for v in vecs}) == 1 and len(vecs) == len(CHUNKS)
    norm_err = max(abs(sum(x * x for x in v) ** 0.5 - 1.0) for v in vecs)
    print("  编码: %d 向量, 维度=%d, 归一化误差=%.1e %s" % (
        len(vecs), len(vecs[0]), norm_err, "✔" if dim_ok and norm_err < 1e-6 else "✘"))
    ok &= dim_ok and norm_err < 1e-6
    db_dir = str(BACKEND / ".rag_db" / "test_run")
    n = index_chunks(CHUNKS, vecs, reset=True, db_dir=db_dir)
    print("  Chroma 写入: %d 条 %s" % (n, "✔" if n == len(CHUNKS) else "✘"))
    ok &= n == len(CHUNKS)
    hits = vector_search(["Spring Boot", "MySQL"], top_k=3, db_dir=db_dir)
    skills = [h["chunk"]["metadata"]["skill"] for h in hits]
    print("  语义检索 Top3: %s" % skills)
    filt = vector_search(["容器编排"], top_k=3, where={"skill": "Kubernetes"}, db_dir=db_dir)
    f_ok = len(filt) == 1 and filt[0]["chunk"]["metadata"]["skill"] == "Kubernetes"
    print("  metadata 过滤(where skill=Kubernetes): %d 条 %s" % (len(filt), "✔" if f_ok else "✘"))
    ok &= f_ok
    print("  E 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_f():
    print("\n=== F. R6 注入格式（纯函数，尚未接线）===")
    ok = True
    items = [
        {"chunk": {"chunk_id": "x1", "text": "Spring Boot：能独立搭建 REST 服务，理解 IoC 和 AOP",
                   "metadata": {"skill": "Spring Boot"}}},
        {"chunk": {"chunk_id": "x2", "text": "MySQL：能优化慢查询，理解索引原理",
                   "metadata": {"skill": "MySQL"}}},
    ]
    text = format_capability_context(items)
    expect = "岗位能力参考：\n- Spring Boot：能独立搭建 REST 服务，理解 IoC 和 AOP\n- MySQL：能优化慢查询，理解索引原理"
    fmt_ok = text == expect
    print("  格式与执行书一致: %s" % ("✔" if fmt_ok else "✘\n    实际=%r" % text))
    ok &= fmt_ok
    prefix_ok = text.count("Spring Boot") == 1
    print("  技能名前缀不重复: %s" % ("✔" if prefix_ok else "✘"))
    ok &= prefix_ok
    empty_ok = format_capability_context([]) == ""
    print("  空结果返回空串（可降级）: %s" % ("✔" if empty_ok else "✘"))
    ok &= empty_ok
    many = [{"chunk": {"chunk_id": "m%d" % i, "text": "S%d：描述%d" % (i, i),
                       "metadata": {"skill": "S%d" % i}}} for i in range(10)]
    capped = format_capability_context(many)
    items_in = capped.count("\n- ")          # 每条恰好贡献一个 "\n- "
    cap_ok = len(capped) <= CTX_MAX_CHARS + len("岗位能力参考：\n") and items_in <= CTX_MAX_ITEMS
    print("  条数上限: 条数=%d(≤%d) %s" % (items_in, CTX_MAX_ITEMS, "✔" if cap_ok else "✘"))
    ok &= cap_ok
    long_items = [{"chunk": {"chunk_id": "L%d" % i, "text": "技术%d：%s" % (i, "能独立设计高并发系统并做容量评估。" * 8),
                             "metadata": {"skill": "技术%d" % i}}} for i in range(10)]
    long_ctx = format_capability_context(long_items)
    char_ok = len(long_ctx) <= CTX_MAX_CHARS + len("岗位能力参考：\n")
    print("  字数上限: 字符=%d(≤%d+表头) 条数=%d %s" % (
        len(long_ctx), CTX_MAX_CHARS, long_ctx.count("\n- "), "✔" if char_ok else "✘"))
    ok &= char_ok
    no_half = all(ln.startswith("- ") for ln in capped.split("\n")[1:] if ln)
    print("  截断按整条（无半句）: %s" % ("✔" if no_half else "✘"))
    ok &= no_half
    none = capability_context_for_skills([])
    none_ok = none["text"] == "" and none["modes"] == ["empty_query"]
    print("  无技能输入: %s %s" % (none, "✔" if none_ok else "✘"))
    ok &= none_ok
    real = capability_context_for_skills(["Spring Boot", "MySQL"])
    real_ok = bool(real["text"].startswith("岗位能力参考：") and real["ids"])
    print("  真实知识源检索注入预览: ids=%s chars=%d %s" % (
        real["ids"], real["chars"], "✔" if real_ok else "✘"))
    ok &= real_ok
    print("  F 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":
    a, b, c, d, e, f = part_a(), part_b(), part_c(), part_d(), part_e(), part_f()
    allok = all([a, b, c, d, e, f])
    print("\n总结果:", "全部通过 ✅" if allok else "存在失败 ❌")
    sys.exit(0 if allok else 1)
