# -*- coding: utf-8 -*-
"""事项 3 · 批次 2：列出 27 条非模板待复核用例的完整信息（供逐条判定）。"""
import asyncio
import json
import sys
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
    config.DEEPSEEK_API_KEY = ""

    cases = [json.loads(l) for l in (EVAL / "eval_set_v1.jsonl").open(encoding="utf-8") if l.strip()]
    batch2 = [c for c in cases if c["needs_human_review"] and not c["review_reason"].startswith("模板生成模式")]
    print(f"批次 2 共 {len(batch2)} 条\n")
    for c in batch2:
        agent._analyze_cache.clear()
        r = asyncio.run(agent.analyze_agent(c["jd"], c["resume"], tenant_id="t", session_id="s"))
        jp = r["jd_parse"]["skills"]
        mr = r["match_result"]
        agree = "一致" if c["gt"]["conclusion"] == r["recommendation"]["type"] else "★不一致"
        print(f"[{c['id']}] {agree}  期望={c['gt']['conclusion']} 实际={r['recommendation']['type']} 分数={mr['score']}")
        print(f"   标注: req={c['gt']['jd_required_skills']} pref={c['gt']['jd_preferred_skills']} resume_skills={c['gt']['resume_skills']}")
        print(f"   解析: req={jp['required']} pref={jp['preferred']}")
        print(f"   命中={mr['matched_skills']} 缺失={mr['missing_skills']}")
        print(f"   维度={mr['dimensions']}")
        print(f"   JD: {c['jd'][:95]}")
        print(f"   简历: {c['resume'][:95]}")
        print(f"   复核原因: {c['review_reason'][:80]}")
        print()


if __name__ == "__main__":
    main()
