"""AI 招聘助理 Agent：JD 解析 → 简历匹配 → 面试题生成 → 推荐结论。

成本控制：
1. parse_jd / match_resume 纯规则，零 LLM。
2. 推荐结论规则优先：匹配度 ≥80 且缺失 ≤1 → 推荐；<50 → 不推荐，均零 LLM。
3. 同一 JD+简历组合缓存（TTL 可配）。
4. LLM 调用上限 2 次（面试题 1 次 + 待定结论 1 次）。
"""

import copy
import hashlib
import json
import logging
import os
import re
import time
from typing import AsyncGenerator, Optional

from .config import CACHE_TTL_SECONDS, LLM_TEMPERATURE, DEEPSEEK_MODEL
from . import trace
from .tools import (
    parse_jd,
    match_resume,
    generate_interview_questions,
    summarize_recommendation,
    build_interview_context,
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

# 第 6 步：输入短于这个字符数时，结构化上下文的固定开销大于原始文本，直接原样送
CTX_MIN_CHARS = 200


# R6：从 JD 解析结果取技能列表（必须 + 优先，去重），供只读检索注入面试题生成使用。
def _jd_skills(jd_parse: dict) -> list:
    sk = (jd_parse or {}).get("skills", {}) or {}
    out: list = []
    for s in list(sk.get("required", []) or []) + list(sk.get("preferred", []) or []):
        if s and s not in out:
            out.append(s)
    return out

# ---------------------------------------------------------------------------
# 第 10 步：角色化结论文案
# ---------------------------------------------------------------------------
# type 保持机器可读（推荐/待定/不推荐）——第 7 步反馈枚举、评测集 ground truth、
# 前端三色卡片都依赖它；label 是给人看的、按角色变化的文案。
ROLE_HR = "hr"
ROLE_CANDIDATE = "candidate"
ROLES = (ROLE_HR, ROLE_CANDIDATE)

ROLE_LABELS = {
    ROLE_HR: {
        "推荐": "推荐",
        "待定": "待定",
        "不推荐": "不推荐",
    },
    ROLE_CANDIDATE: {
        "推荐": "高匹配，建议投递",
        "待定": "中匹配，可尝试，建议补强",
        "不推荐": "低匹配，差距较大，建议先补技能或换岗位",
    },
}


def _role_label(conclusion: str, role: str) -> str:
    """把机器结论映射成该角色下的展示文案；未知角色按 HR 处理。"""
    r = role if role in ROLES else ROLE_HR
    return ROLE_LABELS[r].get(conclusion, conclusion)


# ---------------------------------------------------------------------------
# 第 5 步：节点埋点辅助
# ---------------------------------------------------------------------------
def _traced_node(trace_id: str, task_id: str, node_name: str, input_text: str, fn):
    """执行一个同步节点并把过程写入 trace_events。

    - 成功：记录 output_json + latency_ms
    - 异常：记录 degraded=True + degrade_reason，并把异常继续抛出（不改变原有行为）
    """
    t0 = time.perf_counter()
    ih = trace.hash_input(input_text)
    try:
        out = fn()
    except Exception as e:
        trace.record(trace_id, task_id, node_name, input_hash=ih,
                     degraded=True, degrade_reason=f"{type(e).__name__}: {e}",
                     latency_ms=(time.perf_counter() - t0) * 1000)
        raise
    trace.record(trace_id, task_id, node_name, input_hash=ih, output=out,
                 latency_ms=(time.perf_counter() - t0) * 1000)
    return out


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "").strip()


def _cache_key(jd: str, resume: str, tenant_id: str = "default", session_id: str = "default",
               role: str = ROLE_HR) -> str:
    """第 9/10 步：缓存 key 加入租户/会话/角色前缀。

    - 原 key = md5(JD + 简历)，全局共享 —— A 公司命中后 B 公司会读到同一结果。
    - 第 10 步 role 会改变返回文案，因此必须计入 key，否则 hr 缓存会被 candidate 复用。
    """
    raw = ((tenant_id or "default") + "|" + (session_id or "default") + "|"
           + (role if role in ROLES else ROLE_HR) + "|"
           + _norm(jd) + "||" + _norm(resume))
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _jd_summary(jd: str) -> str:
    """生成 JD 摘要（历史记录用，避免存全量长文本）。"""
    j = _norm(jd)
    return j[:60] + ("…" if len(j) > 60 else "")


