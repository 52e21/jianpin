# -*- coding: utf-8 -*-
"""列出 22 条待确认的改标（供用户逐条审视）；E051 单独列出。"""
import json
import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parent


def is_suggested(x):
    if "changed" in x:
        return bool(x["changed"])
    return bool(x.get("pending_human_confirmation"))


def main():
    cases = {json.loads(l)["id"]: json.loads(l)
             for l in (EVAL / "eval_set_v1.jsonl").open(encoding="utf-8") if l.strip()}
    adv = {}
    for p in ("review_advice_v1.jsonl", "review_advice_v2.jsonl"):
        if (EVAL / p).exists():
            for line in (EVAL / p).open(encoding="utf-8"):
                if line.strip():
                    a = json.loads(line)
                    adv[a["id"]] = a

    ids = sorted(i for i, x in adv.items() if is_suggested(x))
    templates = [i for i in ids if i != "E051"]
    print(f"待确认改标共 {len(ids)} 条：模板生成 {len(templates)} 条 + E051 1 条\n")
    print("=" * 118)
    print(f"{'ID':<6}{'原标':<6}{'建议':<6}{'分数':>5}  {'JD（截断）':<46}简历（截断）")
    print("-" * 118)
    for i in templates:
        c, a = cases[i], adv[i]
        print(f"{i:<6}{c['gt']['conclusion']:<6}{a['suggested_gt']:<6}{a['match_score']:>5}  "
              f"{c['jd'][:44]:<46}{c['resume'][:34]}")

    print("=" * 118)
    print("\n【E051 单独看】")
    c, a = cases["E051"], adv["E051"]
    print(f"  ID={c['id']}  类别={a.get('category')}")
    print(f"  JD      = {c['jd']!r}    ← 空字符串")
    print(f"  简历    = {c['resume']!r}")
    print(f"  原标    = {c['gt']['conclusion']}（复核原因：{c['review_reason']}）")
    print(f"  建议标  = {a['suggested_gt']}")
    print(f"  依据    = {a['reason']}")
    print(f"  代码输出= {a['code_output']}  分数={a['match_score']}")
    print("\n  说明：空 JD 在**接口层**已由 /api/agent/analyze 返回 400（main.py 校验）。")
    print("        本用例是评测脚本**直接调编排函数**（绕过接口校验），因此内部给出『待定』。")
    print("        原标『不推荐』无依据 —— 管线并未判定为不推荐，只是没有可评分维度。")


if __name__ == "__main__":
    sys.exit(main())
