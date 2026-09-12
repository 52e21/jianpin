# -*- coding: utf-8 -*-
"""
第 6 步验收：结构化上下文注入 A/B 对比（精确到 API 返回的 prompt_tokens）

做法：
  - 同一进程内对每个用例跑两遍：ctx_mode="raw"（旧行为）与 ctx_mode="structured"（新行为）
  - 通过 spy 包装 generate_interview_questions，从 stats 里扣除出该节点自己的
    prompt_tokens / completion_tokens（stats 由两个 LLM 节点共享累加）
  - 相关性代理指标：题目文本对【必须技能】【缺失技能】的覆盖率（去重后的技能名命中数）

用法：
    python eval/measure_ctx.py
"""
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import app.agent as agent          # noqa: E402
import app.config as config        # noqa: E402
import app.database as database    # noqa: E402
import app.trace as trace          # noqa: E402
from app.tools import build_interview_context, extract_experiences   # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent

_spy = {}


def install_spy():
    """包装面试题节点，精确取该节点的 prompt/completion tokens。"""
    orig = agent.generate_interview_questions

    async def spy(*a, **kw):
        stats = a[2] if len(a) > 2 else kw.get("stats")
        p0 = (stats or {}).get("prompt_tokens", 0)
        c0 = (stats or {}).get("completion_tokens", 0)
        t0 = time.perf_counter()
        result = await orig(*a, **kw)
        if stats is not None:
            _spy["prompt_tokens"] = stats.get("prompt_tokens", 0) - p0
            _spy["completion_tokens"] = stats.get("completion_tokens", 0) - c0
        _spy["latency_ms"] = (time.perf_counter() - t0) * 1000
        ctx = kw.get("context")
        _spy["ctx_chars"] = len(ctx) if ctx else 0
        return result

    agent.generate_interview_questions = spy


def pick_cases():
    cases = [json.loads(l) for l in (EVAL_DIR / "eval_set_v1.jsonl").open(encoding="utf-8") if l.strip()]
    by_id = {c["id"]: c for c in cases}
    picks, seen = [], set()
    for c in (max(cases, key=lambda c: len(c["jd"])),
              max(cases, key=lambda c: len(c["resume"])),
              next((x for x in cases if x["source"] == "frontend_sample"), None),
              by_id.get("E001"), by_id.get("E004"), by_id.get("E021")):
        if c and c["id"] not in seen:
            seen.add(c["id"])
            picks.append(c)
    return picks


async def run_case(case, mode):
    _spy.clear()
    r = await agent.analyze_agent(case["jd"], case["resume"], ctx_mode=mode)
    qtext = json.dumps(r.get("interview_questions") or [], ensure_ascii=False).lower()
    req = (r.get("jd_parse", {}).get("skills", {}) or {}).get("required", []) or []
    miss = (r.get("match_result", {}) or {}).get("missing_skills", []) or []
    return {
        "score": r["match_result"]["score"],
        "conclusion": r["recommendation"]["type"],
        "prompt_tokens": _spy.get("prompt_tokens", 0),
        "completion_tokens": _spy.get("completion_tokens", 0),
        "total_call_tokens": _spy.get("prompt_tokens", 0) + _spy.get("completion_tokens", 0),
        "latency_ms": round(_spy.get("latency_ms", 0), 1),
        "ctx_chars": _spy.get("ctx_chars", 0),
        "n_questions": len(r.get("interview_questions") or []),
        "req_covered": sum(1 for s in req if s.lower() in qtext),
        "req_total": len(req),
        "miss_covered": sum(1 for s in miss if s.lower() in qtext),
        "miss_total": len(miss),
        "questions": [q.get("question", "") for q in (r.get("interview_questions") or [])],
    }


