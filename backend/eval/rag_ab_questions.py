# -*- coding: utf-8 -*-
"""
R7：加 RAG 前后对比（面试题相关性 / token 增幅 / 延迟）

做法：
- 从评测集挑 N 条会真正生成面试题的用例（gt.conclusion ∈ 推荐/待定）
- 同一批用例跑两组：RAG_ENABLED=0（前）与 RAG_ENABLED=1（后）
  · 两组用不同的 session_id，避免命中 10 分钟结果缓存（缓存键含 session_id）
- 指标：
  · jd_skill_cover：题目提到的 JD 必须技能比例（关键词口径，确定性）
  · cap_cover    ：题目提到"检索到的岗位能力点"的比例（RAG 是否被用上）
  · diversity    ：各题两两 Jaccard 相似度均值（越低越不重复）
  · avg_tokens / p50 / p95 延迟
  · --judge：额外用 LLM 盲评（0-10 分，针对性与可考察性），两组都不告诉评委来源
- 不写库、不写 Trace（纪律）；结果落 eval/rag_ab_result.json + eval/rag_ab_table.md

用法：python eval/rag_ab_questions.py [--limit 10] [--judge]
"""
import argparse
import asyncio
import io
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import app.database as database          # noqa: E402
import app.trace as trace                # noqa: E402

database.save_history = lambda *a, **k: None      # 纪律：不写历史
trace.record = lambda *a, **k: None               # 纪律：不写 Trace

from app.agent import analyze_agent, _jd_skills    # noqa: E402
from app.rag.chunker import build_chunks           # noqa: E402
from app.rag.inject import capability_context_for_skills   # noqa: E402
from app.tools import _token_hits, parse_jd        # noqa: E402

EVAL = Path(__file__).resolve().parent
CHUNKS = build_chunks()
SKILL_OF_CHUNK = {c["chunk_id"]: c["metadata"]["skill"] for c in CHUNKS}


def pick_cases(limit: int) -> list[dict]:
    out = []
    with io.open(EVAL / "eval_set_v1_1.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if (d.get("gt") or {}).get("conclusion") in ("推荐", "待定"):
                out.append({"id": d["id"], "jd": d["jd"], "resume": d["resume"],
                            "expect": (d.get("gt") or {}).get("conclusion")})
    return out[:limit]


def _mentioned(questions: list, skills: list) -> int:
    """questions 里提到多少个 skills（词边界口径，按题目文本匹配）。

    注意：`_token_hits` 要求传**小写文本**（内部按归一化下标做词边界判定），漏了会全部判不中。
    """
    text = " ".join([q.get("question", "") for q in questions if isinstance(q, dict)]).lower()
    return sum(1 for s in skills if s and _token_hits(text, s))


def _diversity(questions: list) -> float:
    def toks(q):
        return set(re.findall(r"[a-z0-9+#.]+|[\u4e00-\u9fa5]{2}", q.get("question", "").lower()))
    sets = [toks(q) for q in questions if isinstance(q, dict)]
    if len(sets) < 2:
        return 1.0
    sims = []
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            a, b = sets[i], sets[j]
            u = a | b
            sims.append(len(a & b) / len(u) if u else 0.0)
    return round(1.0 - (sum(sims) / len(sims)), 4)


async def run_config(enabled: bool, cases: list[dict], cap_skills: dict) -> list[dict]:
    os.environ["RAG_ENABLED"] = "1" if enabled else "0"
    rows = []
    for c in cases:
        t0 = time.perf_counter()
        res = await analyze_agent(c["jd"], c["resume"], tenant_id="ab",
                                 session_id="ab-%s" % ("on" if enabled else "off"), role="hr")
        ms = (time.perf_counter() - t0) * 1000
        qs = res.get("interview_questions") or []
        jd_req = (res.get("jd_parse") or {}).get("skills", {}).get("required", []) or []
        caps = cap_skills.get(c["id"], [])
        rows.append({
            "id": c["id"], "expect": c["expect"], "ms": round(ms, 1),
            "tokens": res.get("total_tokens", 0), "llm_calls": res.get("llm_calls", 0),
            "cache_hit": res.get("cache_hit", False),
            "n_questions": len(qs),
            "jd_skill_cover": "%d/%d" % (_mentioned(qs, jd_req), len(jd_req)),
            "jd_skill_cover_rate": round(_mentioned(qs, jd_req) / len(jd_req), 4) if jd_req else 1.0,
            "cap_cover": "%d/%d" % (_mentioned(qs, caps), len(caps)),
            "cap_cover_rate": round(_mentioned(qs, caps) / len(caps), 4) if caps else 1.0,
            "diversity": _diversity(qs),
            "questions": [q.get("question", "") for q in qs if isinstance(q, dict)],
        })
    return rows


async def judge_one(jd: str, resume: str, questions: list) -> dict:
    """LLM 盲评：只给 JD + 简历 + 一组题目，不告知是否加了 RAG。"""
    from openai import AsyncOpenAI
    from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

    client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL, timeout=60.0)
    qs = "\n".join("%d. %s" % (i + 1, q) for i, q in enumerate(questions))
    prompt = ("你是资深技术面试官，负责评审面试题质量。请根据岗位 JD 与候选人简历，"
              "评价下面这组面试题的**针对性与可考察性**（是否问到关键能力、是否有区分度、"
              "是否结合了候选人经历）。\n\n【岗位JD】\n%s\n\n【候选人简历】\n%s\n\n"
              "【待评面试题】\n%s\n\n"
              '只输出 JSON：{"score": 0-10 的整数, "reason": "一句话理由"}' % (jd, resume, qs))
    resp = await client.chat.completions.create(
        model=DEEPSEEK_MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.2)
    content = (resp.choices[0].message.content or "").strip()
    m = re.search(r"\{.*\}", content, re.S)
    try:
        d = json.loads(m.group()) if m else {}
    except Exception:
        d = {}
    return {"score": d.get("score"), "reason": str(d.get("reason", ""))[:80],
            "tokens": getattr(getattr(resp, "usage", None), "total_tokens", 0) or 0}