# ---------------------------------------------------------------------------
# 主执行入口
# ---------------------------------------------------------------------------
async def run_agent(jd: str, resume: str, stats: Optional[dict] = None,
                    tenant_id: str = "default", session_id: str = "default",
                    role: str = ROLE_HR) -> AsyncGenerator[str, None]:
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
    tenant_id = (tenant_id or "default").strip() or "default"
    session_id = (session_id or "default").strip() or "default"
    role = role if role in ROLES else ROLE_HR
    key = _cache_key(jd, resume, tenant_id, session_id, role)

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
    no_scorable = bool(match_result.get("no_scorable_dimension"))
    questions: list = []
    if no_scorable:
        # 事项 1：JD 无可评分维度 → 不生成面试题、不调 LLM
        yield emit("【面试题生成】JD 未识别出可评分维度，跳过面试题生成（LLM 调用 0 次）。\n\n")
    elif score < 50:
        # 低匹配：成本控制短路 —— 不生成面试题、不调 LLM
        yield emit("【面试题生成】匹配度过低，跳过面试题生成以节省成本（LLM 调用 0 次）。\n\n")
    else:
        yield emit("【面试题生成】正在生成个性化面试题...\n")
        # 第 6 步：SSE 旧链路同样改为结构化上下文注入（输出仍为纯文本列表）
        questions = await generate_interview_questions(
            jd, resume, stats,
            context=build_interview_context(jd_result, match_result, resume),
            rag_skills=_jd_skills(jd_result))
        # 修复（llm_calls 计数 bug）：与 analyze 链路一致，以节点回报的标志为准
        if stats.pop("questions_llm_called", False):
            stats["llm_call_count"] += 1
            stats["llm_used"] = True
        questions_text = "\n".join(f"Q{i + 1}. {q}" for i, q in enumerate(questions))
        yield emit(questions_text + "\n\n")

    # ========== 步骤 4：推荐结论（规则优先，按需 LLM） ==========
    if no_scorable:
        # 事项 1：不进入阈值判定，直接待定 + 人工复核（原实现会因 100 分给出"推荐"）
        yield emit("【推荐结论】\n")
        rec = {"conclusion": "待定",
               "reason": match_result.get("reason") or match_result["summary"],
               "llm_used": False}
    else:
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
    # 第 10 步：SSE 链路的结论文案同样按角色输出
    yield emit(f"结论：{_role_label(rec['conclusion'], role)}\n")
    yield emit(f"理由：{rec['reason']}\n")

    # ---- 缓存 ----
    _result_cache[key] = (time.time() + CACHE_TTL_SECONDS, segments)
    stats["elapsed_ms"] = (time.time() - started) * 1000
    _log_stats()


# ---------------------------------------------------------------------------
# 带历史落库的外层入口
# ---------------------------------------------------------------------------
async def run_agent_with_history(jd: str, resume: str,
                                 tenant_id: str = "default", session_id: str = "default",
                                 role: str = ROLE_HR) -> AsyncGenerator[str, None]:
    """外层：执行 Agent 并把统计信息写入 SQLite 历史。"""
    start = time.time()
    result_parts: list = []
    stats: dict = {}
    task_id = trace.new_task_id()          # 第 7 步：SSE 链路同样落 task_id
    try:
        async for chunk in run_agent(jd, resume, stats, tenant_id, session_id, role):
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
                task_id=task_id,
            )
        except Exception as e:
            logger.warning("SAVE-HISTORY-ERROR task=%r error=%r", stats.get("task"), e)


# ---------------------------------------------------------------------------
# 结构化分析入口（供 /api/agent/analyze 使用，同步 JSON 非 SSE）
# ---------------------------------------------------------------------------
_analyze_cache: dict = {}


