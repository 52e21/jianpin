"""AI 招聘助理 Agent：JD 解析 → 简历匹配 → 面试题生成 → 推荐结论。

成本控制：
1. parse_jd / match_resume 纯规则，零 LLM。
2. 推荐结论规则优先：匹配度 ≥80 且缺失 ≤1 → 推荐；<50 → 不推荐，均零 LLM。
3. 同一 JD+简历组合缓存（TTL 可配）。
4. LLM 调用上限 2 次（面试题 1 次 + 待定结论 1 次）。
"""

import hashlib
import json
import logging
import re
import time
from typing import AsyncGenerator, Optional

from .config import CACHE_TTL_SECONDS, LLM_TEMPERATURE, DEEPSEEK_MODEL
from .tools import (
    parse_jd,
    match_resume,
    generate_interview_questions,
    summarize_recommendation,
)

logger = logging.getLogger("agent")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_handler)

# 缓存：key = (jd, resume) 标准化哈希 → (过期时间戳, 输出片段列表)
_result_cache: dict = {}


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "").strip()


def _cache_key(jd: str, resume: str) -> str:
    raw = _norm(jd) + "||" + _norm(resume)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _jd_summary(jd: str) -> str:
    """生成 JD 摘要（历史记录用，避免存全量长文本）。"""
    j = _norm(jd)
    return j[:60] + ("…" if len(j) > 60 else "")


