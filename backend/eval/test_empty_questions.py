# -*- coding: utf-8 -*-
"""
第 13 步验收：模型返回空内容时不得 500（空列表越界）

触发方式：把 AsyncOpenAI 换成"永远返回空字符串"的假客户端。
此时 generate_interview_questions(structured=True) 会走到
`[{...} for q in lines[:5]]` 且 lines 为空 → 返回 []，
原实现紧接着 questions[0] → IndexError。

覆盖：
  A. 直接调用 analyze_agent（原实现会抛 IndexError）
  B. 走 HTTP 层 /api/agent/analyze（原实现会 500）

用法：python eval/test_empty_questions.py
"""
import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import app.agent as agent              # noqa: E402
import app.config as config            # noqa: E402
import app.database as database        # noqa: E402
import app.trace as trace              # noqa: E402
from app.tools import generate_interview_questions   # noqa: E402

# 这组输入匹配度约 67%（落在 50-79），才会走 LLM 分支
JD = "招聘数据分析师，要求Python与SQL。"
RESUME = "候选人3年Python/SQL经验。"


class _Msg:
    def __init__(self, c):
        self.content = c


class _Choice:
    def __init__(self, c):
        self.message = _Msg(c)
        self.finish_reason = "stop"


class _Usage:
    total_tokens = 5
    prompt_tokens = 5
    completion_tokens = 0


class _Resp:
    def __init__(self, c):
        self.choices = [_Choice(c)]
        self.usage = _Usage()


class _FakeEmptyLLM:
    """AsyncOpenAI 替身：永远返回空内容。"""

    def __init__(self, *a, **kw):
        outer = self

        class _Completions:
            async def create(self, **kwargs):
                return _Resp("")

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def install_fake():
    import openai
    original = openai.AsyncOpenAI
    openai.AsyncOpenAI = _FakeEmptyLLM
    return original


def part_a():
    print("=== A. 直接调用 analyze_agent ===")
    # 先证明底层函数确实会返回空列表（stats 必须是完整结构，否则会走异常分支而不是 [] 分支）
    full_stats = {"trace_id": "", "task_id": "", "llm_call_count": 0, "llm_used": False,
                  "total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0}
    raw = asyncio.run(generate_interview_questions(JD, RESUME, full_stats, structured=True))
    print(f"  generate_interview_questions(structured=True) 返回 = {raw!r}")
    print(f"  → 是否空列表: {raw == []}（空列表正是越界来源）")

    # 证明"修复前的写法"会崩
    try:
        _ = [][0].get("question", "")      # 等价于原实现 questions[0].get(...)
        print("  修复前写法：未抛异常（不应发生）")
    except IndexError as e:
        print(f"  修复前写法：questions[0] → IndexError: {e}   ← 原实现会让整个请求 500")

    # 修复后的实际行为
    config.DEEPSEEK_API_KEY = "fake-key"
    agent._analyze_cache.clear()
    try:
        r = asyncio.run(agent.analyze_agent(JD, RESUME, tenant_id="t", session_id="s"))
        qs = r["interview_questions"]
        ok = isinstance(qs, list) and len(qs) == 1 and isinstance(qs[0], dict) and bool(qs[0].get("question"))
        print(f"  修复后：分数={r['match_result']['score']}  结论={r['recommendation']['type']}  "
              f"面试题条数={len(qs)}")
        print(f"  占位题目 = {qs[0]['question']}")
        print(f"  llm_calls={r['llm_calls']}（其中 1 次来自结论节点——该节点确实调用了假 LLM；"
              f"面试题节点的失败未被计为成功调用）")
        print(f"  A 结果: {'PASS' if ok else 'FAIL'}")
        return ok
    except Exception as e:
        print(f"  修复后仍抛异常: {type(e).__name__}: {e}")
        print("  A 结果: FAIL")
        return False


def part_b():
    print("\n=== B. HTTP 层 /api/agent/analyze ===")
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    resp = client.post("/api/agent/analyze",
                       json={"jd": JD, "resume": RESUME, "tenant_id": "t", "session_id": "s"})
    ok = resp.status_code == 200
    body = resp.json() if ok else {}
    print(f"  HTTP 状态 = {resp.status_code}（原实现此处为 500）")
    if ok:
        print(f"  面试题条数 = {len(body.get('interview_questions', []))}")
        print(f"  首题 = {body['interview_questions'][0]['question']}")
    else:
        print(f"  响应 = {body}")
    print(f"  B 结果: {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    database.init_db()
    database.save_history = lambda *a, **k: None     # 不污染业务库
    database.upsert_ask_session = lambda *a, **k: None   # A1/A4：测试不写追问会话状态
    trace.set_enabled(False)                         # 不污染 trace 表
    original = install_fake()
    try:
        a = part_a()
        b = part_b()
    finally:
        import openai
        openai.AsyncOpenAI = original
        config.DEEPSEEK_API_KEY = ""
    print("\n总结果:", "全部通过 ✅" if (a and b) else "存在失败 ❌")
    sys.exit(0 if (a and b) else 1)
