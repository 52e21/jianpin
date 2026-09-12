# -*- coding: utf-8 -*-
"""
事项 4 配套：两份跑批结果对比（v1 基线 → v2 基线）

用法：
    python eval/compare_baselines.py                      # 默认 baseline.json → baseline_v2.json
    python eval/compare_baselines.py --old x.json --new y.json
"""
import argparse
import json
import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parent


def load(p):
    d = json.load((EVAL / p).open(encoding="utf-8"))
    return d["report"], {c["id"]: c["pred_conclusion"] for c in d["cases"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default="baseline.json")
    ap.add_argument("--new", default="baseline_v2.json")
    a = ap.parse_args()

    ro, po = load(a.old)
    rn, pn = load(a.new)

    print("=" * 78)
    print(f"基线对比：{a.old}  →  {a.new}")
    print("=" * 78)
    keys = [
        ("conclusion_agreement", "结论一致率（全部 200 条）"),
        ("conclusion_agreement_n", ""),
        ("avg_tokens", "平均 token"),
        ("latency_ms_p50", "P50 延迟"),
        ("latency_ms_p95", "P95 延迟"),
        ("short_circuit_rate", "低分短路率"),
        ("elapsed_seconds", "跑批耗时(s)"),
        ("error_count", "异常数"),
    ]
    for k, label in keys:
        if k == "conclusion_agreement_n":
            print(f"  {'':34} {ro.get(k)}  →  {rn.get(k)}")
            continue
        vo, vn = ro.get(k), rn.get(k)
        mark = "  =  " if vo == vn else "  →  "
        print(f"  {label or k:<34} {vo} {mark} {vn}")

    for name, key in (("必须技能 P/R", "skill_required_strict"), ("全部技能 P/R", "skill_all_strict")):
        so, sn = ro.get(key, {}), rn.get(key, {})
        print(f"  {name:<34} P={so.get('precision')}/R={so.get('recall')}  →  "
              f"P={sn.get('precision')}/R={sn.get('recall')}")

    print("\n" + "-" * 78)
    print("【分组指标】（两类口径必须分开看）")
    for g, info in rn.get("by_group", {}).items():
        sk = info["skill_required_strict"]
        print(f"  {info['label']}")
        print(f"    样本 {info['n']} 条 | 一致率 {info['agreement']} ({info['agreement_n']})"
              f" | 必须技能 P={sk['precision']} R={sk['recall']} | P95={info['latency_ms_p95']}ms")

    fixed = [i for i in pn if po.get(i) != pn.get(i) and i in po]
    print("\n" + "-" * 78)
    print(f"【结论发生变化的用例】{len(fixed)} 条（只列有标注的前 200 条内）")
    from collections import Counter
    print("  变化方向统计:", dict(Counter(f"{po[i]}→{pn[i]}" for i in fixed)))

    # 用评测集原始标注核对这些变化是好是坏
    cases = {c["id"]: c for c in
             (json.loads(l) for l in (EVAL / "eval_set_v1.jsonl").open(encoding="utf-8") if l.strip())}
    better = [i for i in fixed if cases[i]["gt"]["conclusion"] == pn[i]]
    worse = [i for i in fixed if cases[i]["gt"]["conclusion"] == po[i]]
    neutral = [i for i in fixed if i not in better and i not in worse]
    print(f"  变好的 {len(better)} 条: {better}")
    print(f"  变差的 {len(worse)} 条: {worse}")
    if neutral:
        print(f"  仍不一致但结论变了 {len(neutral)} 条: {neutral}")
        for i in neutral:
            print(f"    {i}: {po[i]} → {pn[i]}（期望 {cases[i]['gt']['conclusion']}）")


if __name__ == "__main__":
    sys.exit(main())