def _save_analyze_history(payload: dict, jd: str, resume: str, job_url,
                          duration_ms: int, llm_calls: int = 0, total_tokens: int = 0,
                          cache_hit: bool = False):
    """把一次分析落进执行历史。

    缓存命中路径**同样要落**（修复：否则返回的是最初那次任务的 task_id，
    那条历史一旦被删除，用户点「采纳/改判」就会 404）。
    """
    try:
        from .database import save_history

        mr = payload.get("match_result", {}) or {}
        rec = payload.get("recommendation", {}) or {}
        result = (
            f"【结构化分析】匹配度 {mr.get('score')}% | 结论：{rec.get('type')}\n"
            f"理由：{rec.get('reason')}\n面试题 {len(payload.get('interview_questions') or [])} 个"
        )
        if cache_hit:
            result += "\n（命中缓存，未重新调用 LLM）"
        save_history(
            task=f"JD: {_jd_summary(jd)} | 简历: {_norm(resume)[:30]}",
            result=result,
            llm_calls=llm_calls,
            total_tokens=total_tokens,
            cache_hit=cache_hit,
            duration_ms=duration_ms,
            job_url=job_url or "",
            task_id=payload.get("task_id", ""),
        )
        # A1（Agent 子模块）：同一 session_id 共享追问状态。
        # 只更新本次输入相关字段（jd/resume/role/tenant），**不动** round/status/pending——
        # A4「补充后重走链路」要靠 round 累加，不能被普通请求重置。
        try:
            from .database import upsert_ask_session

            upsert_ask_session(
                session_id=payload.get("session_id", ""),
                tenant_id=payload.get("tenant_id", "default"),
                role=payload.get("role", "hr"),
                jd=jd, resume=resume, job_url=job_url or "",
            )
        except Exception:            # 挂载失败不影响主流程
            pass
    except Exception as e:
        logger.warning("ANALYZE-SAVE-HISTORY-ERROR %r", e)


