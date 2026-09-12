# -*- coding: utf-8 -*-
"""
R7：加 RAG 前后对比工具（每个 eval_runner 产物都能比）

用法：
  python eval/rag_compare.py <before.json> <after.json> [--out 对比表.md]

对比项（执行书 R7）：
  结论一致率 / 面试题相关性（另见 --questions）/ Token 增幅 / P95 延迟
输出：控制台表格 + （可选）markdown 表格，供 rag_report.md 直接引用
"""
import argparse
import io
import json
import sys
from pathlib import Path


def load(path):
    with io.open(path, encoding="utf-8") as f:
        d = json.load(f)
    return d.get("report", {}), {c["id"]: c for c in d.get("cases", [])}


def fmt(v, nd=4):
    if isinstance(v, float):
        return ("%." + str(nd) + "f") % v
    return str(v)


def compare(before_path, after_path, out_path="", limit=15):
    rb, cb = load(before_path)
    ra, ca = load(after_path)
    rows = []

    def add(name, key, nd=4, lower_better=False):
        b, a = rb.get(key), ra.get(key)
        if isinstance(b, dict) and "precision" in b:
            b = "P=%s R=%s" % (fmt(b.get("precision"), nd), fmt(b.get("recall"), nd))
            a = "P=%s R=%s" % (fmt((a or {}).get("precision"), nd), fmt((a or {}).get("recall"), nd))
        rows.append((name, fmt(b, nd), fmt(a, nd)))

    add("结论一致率", "conclusion_agreement")
    add("一致率分子/分母", "conclusion_agreement_n")
    add("必须技能 P/R", "skill_required_strict")
    add("全部技能 P/R", "skill_all_strict")
    add("错误数", "error_count")
    add("LLM 调用总数", "total_tokens")
    add("平均 tokens", "avg_tokens", nd=1)
    add("P50 延迟(ms)", "latency_ms_p50", nd=2)
    add("P95 延迟(ms)", "latency_ms_p95", nd=2)
    add("最大延迟(ms)", "latency_ms_max", nd=2)
    add("低分短路率", "short_circuit_rate")
    add("缓存命中数", "cache_hits")
    add("是否调 LLM", "with_llm")

    print("指标             | before            | after")
    print("-----------------|-------------------|------------------")
    for name, b, a in rows:
        print("%-16s | %-17s | %s" % (name, b, a))

    fixed = sorted([i for i in set(cb) & set(ca)
                    if cb[i].get("actual") != ca[i].get("actual") and ca[i].get("actual") == ca[i].get("expected")])
    broke = sorted([i for i in set(cb) & set(ca)
                    if cb[i].get("actual") == cb[i].get("expected") and ca[i].get("actual") != ca[i].get("expected")])
    changed = sorted([i for i in set(cb) & set(ca) if cb[i].get("actual") != ca[i].get("actual")])
    print("\n逐条变化: 共 %d 条" % len(changed))
    print("  变一致(fixed): %d %s" % (len(fixed), fixed[:limit]))
    print("  变不一致(broke): %d %s" % (len(broke), broke[:limit]))
    for i in changed[:limit]:
        print("   %s: %s→%s (期望 %s)" % (i, cb[i].get("actual"), ca[i].get("actual"), ca[i].get("expected")))

    if out_path:
        lines = ["| 指标 | 加 RAG 前 | 加 RAG 后 |", "|---|---|---|"]
        lines += ["| %s | %s | %s |" % r for r in rows]
        lines += ["", "逐条结论变化：%d 条；其中变一致 %d 条（%s），变不一致 %d 条（%s）" % (
            len(changed), len(fixed), ", ".join(fixed) or "无", len(broke), ", ".join(broke) or "无")]
        Path(out_path).write_text("\n".join(lines), encoding="utf-8")
        print("\n已写出对比表: %s" % out_path)
    return len(broke)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    n = compare(a.before, a.after, a.out)
    sys.exit(0 if n == 0 else 1)
