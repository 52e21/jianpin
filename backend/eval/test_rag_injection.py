# -*- coding: utf-8 -*-
"""
R6 验收：检索结果注入面试题生成（且绝不注入匹配打分）

覆盖：
  A. 注入存在且格式正确：prompt 里出现「岗位能力参考：」与检索到的技能行
  B. 追加而非替换：把注入块从 prompt 里抠掉后，与「不传 rag_skills」的 prompt **逐字一致**
  C. 开关：RAG_ENABLED=0 时不注入（A/B 用）
  D. 降级：检索抛异常时不注入、不报错，stats 记录 rag_error
  E. 只注入面试题节点：match_resume 的结果在 RAG 开关前后完全相同
  F. stats 诊断字段齐全（rag_chars / rag_chunk_ids / rag_modes）

用假 AsyncOpenAI 客户端捕获 prompt，不调用真实模型。
用法：python eval/test_rag_injection.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import openai                      # noqa: E402
from app.tools import generate_interview_questions, match_resume, parse_jd   # noqa: E402

JD = ("招聘 Java 后端工程师。职责：负责交易系统的服务端开发。"
      "要求：熟练 Java、Spring Boot、MySQL，熟悉 Redis 与消息队列，3 年以上经验。")
RESUME = "本科，5 年 Java 后端开发经验，熟悉 Spring Boot、MySQL、Redis，做过高并发订单系统。"
FORMAT_MARK = "每道题必须包含"          # structured=True 时 format_req 的开头
RAG_MARK = "岗位能力参考："

CAPTURED = {}


class _Msg:
    def __init__(self, c):
        self.content = c


class _Choice:
    def __init__(self, c):
        self.message = _Msg(c)
        self.finish_reason = "stop"


class _Usage:
    total_tokens = 123
    prompt_tokens = 100
    completion_tokens = 23


class _Resp:
    def __init__(self, c):
        self.choices = [_Choice(c)]
        self.usage = _Usage()


class _Completions:
    async def create(self, **kw):
        CAPTURED["messages"] = kw.get("messages")
        CAPTURED["model"] = kw.get("model")
        return _Resp(json.dumps([{
            "category": "技术能力", "difficulty": "中级", "question": "Q1",
            "answer_points": ["a"], "scoring_criteria": "c"}], ensure_ascii=False))


class _Chat:
    def __init__(self):
        self.completions = _Completions()


class _FakeClient:
    def __init__(self, **kw):
        self.chat = _Chat()


def call(rag_skills, enabled=None, break_inject=False):
    """跑一次面试题生成，返回 (prompt, stats, 结果)。"""
    old_env = os.environ.get("RAG_ENABLED")
    if enabled is None:
        os.environ.pop("RAG_ENABLED", None)
    else:
        os.environ["RAG_ENABLED"] = enabled
    orig_client = openai.AsyncOpenAI
    openai.AsyncOpenAI = _FakeClient
    inject_mod = None
    orig_inject = None
    if break_inject:
        import app.rag.inject as inject_mod
        orig_inject = inject_mod.capability_context_for_skills
        def _boom(*a, **k):
            raise RuntimeError("检索不可用（模拟）")
        inject_mod.capability_context_for_skills = _boom
    CAPTURED.clear()
    stats = {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0}
    try:
        out = asyncio.run(generate_interview_questions(
            JD, RESUME, stats, structured=True, context=None, rag_skills=rag_skills))
    finally:
        openai.AsyncOpenAI = orig_client
        if inject_mod is not None and orig_inject is not None:
            inject_mod.capability_context_for_skills = orig_inject
        if old_env is None:
            os.environ.pop("RAG_ENABLED", None)
        else:
            os.environ["RAG_ENABLED"] = old_env
    prompt = CAPTURED["messages"][0]["content"]
    return prompt, stats, out


def part_a():
    print("=== A. 注入存在且格式正确 ===")
    skills = parse_jd(JD)["skills"]
    use = (skills["required"] + skills["preferred"])[:5]
    prompt, stats, out = call(use)
    ok = RAG_MARK in prompt
    lines = [ln for ln in prompt.splitlines() if ln.startswith("- ")]
    print("  检索技能: %s" % use)
    print("  注入块存在: %s" % ("✔" if ok else "✘"))
    print("  注入行: %s" % lines[:5])
    ok &= len(lines) > 0
    ok &= out and out[0]["question"] == "Q1"      # 返回值仍正常解析
    print("  A 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_b():
    print("\n=== B. 追加而非替换（抠掉注入块后应逐字等于无 RAG 的 prompt）===")
    skills = parse_jd(JD)["skills"]["required"]
    p_rag, _, _ = call(skills)
    p_plain, _, _ = call(None)
    ok = RAG_MARK not in p_plain
    print("  无 rag_skills 时无注入块: %s" % ("✔" if ok else "✘"))
    if RAG_MARK in p_rag and FORMAT_MARK in p_rag:
        start = p_rag.index(RAG_MARK)
        end = p_rag.index(FORMAT_MARK)
        stripped = p_rag[:start] + p_rag[end:]
        same = stripped == p_plain
        print("  抠掉注入块 == 原 prompt: %s" % ("✔" if same else "✘"))
        ok &= same
    else:
        print("  注入块或格式段缺失 ✘")
        ok = False
    print("  B 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_c():
    print("\n=== C. 开关 RAG_ENABLED=0 ===")
    skills = parse_jd(JD)["skills"]["required"]
    p_on, _, _ = call(skills, enabled="1")
    p_off, s_off, _ = call(skills, enabled="0")
    ok = (RAG_MARK in p_on) and (RAG_MARK not in p_off)
    print("  开启时有注入: %s；关闭时无注入: %s %s" % (
        RAG_MARK in p_on, RAG_MARK not in p_off, "✔" if ok else "✘"))
    print("  C 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_d():
    print("\n=== D. 降级：检索抛异常不得影响生成 ===")
    skills = parse_jd(JD)["skills"]["required"]
    prompt, stats, out = call(skills, break_inject=True)
    ok = (RAG_MARK not in prompt) and bool(out) and "rag_error" in stats
    print("  无注入: %s；仍返回结果: %s；stats.rag_error=%s %s" % (
        RAG_MARK not in prompt, bool(out), stats.get("rag_error"), "✔" if ok else "✘"))
    print("  D 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_e():
    print("\n=== E. 打分链路不受影响（match_resume 开关前后一致）===")
    jd_parse = parse_jd(JD)
    old = os.environ.get("RAG_ENABLED")
    os.environ["RAG_ENABLED"] = "0"
    m_off = match_resume(jd_parse, RESUME)
    os.environ["RAG_ENABLED"] = "1"
    m_on = match_resume(jd_parse, RESUME)
    if old is None:
        os.environ.pop("RAG_ENABLED", None)
    else:
        os.environ["RAG_ENABLED"] = old

    def _strip(m):
        d = dict(m or {})
        for k in ("latency_ms", "duration_ms", "elapsed_ms"):
            d.pop(k, None)
        return d

    same = _strip(m_off) == _strip(m_on)
    print("  完整匹配结果一致=%s（score=%s / matched=%s / missing=%s） %s" % (
        same, m_on.get("score") or m_on.get("match_score"),
        m_on.get("matched_skills"), m_on.get("missing_skills"), "✔" if same else "✘"))
    print("  E 结果: %s" % ("PASS" if same else "FAIL"))
    return same


def part_f():
    print("\n=== F. stats 诊断字段（供 R7/R8 与 trace 使用）===")
    skills = parse_jd(JD)["skills"]["required"]
    _, stats, _ = call(skills)
    need = ["rag_chars", "rag_chunk_ids", "rag_modes"]
    ok = all(k in stats for k in need)
    print("  %s %s" % ({k: stats.get(k) for k in need}, "✔" if ok else "✘"))
    print("  F 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":
    # 纪律：测试不得写库/写 Trace（与本目录其它测试一致）
    import app.database as _database
    import app.trace as _trace

    _trace.record = lambda *a, **k: None
    _database.save_history = lambda *a, **k: None

    a, b, c, d, e, f = part_a(), part_b(), part_c(), part_d(), part_e(), part_f()
    allok = all([a, b, c, d, e, f])
    print("\n总结果:", "全部通过 ✅" if allok else "存在失败 ❌")
    sys.exit(0 if allok else 1)