async def analyze_agent(jd: str, resume: str, job_url: str = "", ctx_mode: str = "structured",
                        tenant_id: str = "default", session_id: str = "default",
                        role: str = ROLE_HR, answers: list = None) -> dict:
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
    tenant_id = (tenant_id or "default").strip() or "default"
    session_id = (session_id or "default").strip() or "default"
    role = role if role in ROLES else ROLE_HR
    # ---- A4/A5：追问状态机 ----
    # round = 「已追问轮数」。这里只做两件事：
    #   1) 把 HR 的补充回答**累积合并**进 JD（merged_jd），后续解析/匹配都用合并后的文本；
    #   2) 信息仍不足时按轮数决定"继续追问"还是"转人工复核（待定）"。
    # 开关 ASK_ENABLED=0 可整体关闭该分支（A 阶段评测的对照组）。
    ASK_ON = os.environ.get("ASK_ENABLED", "1") != "0"
    ask_state = None
    if ASK_ON:
        try:
            from .database import fetch_ask_session

            ask_state = fetch_ask_session(session_id)
        except Exception:
            ask_state = None
    ask_round = int((ask_state or {}).get("round") or 0)
    base_jd = ((ask_state or {}).get("merged_jd") or "").strip() or jd
    # 只有"带补充回答"的请求才算追问续接，才复用会话里合并过的 JD；
    # 否则一律用本次请求自己的 JD —— 否则同一 session_id 的连续请求（如评测跑批）
    # 会互相覆盖 JD，实测会把一致率从 0.8141 打到 0.3216。
    if ASK_ON and answers:
        from .ask import merge_answers

        jd = merge_answers(base_jd, answers)      # 累积合并历轮补充

    key = _cache_key(jd, resume, tenant_id, session_id, role)

    started = time.time()          # 缓存命中路径也要算耗时（并写历史行）
    now = time.time()
    hit = _analyze_cache.get(key)
    if hit:
        expiry, cached = hit
        if now < expiry:
            # 第 14 步：缓存里存的是对象引用。原实现直接改 payload["cache_hit"]/["job_url"]，
            # 改的是**缓存本体**，也改到了之前已经返回给调用方的同一个对象上 ——
            # 后果：不同岗位链接会互相覆盖；调用方读到的 cache_hit 会被后续请求篡改。
            payload = copy.deepcopy(cached)
            payload["cache_hit"] = True
            payload["job_url"] = job_url  # 缓存不区分链接，命中时附加本次链接
            # 修复（事项 5 验证时发现）：缓存命中也要有自己的 task_id 与历史行。
            # 否则返回的是**最初那次任务**的 task_id，一旦那条历史记录被删除
            # （前端有单条删除/清空功能），用户点「采纳/改判」就会收到 404。
            source_task_id = payload.get("task_id", "")
            payload["task_id"] = trace.new_task_id()
            payload["cache_source_task_id"] = source_task_id  # 保留回溯到最初那次运行
            _save_analyze_history(payload, jd, resume, job_url,
                                  duration_ms=int((time.time() - started) * 1000), cache_hit=True)
            return payload
        _analyze_cache.pop(key, None)

    stats = {
        "llm_call_count": 0,
        "llm_used": False,
        "total_tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }

    # 第 5 步：为本次分析生成 trace_id / task_id，并通过 stats 透传给 LLM 节点
    trace_id = trace.new_trace_id()
    task_id = trace.new_task_id()
    stats["trace_id"] = trace_id
    stats["task_id"] = task_id

    # 1. JD 解析（纯规则）
    jd_parse = _traced_node(trace_id, task_id, "parse_jd", jd, lambda: parse_jd(jd))

    # ---- A2–A5：信息不足分支（插入点：parse_jd 之后、match_resume 之前）----
    # 主干不动：只有"信息不足"才走分支；充足时下面一行注释之后的行为与加 Agent 之前完全一致。
    if ASK_ON:
        from .ask import ROUND_LIMIT, generate_questions, should_ask, sufficiency

        suff = sufficiency(jd_parse, jd)
        if suff["status"] == "insufficient":
            qs = generate_questions(suff, jd_parse)
            can_ask = should_ask(ask_round)                   # round < 2 才继续追问
            next_round = ask_round + 1 if can_ask else ask_round
            trace.record(trace_id, task_id, "ask_branch", input_hash=trace.hash_input(jd, resume),
                         output={"status": "need_more_info" if can_ask else "insufficient_final",
                                 "missing_fields": suff["missing_fields"], "round": next_round,
                                 "questions": qs},
                         degraded=not can_ask,
                         degrade_reason="" if can_ask else "追问已达上限，转人工复核")
            if can_ask:
                try:
                    from .database import upsert_ask_session

                    upsert_ask_session(session_id=session_id, tenant_id=tenant_id, role=role,
                                       jd=jd, resume=resume, job_url=job_url or "",
                                       status="insufficient", round_no=next_round,
                                       pending_questions=qs, merged_jd=jd)
                except Exception:
                    pass
                return {
                    "status": "need_more_info",
                    "session_id": session_id, "tenant_id": tenant_id, "role": role,
                    "task_id": task_id, "trace_id": trace_id, "job_url": job_url,
                    "ask": {"questions": qs, "round": next_round, "round_limit": ROUND_LIMIT,
                            "reason": suff["reason"], "missing_fields": suff["missing_fields"]},
                    "jd_parse": jd_parse,
                    "match_result": None,
                    "interview_questions": [],
                    "recommendation": {"type": "待定",
                                       "reason": "JD 信息不足（%s），已向 HR 追问（第 %d/%d 轮）" % (
                                           suff["reason"], next_round, ROUND_LIMIT),
                                       "label": _role_label("待定", role), "role": role},
                    "llm_calls": 0, "total_tokens": 0, "cache_hit": False,
                }
            # A5 边界：追问满 2 轮仍不足 → 转人工复核（待定），不再消耗 LLM
            try:
                from .database import upsert_ask_session

                upsert_ask_session(session_id=session_id, status="closed",
                                   pending_questions=[], merged_jd=jd)
            except Exception:
                pass
            return {
                "status": "insufficient_final",
                "session_id": session_id, "tenant_id": tenant_id, "role": role,
                "task_id": task_id, "trace_id": trace_id, "job_url": job_url,
                "ask": {"questions": [], "round": ask_round, "round_limit": ROUND_LIMIT,
                        "reason": "追问已达上限（%d 轮），信息仍不足，转人工复核" % ROUND_LIMIT,
                        "missing_fields": suff["missing_fields"]},
                "jd_parse": jd_parse,
                "match_result": None,
                "interview_questions": [],
                "recommendation": {"type": "待定",
                                   "reason": "JD 信息不足且追问已达上限（%d 轮），转人工复核" % ROUND_LIMIT,
                                   "label": _role_label("待定", role), "role": role},
                "llm_calls": 0, "total_tokens": 0, "cache_hit": False,
            }
    # ---- 分支结束：以下为原有主链路（信息充足时行为不变）----

    # 2. 简历匹配（纯规则加权）
    mr = _traced_node(trace_id, task_id, "match_resume", jd + "\u0001" + resume,
                      lambda: match_resume(jd_parse, resume))
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
    no_scorable = bool(mr.get("no_scorable_dimension"))

    def _trace_skipped(skip_reason: str, conclusion: str):
        """短路/跳过时也留痕，保证每个 task 稳定产出 4 条节点 Trace。"""
        trace.record(trace_id, task_id, "generate_interview_questions",
                     input_hash=trace.hash_input(jd, resume),
                     output={"skipped": True, "reason": skip_reason},
                     latency_ms=0, degraded=False, degrade_reason=skip_reason)
        trace.record(trace_id, task_id, "summarize_recommendation",
                     input_hash=trace.hash_input(mr["match_score"]),
                     output={"skipped": True, "reason": skip_reason, "conclusion": conclusion},
                     latency_ms=0, degraded=False, degrade_reason=skip_reason)

    if no_scorable:
        # 事项 1：JD 未识别出可评分维度 → 待定 + 人工复核，不调 LLM、不生成面试题。
        recommendation = {
            "type": "待定",
            "reason": mr.get("reason") or mr["summary"],
            "label": _role_label("待定", role),
            "role": role,
        }
        llm_used = False
        _trace_skipped("JD 未识别出可评分维度（total_w=0），跳过 LLM，建议人工复核", "待定")
    elif mr["match_score"] < 50:
        recommendation = {
            "type": "不推荐",
            "reason": mr["summary"] + "；匹配度过低，跳过面试题生成（零 LLM）。",
            "label": _role_label("不推荐", role),
            "role": role,
        }
        llm_used = False
        _trace_skipped("低分短路：match_score<50，成本控制目的主动跳过", "不推荐")
    else:
        # 第 6 步：注入结构化上下文，不再直塞 JD 全文 + 简历全文。
        # - ctx_mode="raw"：强制走旧行为，用于 A/B 对比实验（评测脚本用）
        # - 输入本身很短时（<200 字）结构化包装是净开销，直接原样送
        raw_len = len(jd) + len(resume)
        if ctx_mode != "raw" and raw_len >= CTX_MIN_CHARS:
            iv_context = build_interview_context(jd_parse, match_result, resume)
        else:
            iv_context = None
        questions = await generate_interview_questions(jd, resume, stats, structured=True,
                                                       context=iv_context,
                                                       rag_skills=_jd_skills(jd_parse))
        # 第 13 步：防空列表越界。
        # structured=True 时，若模型返回空内容，函数会返回 [] ——
        # 原实现紧接着访问 questions[0]，直接 IndexError，整个请求 500。
        if not questions:
            questions = [{
                "category": "提示", "difficulty": "-",
                "question": "（面试题生成失败：模型返回空内容）",
                "answer_points": [], "scoring_criteria": "",
            }]
        elif not isinstance(questions[0], dict):
            # 防御性兜底：非预期形态（例如误传纯文本列表）也要收敛成结构化对象
            questions = [{"category": "综合", "difficulty": "中级", "question": str(q),
                          "answer_points": [], "scoring_criteria": ""} for q in questions]
        # 修复（llm_calls 计数 bug）：以节点回报的机器可读标志为准，
        # 不再用"返回文本是否以某前缀开头"来猜（原实现因括号不一致误计 164/200 条）。
        if stats.pop("questions_llm_called", False):
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
        recommendation = {"type": rec["conclusion"], "reason": rec["reason"],
                          "label": _role_label(rec["conclusion"], role), "role": role}
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
        # 第 5 步新增：可观测与反馈所需的关联标识（第 7 步反馈接口用它定位任务）
        "task_id": task_id,
        "trace_id": trace_id,
        # 第 9 步新增：缓存隔离维度（命中缓存时这两个值与请求者必然一致）
        "tenant_id": tenant_id,
        "session_id": session_id,
        # 第 10 步新增：本次请求的角色（label 已按角色生成）
        "role": role,
    }
    # 第 14 步：入缓存的是**副本**，保证返回给调用方的对象与缓存对象不共享引用
    # （否则调用方一旦修改返回值，缓存就被污染）
    _analyze_cache[key] = (time.time() + CACHE_TTL_SECONDS, copy.deepcopy(payload))

    # 落历史（复用执行历史表，job_url 单独列）
    _save_analyze_history(payload, jd, resume, job_url,
                          duration_ms=int((time.time() - started) * 1000),
                          llm_calls=stats["llm_call_count"],
                          total_tokens=stats.get("total_tokens", 0),
                          cache_hit=False)

    # A4：追问闭环 —— 只有"之前追问过"的会话才改状态，避免把全新会话从 idle 改成 done
    if ASK_ON and ask_state and (ask_state.get("status") == "insufficient" or ask_round > 0):
        try:
            from .database import upsert_ask_session

            upsert_ask_session(session_id=session_id, status="done",
                               merged_jd=jd, pending_questions=[])
        except Exception:
            pass

    logger.info(
        "ANALYZE-EXEC task=JD:%s | score=%s | llm_calls=%d | tokens=%d",
        _jd_summary(jd), mr["match_score"], stats["llm_call_count"], stats.get("total_tokens", 0),
    )
    return payload