# ---------------------------------------------------------------------------
# 主执行入口
# ---------------------------------------------------------------------------
async def run_agent(jd: str, resume: str, stats: Optional[dict] = None) -> AsyncGenerator[str, None]:
    """
    AI 招聘助理执行入口（async 生成器，兼容 SSE 流式输出）。

    阶段输出：
        【JD 解析】...
        【简历匹配】...
        【面试题生成】...
        【推荐结论】...
    """
    jd = (jd or "").strip()
    resume = (resume or "").strip()
    key = _cache_key(jd, resume)

    if stats is None:
        stats = {}
    stats.update(
        {
            "task": f"JD: {_jd_summary(jd)} | 简历: {_norm(resume)[:30]}",
            "cache_hit": False,
            "llm_call_count": 0,
            "llm_used": False,
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "elapsed_ms": 0,
            "match_score": None,
        }
    )
    started = time.time()

    def _log_stats():
        logger.info(
            "AGENT-EXEC task=%r | cache_hit=%s | llm_calls=%d | total_tokens=%d | match_score=%s | elapsed_ms=%.0f",
            stats["task"],
            stats["cache_hit"],
            stats["llm_call_count"],
            stats["total_tokens"],
            stats["match_score"],
            stats["elapsed_ms"],
        )

    # ---- 1. 缓存命中 ----
    now = time.time()
    hit = _result_cache.get(key)
    if hit:
        expiry, segments = hit
        if now < expiry:
            stats["cache_hit"] = True
            stats["elapsed_ms"] = (time.time() - started) * 1000
            _log_stats()
            for seg in segments:
                yield seg
            return
        _result_cache.pop(key, None)

    segments: list = []

    def emit(text: str):
        segments.append(text)
        return text

    if not jd or not resume:
        yield emit("【推荐结论】\n")
        yield emit("错误：JD 与简历都不能为空。\n")
        _log_stats()
        return

    # ========== 步骤 1：JD 解析（纯规则，零 LLM） ==========
    yield emit("【JD 解析】正在解析岗位要求...\n")
    jd_result = parse_jd(jd)

    def _join_list(items, empty="未要求"):
        return "、".join(items) if items else empty

    header = (
        f"【职位】{jd_result['position'] or '未识别'}"
        + (f" | {jd_result['level']}" if jd_result["level"] else "")
        + (f" | {jd_result['department']}" if jd_result["department"] else "")
        + (f" | {jd_result['work_mode']}" if jd_result["work_mode"] else "")
    )
    resp_lines = [f"{i + 1}. {r}" for i, r in enumerate(jd_result["responsibilities"])]
    jd_pretty = (
        header + "\n"
        + ("【职责】\n" + "\n".join(resp_lines) + "\n" if resp_lines else "")
        + f"【技能要求】\n必须：{_join_list(jd_result['skills']['required'])}\n"
        + f"优先：{_join_list(jd_result['skills']['preferred'])}\n"
        + f"【经验要求】\n"
        + (f"年限：{jd_result['experience']['min_years']}" + (f"-{jd_result['experience']['max_years']} 年" if jd_result['experience']['max_years'] else " 年以上") if jd_result['experience']['min_years'] else "年限：未要求")
        + f"\n行业：{_join_list(jd_result['experience']['industry'])}\n"
        + f"【学历要求】\n{jd_result['education']['level'] or '不限'}，{jd_result['education']['major']}"
        + ("（硬性要求）" if jd_result["education"]["is_strict"] else "")
        + f"\n【软技能】{_join_list(jd_result['soft_skills'])}\n"
        + f"【加分项】{_join_list(jd_result['bonus'])}"
    )
    yield emit(jd_pretty + "\n\n")

    # ========== 步骤 2：简历匹配（纯规则，零 LLM） ==========
    yield emit("【简历匹配】正在计算匹配度...\n")
    match_result = match_resume(jd_result, resume)
    stats["match_score"] = match_result["match_score"]
    dims = match_result.get("dimensions", {})
    match_pretty = (
        f"匹配度：{match_result['match_score']}%\n"
        + (f"维度：技能 {dims.get('skill_score')} | 经验 {dims.get('exp_score')} | 学历 {dims.get('edu_score')} | 软技能 {dims.get('soft_score')} | 加分 {dims.get('bonus_score')}\n" if dims else "")
        + f"命中：{'、'.join(match_result['matched_skills']) if match_result['matched_skills'] else '无'}\n"
        + (f"缺失(必须)：{'、'.join(match_result['missing_skills'])}\n" if match_result['missing_skills'] else "")
        + f"摘要：{match_result['summary']}"
    )
    yield emit(match_pretty + "\n\n")

    # ========== 步骤 3：面试题生成（仅中等以上匹配才调 LLM） ==========
    score = match_result["match_score"]
    questions: list = []
    if score < 50:
        # 低匹配：成本控制短路 —— 不生成面试题、不调 LLM
        yield emit("【面试题生成】匹配度过低，跳过面试题生成以节省成本（LLM 调用 0 次）。\n\n")
    else:
        yield emit("【面试题生成】正在生成个性化面试题...\n")
        questions = await generate_interview_questions(jd, resume, stats)
        if questions and not questions[0].startswith("（未配置"):
            stats["llm_call_count"] += 1
            stats["llm_used"] = True
        questions_text = "\n".join(f"Q{i + 1}. {q}" for i, q in enumerate(questions))
        yield emit(questions_text + "\n\n")

    # ========== 步骤 4：推荐结论（规则优先，按需 LLM） ==========
    yield emit("【推荐结论】正在汇总评估...\n")
    rec = await summarize_recommendation(
        match_result["match_score"],
        match_result["matched_skills"],
        match_result["missing_skills"],
        questions,
        stats,
    )
    if rec.get("llm_used"):
        stats["llm_call_count"] += 1
        stats["llm_used"] = True
    yield emit(f"结论：{rec['conclusion']}\n")
    yield emit(f"理由：{rec['reason']}\n")

    # ---- 缓存 ----
    _result_cache[key] = (time.time() + CACHE_TTL_SECONDS, segments)
    stats["elapsed_ms"] = (time.time() - started) * 1000
    _log_stats()


# ---------------------------------------------------------------------------
# 带历史落库的外层入口
# ---------------------------------------------------------------------------
async def run_agent_with_history(jd: str, resume: str) -> AsyncGenerator[str, None]:
    """外层：执行 Agent 并把统计信息写入 SQLite 历史。"""
    start = time.time()
    result_parts: list = []
    stats: dict = {}
    try:
        async for chunk in run_agent(jd, resume, stats):
            result_parts.append(chunk)
            yield chunk
    finally:
        duration_ms = int((time.time() - start) * 1000)
        result_text = "".join(result_parts)
        try:
            from .database import save_history

            save_history(
                task=stats.get("task", f"JD: {_jd_summary(jd)}"),
                result=result_text,
                llm_calls=stats.get("llm_call_count", 0),
                total_tokens=stats.get("total_tokens", 0),
                cache_hit=bool(stats.get("cache_hit", False)),
                duration_ms=duration_ms,
            )
        except Exception as e:
            logger.warning("SAVE-HISTORY-ERROR task=%r error=%r", stats.get("task"), e)


# ---------------------------------------------------------------------------
# 结构化分析入口（供 /api/agent/analyze 使用，同步 JSON 非 SSE）
# ---------------------------------------------------------------------------
_analyze_cache: dict = {}