def agg(rows: list[dict]) -> dict:
    rates = [r["jd_skill_cover_rate"] for r in rows]
    caps = [r["cap_cover_rate"] for r in rows]
    ms = sorted(r["ms"] for r in rows)
    return {
        "cases": len(rows),
        "avg_jd_skill_cover": round(statistics.mean(rates), 4) if rates else 0,
        "avg_cap_cover": round(statistics.mean(caps), 4) if caps else 0,
        "avg_diversity": round(statistics.mean([r["diversity"] for r in rows]), 4),
        "avg_tokens": round(statistics.mean([r["tokens"] for r in rows]), 1),
        "total_tokens": sum(r["tokens"] for r in rows),
        "p50_ms": ms[len(ms) // 2] if ms else 0,
        "p95_ms": ms[min(len(ms) - 1, int(len(ms) * 0.95))] if ms else 0,
        "llm_calls": sum(r["llm_calls"] for r in rows),
        "cache_hits": sum(1 for r in rows if r["cache_hit"]),
    }


async def main_async(args):
    cases = pick_cases(args.limit)
    print("用例 %d 条: %s" % (len(cases), [c["id"] for c in cases]))

    # 先取一次"可用能力点"（两组共用，保证 cap_cover 口径一致），同时完成模型预热
    t0 = time.perf_counter()
    cap_skills = {}
    for c in cases:
        ctx = capability_context_for_skills(_jd_skills(parse_jd(c["jd"])))
        cap_skills[c["id"]] = [SKILL_OF_CHUNK.get(i, "") for i in ctx["ids"]]
    print("检索预计算 + 预热: %.0f ms" % ((time.perf_counter() - t0) * 1000))

    print("\n[1/2] 跑 RAG_ENABLED=0（前）...")
    off = await run_config(False, cases, cap_skills)
    print("[2/2] 跑 RAG_ENABLED=1（后）...")
    on = await run_config(True, cases, cap_skills)

    if args.judge:
        print("\n[评审] LLM 盲评两组题目...")
        for rows in (off, on):
            for r, c in zip(rows, cases):
                j = await judge_one(c["jd"], c["resume"], r["questions"])
                r["judge_score"] = j["score"]
                r["judge_reason"] = j["reason"]
                r["judge_tokens"] = j["tokens"]
        for tag, rows in (("off", off), ("on", on)):
            sc = [r["judge_score"] for r in rows if isinstance(r.get("judge_score"), int)]
            print("   %s 组盲评均分: %s (n=%d)" % (tag, round(statistics.mean(sc), 2) if sc else None, len(sc)))

    a_off, a_on = agg(off), agg(on)
    out = {"cases": [c["id"] for c in cases], "cap_skills": cap_skills,
           "before": {"rows": off, "agg": a_off}, "after": {"rows": on, "agg": a_on}}
    if args.judge:
        sc = lambda rows: [r["judge_score"] for r in rows if isinstance(r.get("judge_score"), int)]
        out["before"]["judge_avg"] = round(statistics.mean(sc(off)), 2) if sc(off) else None
        out["after"]["judge_avg"] = round(statistics.mean(sc(on)), 2) if sc(on) else None
    with io.open(EVAL / "rag_ab_result.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    keys = [("avg_jd_skill_cover", "题目覆盖 JD 必须技能率"), ("avg_cap_cover", "题目覆盖岗位能力点率"),
            ("avg_diversity", "题目不重复度"), ("avg_tokens", "平均 tokens"), ("p50_ms", "P50 延迟(ms)"),
            ("p95_ms", "P95 延迟(ms)"), ("llm_calls", "LLM 调用次数")]
    lines = ["| 指标 | 加 RAG 前 | 加 RAG 后 | 变化 |", "|---|---|---|---|"]
    print("\n指标                        | 前        | 后        | 变化")
    print("----------------------------|-----------|-----------|------")
    for k, label in keys:
        b, a = a_off[k], a_on[k]
        delta = (a - b)
        print("%-27s | %-9s | %-9s | %+g" % (label, b, a, round(delta, 4)))
        lines.append("| %s | %s | %s | %+g |" % (label, b, a, round(delta, 4)))
    if args.judge and out["after"].get("judge_avg") is not None:
        lines.append("| LLM 盲评均分(0-10) | %s | %s | %+g |" % (
            out["before"]["judge_avg"], out["after"]["judge_avg"],
            round(out["after"]["judge_avg"] - out["before"]["judge_avg"], 2)))
    with io.open(EVAL / "rag_ab_table.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n已写出: eval/rag_ab_result.json, eval/rag_ab_table.md")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--judge", action="store_true", help="额外用 LLM 盲评两组题目（少量花费）")
    a = ap.parse_args()
    asyncio.run(main_async(a))
