# -*- coding: utf-8 -*-
"""
修复②验收：llm_calls 计数必须反映"真的调了几次 LLM"

修复前的两个不一致（同一个"用返回文本前缀去猜"的设计缺陷）：
  · 无 Key 时：占位文案不带全角括号 → 前缀哨兵匹配失败 → 没调 LLM 却计 1 次
    （评测跑批 v2 基线里 170/200 条如此）
  · 反向：模型已响应（token 已计）但后续解析失败 → 返回"（错误…）"占位 →
    前缀匹配成功 → 不计调用 → 出现 tokens>0 而 llm_calls=0
    （真实库 execution_history 里有 4 行这种数据）

修复后必须满足的不变量：**tokens>0 ⟺ llm_calls>0**

验收用例（对应执行书要求）：
  A 无 Key           → llm_calls=0, tokens=0
  B 正常走 LLM       → llm_calls∈{1,2}, tokens>0
  C 规则短路(<50)    → llm_calls=0, tokens=0
  D 不变量：混合运行下每条都满足 tokens>0 ⟺ llm_calls>0
  E 源码中不再存在"用哨兵前缀给 llm_calls 计数"的写法

用法：python eval/test_llm_calls_count.py
"""
import asyncio
import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
FRONTEND = BACKEND.parent / "frontend"
sys.path.insert(0, str(BACKEND))

import app.agent as agent          # noqa: E402
import app.config as config        # noqa: E402
import app.database as database    # noqa: E402
import app.trace as trace          # noqa: E402

JD_HIGH = "招聘Java开发工程师，要求精通Java与SpringBoot。"
RESUME_HIGH = "候选人，3年Java经验，精通Java与SpringBoot。"
JD_MID = "招聘数据分析师，要求Python与SQL。"
RESUME_MID = "候选人3年Python/SQL经验。"
JD_LOW = "招聘前端工程师，要求精通React和TypeScript。"
RESUME_LOW = "候选人只用Vue，不会React。"

QUESTIONS_JSON = json.dumps([{
    "category": "技术能力", "difficulty": "中级",
    "question": "请说明 JVM 内存模型与 GC 触发条件。",
    "answer_points": ["堆分区", "GC Roots", "分代回收"],
    "scoring_criteria": "说出核心机制 70%，结合实际案例 100%",
}], ensure_ascii=False)


class _Msg:
    def __init__(self, c):
        self.content = c


class _Choice:
    def __init__(self, c):
        self.message = _Msg(c)
        self.finish_reason = "stop"


class _Usage:
    total_tokens = 120
    prompt_tokens = 100
    completion_tokens = 20


class _Resp:
    def __init__(self, c):
        self.choices = [_Choice(c)]
        self.usage = _Usage()


class _FakeLLM:
    """按 prompt 内容返回不同结果，模拟"两个节点都真的调了 LLM"。"""

    def __init__(self, *a, **kw):
        outer = self

        class _Completions:
            async def create(self, **kwargs):
                prompt = kwargs.get("messages", [{}])[0].get("content", "")
                if "面试官" in prompt:              # 面试题节点
                    return _Resp(QUESTIONS_JSON)
                return _Resp("结论：待定\n理由：需结合面试进一步评估。")   # 结论节点

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def run(jd, resume, tag):
    agent._analyze_cache.clear()
    r = asyncio.run(agent.analyze_agent(jd, resume, tenant_id="t", session_id=tag))
    return r["llm_calls"], r["total_tokens"], r["recommendation"]["type"]


def main():
    database.init_db()
    database.save_history = lambda *a, **k: None
    database.upsert_ask_session = lambda *a, **k: None   # A1/A4：测试不写追问会话状态
    trace.set_enabled(False)
    ok = True
    results = []

    print("=== A. 无 Key ===")
    config.DEEPSEEK_API_KEY = ""
    for jd, rv, tag in ((JD_HIGH, RESUME_HIGH, "a1"), (JD_MID, RESUME_MID, "a2"), (JD_LOW, RESUME_LOW, "a3")):
        lc, tk, concl = run(jd, rv, tag)
        results.append((f"A/{tag}", lc, tk))
        good = lc == 0 and tk == 0
        ok &= good
        print(f"  {'OK  ' if good else 'FAIL'} {tag}: llm_calls={lc} tokens={tk} 结论={concl}（期望 0/0）")

    print("\n=== B. 正常走 LLM（假客户端）===")
    import openai
    original = openai.AsyncOpenAI
    openai.AsyncOpenAI = _FakeLLM
    try:
        config.DEEPSEEK_API_KEY = "fake-key"
        for jd, rv, tag in ((JD_HIGH, RESUME_HIGH, "b1"), (JD_MID, RESUME_MID, "b2")):
            lc, tk, concl = run(jd, rv, tag)
            results.append((f"B/{tag}", lc, tk))
            good = lc in (1, 2) and tk > 0
            ok &= good
            print(f"  {'OK  ' if good else 'FAIL'} {tag}: llm_calls={lc} tokens={tk} 结论={concl}"
                  f"（期望 1 或 2 次且 tokens>0）")
    finally:
        openai.AsyncOpenAI = original

    print("\n=== C. 规则短路（score<50）===")
    config.DEEPSEEK_API_KEY = "fake-key"       # 有 Key 也不该被调用
    openai.AsyncOpenAI = _FakeLLM
    try:
        lc, tk, concl = run(JD_LOW, RESUME_LOW, "c1")
        results.append(("C/c1", lc, tk))
        good = lc == 0 and tk == 0
        ok &= good
        print(f"  {'OK  ' if good else 'FAIL'} c1: llm_calls={lc} tokens={tk} 结论={concl}"
              f"（期望 0/0：低分短路不调 LLM）")
    finally:
        openai.AsyncOpenAI = original
        config.DEEPSEEK_API_KEY = ""

    print("\n=== D. 不变量：tokens>0 ⟺ llm_calls>0 ===")
    bad = [(t, lc, tk) for t, lc, tk in results
           if (tk > 0) != (lc > 0)]
    print(f"  违反不变量的用例: {bad if bad else '无 ✔'}")
    ok &= not bad

    print("\n=== E. 源码中不得再用哨兵前缀给 llm_calls 计数 ===")
    src = (BACKEND / "app" / "agent.py").read_text(encoding="utf-8")
    hits = [ln.strip() for ln in src.splitlines()
            if "llm_call_count" in ln and ("startswith" in ln or "未配置" in ln)]
    print(f"  可疑写法: {hits if hits else '无 ✔'}")
    ok &= not hits
    # 确认计数改为读标志
    uses_flag = "questions_llm_called" in src
    print(f"  {'OK  ' if uses_flag else 'FAIL'} 已改为读取节点回报的标志 questions_llm_called")
    ok &= uses_flag

    print("\n总结果:", "全部通过 ✅" if ok else "存在失败 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
