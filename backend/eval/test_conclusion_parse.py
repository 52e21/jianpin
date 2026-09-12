# -*- coding: utf-8 -*-
"""
第 12 步验收：结论枚举解析不得反转

两部分：
  A. parse_conclusion 单元测试（含"修复前的旧逻辑会返回什么"的对照）
  B. 端到端：用假 LLM 客户端让 summarize_recommendation 收到「结论：不推荐」，
     断言整条链路输出 "不推荐"（对应执行书验收：输入"结论：不推荐"，输出"不推荐"）

用法：python eval/test_conclusion_parse.py
"""
import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import app.config as config            # noqa: E402
import app.database as database        # noqa: E402
import app.trace as trace              # noqa: E402
from app.tools import parse_conclusion, summarize_recommendation   # noqa: E402


def legacy_parse(content: str) -> str:
    """修复前的旧实现（仅用于对照，证明 bug 真实存在）。"""
    conclusion = "待定"
    for c in ("推荐", "不推荐", "待定"):
        if c in (content or "")[:60]:
            conclusion = c
            break
    return conclusion


CASES = [
    ("结论：不推荐\n理由：核心技能缺失", "不推荐", "★原 bug 用例"),
    ("结论：推荐\n理由：核心要求全覆盖", "推荐", ""),
    ("结论：待定\n理由：需结合面试评估", "待定", ""),
    ("不推荐", "不推荐", "无标签"),
    ("推荐", "推荐", "无标签"),
    ("我认为应当不推荐，因为差距较大", "不推荐", "句中出现顺序相反"),
    ("该候选人非常推荐", "推荐", ""),
    ("", "待定", "空输入兜底"),
    ("结论：待定。", "待定", "结尾带句号"),
    ("**结论：不推荐**", "不推荐", "Markdown 加粗"),
    ("结论：推荐\n理由：虽然部分技能缺失，但不推荐的理由并不充分", "推荐", "理由里出现「不推荐」"),
    ("这家公司不值得推荐", "推荐", "极端：语义歧义，按词形收敛"),
]


def part_a():
    print("=== A. parse_conclusion 单元测试 ===")
    print(f"{'输入':<44}{'期望':<7}{'实际':<7}{'旧逻辑':<7}结果")
    print("-" * 92)
    ok = True
    for text, expect, note in CASES:
        got = parse_conclusion(text)
        old = legacy_parse(text)
        good = got == expect
        ok &= good
        shown = text.replace("\n", "\\n")[:42]
        print(f"{shown:<44}{expect:<7}{got:<7}{old:<7}{'OK' if good else 'FAIL'} {note}")
    regressions = [(t, e, legacy_parse(t)) for t, e, _ in CASES if legacy_parse(t) != e]
    print(f"\n旧逻辑在 {len(regressions)} 个用例上是错的：")
    for t, e, o in regressions:
        print(f"   输入={t.replace(chr(10),'\\n')[:40]!r} 应为 {e}，旧逻辑给 {o}")
    return ok


# ---------------- B. 端到端（假 LLM） ----------------
class _Msg:
    def __init__(self, c):
        self.content = c


class _Choice:
    def __init__(self, c):
        self.message = _Msg(c)
        self.finish_reason = "stop"


class _Usage:
    total_tokens = 12
    prompt_tokens = 10
    completion_tokens = 2


class _Resp:
    def __init__(self, c):
        self.choices = [_Choice(c)]
        self.usage = _Usage()


class _FakeClient:
    """AsyncOpenAI 的替身：create() 永远返回固定的模型输出。"""

    def __init__(self, content):
        self._content = content
        outer = self

        class _Completions:
            async def create(self, **kwargs):
                return _Resp(outer._content)

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def part_b():
    print("\n=== B. 端到端：假 LLM 返回「结论：不推荐」 ===")
    import openai

    original = openai.AsyncOpenAI
    openai.AsyncOpenAI = lambda **kwargs: _FakeClient("结论：不推荐\n理由：核心技能缺失，不建议推进。")
    try:
        config.DEEPSEEK_API_KEY = "fake-key-for-test"
        trace.set_enabled(False)
        database.save_history = lambda *a, **k: None
        stats = {"trace_id": "", "task_id": "", "llm_call_count": 0, "llm_used": False,
                 "total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0}
        # 分数落在 50–79 才会走 LLM 分支
        rec = asyncio.run(summarize_recommendation(67, ["Python"], ["数据分析"], ["Q1", "Q2"], stats))
        got = rec["conclusion"]
        ok = got == "不推荐" and rec.get("llm_used") is True
        print(f"  匹配度 67%（中间区间）→ 调用 LLM → 结论 = {got!r}   llm_used={rec.get('llm_used')}")
        print(f"  理由 = {rec['reason'][:40]}")
        print(f"  验收（输入'结论：不推荐' → 输出'不推荐'）: {'PASS' if ok else 'FAIL'}")
        return ok
    finally:
        openai.AsyncOpenAI = original
        config.DEEPSEEK_API_KEY = ""


if __name__ == "__main__":
    a = part_a()
    b = part_b()
    print("\n总结果:", "全部通过 ✅" if (a and b) else "存在失败 ❌")
    sys.exit(0 if (a and b) else 1)
