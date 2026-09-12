# -*- coding: utf-8 -*-
"""
事项 3 配套：生成复核工作表 + 批次划分

产出：
  - eval/review_sheet_v1.csv   逐条复核工作表（含系统当前输出，供逐条判断）
  - 控制台打印：批次分布、每组样本

注意：本脚本只"生成待复核信息"，不做任何标注修改。
"""
import asyncio
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import app.agent as agent          # noqa: E402
import app.config as config        # noqa: E402
import app.database as database    # noqa: E402
import app.trace as trace          # noqa: E402

EVAL = Path(__file__).resolve().parent


def main():
    database.init_db()
    database.save_history = lambda *a, **k: None
    trace.set_enabled(False)
    config.DEEPSEEK_API_KEY = ""          # 关 LLM：复核关注的是规则链路判定

    cases = [json.loads(l) for l in (EVAL / "eval_set_v1.jsonl").open(encoding="utf-8") if l.strip()]
    review = [c for c in cases if c["needs_human_review"]]

    rows = []
    for c in review:
        agent._analyze_cache.clear()
        r = asyncio.run(agent.analyze_agent(c["jd"], c["resume"], tenant_id="t", session_id="s"))
        jp = r["jd_parse"]["skills"]
        mr = r["match_result"]
        rows.append({
            "id": c["id"],
            "source": c["source"],
            "review_reason": c["review_reason"],
            "gt_conclusion": c["gt"]["conclusion"],
            "pred_conclusion": r["recommendation"]["type"],
            "agree": c["gt"]["conclusion"] == r["recommendation"]["type"],
            "match_score": mr["score"],
            "gt_req": "/".join(c["gt"]["jd_required_skills"]),
            "pred_req": "/".join(jp["required"]),
            "pred_pref": "/".join(jp["preferred"]),
            "gt_resume_skills": "/".join(c["gt"]["resume_skills"]),
            "matched": "/".join(mr["matched_skills"]),
            "missing": "/".join(mr["missing_skills"]),
            "jd": c["jd"],
            "resume": c["resume"],
        })

    # 写工作表
    out = EVAL / "review_sheet_v1.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"待复核 {len(review)} 条 → 已写出 {out.name}")
    print()
    print("=== 批次划分（按 review_reason 分组）===")
    groups = defaultdict(list)
    for r in rows:
        groups[r["review_reason"] or "（无原因）"].append(r)
    for reason, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        dis = sum(1 for x in items if not x["agree"])
        print(f"  {len(items):>3} 条 | 与系统不一致 {dis:>3} 条 | {reason[:64]}")

    print()
    print("=== 不一致条目的分数分布（决定该不该改标注）===")
    bad = [r for r in rows if not r["agree"]]
    bands = Counter()
    for r in bad:
        s = r["match_score"]
        bands["0-49" if s < 50 else "50-79" if s <= 79 else "80-100"] += 1
    print(f"  不一致共 {len(bad)} 条: {dict(bands)}")

    print()
    print("=== 逐「组」看 3 条样本（便于批量判定口径）===")
    for reason, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f"\n--- {reason[:70]}  ({len(items)} 条) ---")
        for r in items[:3]:
            print(f"  {r['id']} 期望={r['gt_conclusion']} 实际={r['pred_conclusion']} 分数={r['match_score']}")
            print(f"     JD要求(标注)={r['gt_req'] or '无'} | 解析出={r['pred_req'] or '无'}")
            print(f"     JD: {r['jd'][:60]}")
            print(f"     简历: {r['resume'][:60]}")


if __name__ == "__main__":
    main()
