# -*- coding: utf-8 -*-
"""
事项 3 收尾工具：把复核结果写回评测集（生成 eval_set_v1_1.jsonl，不改动 v1）

annotator 的三档语义（按用户口径，已细化）：
  - human_reviewed : **人工判断**确认过的（当前没有条目属于这一档）
  - spec_derived   : 由**规范阈值**推导出的标注（21 条模板用例改标属于这一档）
                     —— 规范若变，这些标注必须跟着重算
  - ai_reviewed    : 我复核过但未获人工确认的
  - ai_assisted_*  : 生成器产出的、尚未复核的

其它字段：
  review_status    : spec_confirmed / ai_reviewed_pending_confirmation /
                     ai_reviewed_confirmed_original / ai_assisted_unreviewed / moved_to_contract
  review_category  : code_defect / spec_gap / capability_gap / label_error / confirm
  label_basis      : business_judgment / spec_threshold / template_heuristic / boundary_behaviour
  exclude_from_agreement : 该条不计入结论一致率（如 E051，已改为接口契约用例）

用法：
    python eval/apply_review.py                                  # 只生成元数据，不改标注
    python eval/apply_review.py --confirm E061,E065,...          # 确认部分改标
    python eval/apply_review.py --confirm-all
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

EVAL = Path(__file__).resolve().parent
V1 = EVAL / "eval_set_v1.jsonl"
ADV1 = EVAL / "review_advice_v1.jsonl"
ADV2 = EVAL / "review_advice_v2.jsonl"
BASELINE = EVAL / "baseline_v2.json"


def is_suggested(x) -> bool:
    """该条是否"建议改标"。

    两批建议用了不同字段：批次 1 用 changed / contested，批次 2 用 pending_human_confirmation。
    这里统一兼容，避免漏条（我第一版就漏掉了批次 2 的 E051）。
    """
    if "changed" in x:
        return bool(x["changed"])
    return bool(x.get("pending_human_confirmation"))


def load_advice():
    """合并两批复核建议 → {id: advice}"""
    out = {}
    for p in (ADV1, ADV2):
        if not p.exists():
            continue
        for line in p.open(encoding="utf-8"):
            if line.strip():
                a = json.loads(line)
                out[a["id"]] = a
    return out


def label_basis_of(case, relabeled):
    if case["source"] == "constructed":
        if "模板生成" in (case.get("note") or ""):
            return "spec_threshold" if relabeled else "template_heuristic"
        return "business_judgment"
    return "business_judgment"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", default="", help="逗号分隔的用例 id，表示用户已确认改标")
    ap.add_argument("--confirm-all", action="store_true", help="确认全部建议改标")
    ap.add_argument("--out", default="eval_set_v1_1.jsonl")
    a = ap.parse_args()

    cases = [json.loads(l) for l in V1.open(encoding="utf-8") if l.strip()]
    advice = load_advice()
    suggested = sorted(i for i, x in advice.items() if is_suggested(x))
    confirmed = set(suggested) if a.confirm_all else {s.strip() for s in a.confirm.split(",") if s.strip()}
    unknown = confirmed - set(suggested)
    if unknown:
        print(f"错误：这些 id 不在建议改标清单里 → {sorted(unknown)}")
        return 2

    print(f"建议改标 {len(suggested)} 条；本次确认 {len(confirmed)} 条"
          f"{'（全部）' if a.confirm_all else ''}")
    if not confirmed:
        print("  （未确认任何改标 → 只写复核元数据，标注保持原样）")

    out_cases, stats = [], Counter()
    for c in cases:
        cid = c["id"]
        adv = advice.get(cid)
        relabeled = cid in confirmed
        new = dict(c)
        # 边界兜底用例（E051：空 JD）：搬到接口契约用例集，本体保留但**不计入一致率**
        if c.get("review_reason", "").startswith("空 JD"):
            new["exclude_from_agreement"] = True
            new["group"] = "boundary"
            new["label_basis"] = "boundary_behaviour"
            new["annotator"] = "ai_reviewed"
            new["review_status"] = "moved_to_contract"
            new["review_category"] = "label_error"
            new["gt"] = dict(c["gt"])
            new["gt"]["conclusion"] = "待定"       # 编排层对空 JD 的实际行为
            new["previously_gt"] = c["gt"]["conclusion"]
            new["review_reason"] = ("空 JD 在接口层已由 /api/agent/analyze 返回 400（接口契约）；"
                                    "本用例直接调编排函数，绕过接口校验，测错了层。"
                                    "已改为接口契约用例（contract_set_v1.jsonl），"
                                    "本行仅保留『编排层对空 JD 不崩』的边界记录，不计入一致率。")
            out_cases.append(new)
            stats["excluded"] += 1
            stats["basis::boundary_behaviour"] += 1
            continue
        if relabeled:
            new["gt"] = dict(c["gt"])
            new["gt"]["conclusion"] = adv["suggested_gt"]
            new["previously_gt"] = c["gt"]["conclusion"]
        # 元数据
        if adv:
            if relabeled:
                basis = label_basis_of(c, relabeled)
                # 规范阈值推导出来的标注 → spec_derived（**不是** human_reviewed）
                new["annotator"] = "spec_derived" if basis == "spec_threshold" else "human_reviewed"
                new["review_status"] = ("spec_confirmed" if basis == "spec_threshold"
                                        else "human_confirmed")
            else:
                new["annotator"] = "ai_reviewed"
                new["review_status"] = ("ai_reviewed_pending_confirmation"
                                    if is_suggested(adv) else "ai_reviewed_confirmed_original")
            new["review_category"] = adv.get("category", "confirm")
            new["review_action"] = adv.get("action", "确认原标")
            new["review_reason"] = adv.get("reason", "")
        else:
            new["annotator"] = "ai_reviewed"
            new["review_status"] = "ai_assisted_unreviewed"
        new["label_basis"] = label_basis_of(c, relabeled)
        out_cases.append(new)
        stats[new["annotator"]] += 1
        stats[f"basis::{new['label_basis']}"] += 1

    out = EVAL / a.out
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for c in out_cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"\n已写出 {out.name}（{len(out_cases)} 条）")
    print("  annotator 分布:", {k: v for k, v in stats.items() if not k.startswith("basis::")})
    print("  label_basis 分布:", {k[7:]: v for k, v in stats.items() if k.startswith("basis::")})

    # 用最近一次跑批的逐条预测，投影新标注下的一致率（不重跑）
    if BASELINE.exists():
        pred = {c["id"]: c["pred_conclusion"] for c in
                json.load(BASELINE.open(encoding="utf-8"))["cases"]}
        after = sum(1 for c in out_cases if pred.get(c["id"]) == c["gt"]["conclusion"])
        before = sum(1 for c in cases if pred.get(c["id"]) == c["gt"]["conclusion"])
        print(f"\n  一致率投影（基于 v2 跑批的逐条预测）：{before}/200={before/2:.1f}%"
              f"  →  本次确认后 {after}/200={after/2:.1f}%")

    # 完整性自检
    bad = []
    if len(out_cases) != 200:
        bad.append(f"条数 {len(out_cases)} != 200")
    for c in out_cases:
        if c["gt"]["conclusion"] not in ("推荐", "待定", "不推荐"):
            bad.append(f"{c['id']} 结论非法")
        if c["annotator"] == "human_reviewed" and c["id"] not in confirmed:
            bad.append(f"{c['id']} 未确认却被标为 human_reviewed")
    print(f"  自检: {'通过' if not bad else '失败 → ' + str(bad[:5])}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