async def analyze_agent(jd: str, resume: str, job_url: str = "") -> dict:
    """执行完整分析并返回结构化结果（执行书字段为准）。

    与 run_agent 共用同一套规则解析/匹配/面试题/推荐逻辑与缓存键。
    返回体：
    {
      "jd_parse": {...}, "match_result": {...},
      "interview_questions": [{category,difficulty,question}],
      "recommendation": {type, reason},
      "job_url": str | None,
      "llm_calls": int, "cache_hit": bool
    }
    """
    jd = (jd or "").strip()
    resume = (resume or "").strip()
    job_url = (job_url or "").strip() or None
    key = _cache_key(jd, resume)

    now = time.time()
    hit = _analyze_cache.get(key)
    if hit:
        expiry, payload = hit
        if now < expiry:
            payload["cache_hit"] = True
            payload["job_url"] = job_url  # 缓存不区分链接，命中时附加本次链接
            return payload
        _analyze_cache.pop(key, None)

    stats = {
        "llm_call_count": 0,
        "llm_used": False,
        "total_tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }
    started = time.time()

    # 1. JD 解析（纯规则）
    jd_parse = parse_jd(jd)

    # 2. 简历匹配（纯规则加权）
    mr = match_resume(jd_parse, resume)
    dims_raw = mr.get("dimensions", {})
    match_result = {
        "score": mr["match_score"],
        "dimensions": {
            "skills": dims_raw.get("skill_score", 0),
            "experience": dims_raw.get("exp_score", 0),
            "education": dims_raw.get("edu_score", 0),
            "soft_skills": dims_raw.get("soft_score", 0),
            "bonus": dims_raw.get("bonus_score", 0),
        },
        "matched_skills": mr["matched_skills"],
        "missing_skills": mr["missing_skills"],
        "bonus_skills": [s for s in jd_parse.get("bonus", []) if s.replace("有", "") in resume],
        "summary": mr["summary"],
    }

    # 3. 面试题（低匹配 <50 短路，零 LLM；否则调 LLM）
    interview_questions = []
    if mr["match_score"] < 50:
        recommendation = {
            "type": "不推荐",
            "reason": mr["summary"] + "；匹配度过低，跳过面试题生成（零 LLM）。",
        }
        llm_used = False
    else:
        questions = await generate_interview_questions(jd, resume, stats, structured=True)
        if not questions[0].get("question", "").startswith(("（未配置", "（面试题生成失败", "（错误")):
            stats["llm_call_count"] += 1
            stats["llm_used"] = True
        interview_questions = questions

        # 4. 推荐结论（规则优先）
        rec = await summarize_recommendation(
            mr["match_score"], mr["matched_skills"], mr["missing_skills"],
            [q["question"] for q in interview_questions], stats,
        )
        if rec.get("llm_used"):
            stats["llm_call_count"] += 1
            stats["llm_used"] = True
        recommendation = {"type": rec["conclusion"], "reason": rec["reason"]}
        llm_used = stats["llm_used"]

    payload = {
        "jd_parse": jd_parse,
        "match_result": match_result,
        "interview_questions": interview_questions,
        "recommendation": recommendation,
        "job_url": job_url,
        "llm_calls": stats["llm_call_count"],
        "total_tokens": stats.get("total_tokens", 0),
        "cache_hit": False,
    }
    _analyze_cache[key] = (time.time() + CACHE_TTL_SECONDS, payload)
    payload["cache_hit"] = False

    # 落历史（复用执行历史表，job_url 单独列）
    try:
        from .database import save_history

        save_history(
            task=f"JD: {_jd_summary(jd)} | 简历: {_norm(resume)[:30]}",
            result=(
                f"【结构化分析】匹配度 {match_result['score']}% | 结论：{recommendation['type']}\n"
                f"理由：{recommendation['reason']}\n面试题 {len(interview_questions)} 个"
            ),
            llm_calls=stats["llm_call_count"],
            total_tokens=stats.get("total_tokens", 0),
            cache_hit=False,
            duration_ms=int((time.time() - started) * 1000),
            job_url=job_url or "",
        )
    except Exception as e:
        logger.warning("ANALYZE-SAVE-HISTORY-ERROR %r", e)

    logger.info(
        "ANALYZE-EXEC task=JD:%s | score=%s | llm_calls=%d | tokens=%d",
        _jd_summary(jd), mr["match_score"], stats["llm_call_count"], stats.get("total_tokens", 0),
    )
    return payload