async def main():
    database.init_db()
    trace.set_enabled(False)
    database.save_history = lambda *a, **kw: None
    install_spy()

    picks = pick_cases()
    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cases": []}
    print(f"{'用例':<7}{'输入字数':>8} | {'raw prompt':>11}{'struct prompt':>14}{'降幅':>8} | "
          f"{'raw total':>10}{'struct total':>13} | {'相关性(必须/缺失)':>18}")
    print("-" * 108)

    for c in picks:
        agent._analyze_cache.clear()
        before = await run_case(c, "raw")
        agent._analyze_cache.clear()
        after = await run_case(c, "structured")
        drop = (1 - after["prompt_tokens"] / before["prompt_tokens"]) * 100 if before["prompt_tokens"] else 0
        rel_b = f"{before['req_covered']}/{before['req_total']}·{before['miss_covered']}/{before['miss_total']}"
        rel_a = f"{after['req_covered']}/{after['req_total']}·{after['miss_covered']}/{after['miss_total']}"
        print(f"{c['id']:<7}{len(c['jd']) + len(c['resume']):>8} | {before['prompt_tokens']:>11}"
              f"{after['prompt_tokens']:>14}{drop:>7.1f}% | {before['total_call_tokens']:>10}"
              f"{after['total_call_tokens']:>13} | {rel_b:>8} → {rel_a:<8}")
        out["cases"].append({"id": c["id"], "input_chars": len(c["jd"]) + len(c["resume"]),
                             "raw": before, "structured": after,
                             "prompt_token_drop_pct": round(drop, 1)})

    bp = [x["raw"]["prompt_tokens"] for x in out["cases"] if x["raw"]["prompt_tokens"]]
    ap = [x["structured"]["prompt_tokens"] for x in out["cases"] if x["structured"]["prompt_tokens"]]
    bt = [x["raw"]["total_call_tokens"] for x in out["cases"]]
    at = [x["structured"]["total_call_tokens"] for x in out["cases"]]
    long_cases = [x for x in out["cases"] if x["input_chars"] >= 200]
    ldrop = [(1 - x["structured"]["prompt_tokens"] / x["raw"]["prompt_tokens"]) * 100
             for x in long_cases if x["raw"]["prompt_tokens"]]
    out["summary"] = {
        "prompt_tokens_raw_mean": round(statistics.fmean(bp), 1),
        "prompt_tokens_structured_mean": round(statistics.fmean(ap), 1),
        "prompt_token_drop_pct_all": round((1 - statistics.fmean(ap) / statistics.fmean(bp)) * 100, 1),
        "prompt_token_drop_pct_long_inputs_only": round(statistics.fmean(ldrop), 1) if ldrop else 0,
        "total_call_tokens_raw_mean": round(statistics.fmean(bt), 1),
        "total_call_tokens_structured_mean": round(statistics.fmean(at), 1),
        "total_token_drop_pct": round((1 - statistics.fmean(at) / statistics.fmean(bt)) * 100, 1),
        "req_coverage_raw_total": sum(x["raw"]["req_covered"] for x in out["cases"]),
        "req_coverage_struct_total": sum(x["structured"]["req_covered"] for x in out["cases"]),
        "req_total": sum(x["raw"]["req_total"] for x in out["cases"]),
        "miss_coverage_raw_total": sum(x["raw"]["miss_covered"] for x in out["cases"]),
        "miss_coverage_struct_total": sum(x["structured"]["miss_covered"] for x in out["cases"]),
        "miss_total": sum(x["raw"]["miss_total"] for x in out["cases"]),
    }
    print("-" * 108)
    s = out["summary"]
    print(f"prompt_tokens  均值 : raw {s['prompt_tokens_raw_mean']} → structured {s['prompt_tokens_structured_mean']}"
          f"  降幅 {s['prompt_token_drop_pct_all']}%")
    print(f"（仅长输入 ≥200 字）prompt_tokens 降幅 : {s['prompt_token_drop_pct_long_inputs_only']}%")
    print(f"单次调用总 tokens 均值 : raw {s['total_call_tokens_raw_mean']} → structured {s['total_call_tokens_structured_mean']}"
          f"  降幅 {s['total_token_drop_pct']}%")
    print(f"相关性代理（必须技能覆盖）: raw {s['req_coverage_raw_total']}/{s['req_total']}"
          f" → structured {s['req_coverage_struct_total']}/{s['req_total']}")
    print(f"相关性代理（缺失技能覆盖）: raw {s['miss_coverage_raw_total']}/{s['miss_total']}"
          f" → structured {s['miss_coverage_struct_total']}/{s['miss_total']}")

    p = EVAL_DIR / "_ctx_ab.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已保存: {p}")


if __name__ == "__main__":
    if not config.DEEPSEEK_API_KEY:
        print("错误：未配置 DEEPSEEK_API_KEY")
        sys.exit(1)
    asyncio.run(main())
