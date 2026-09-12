# -*- coding: utf-8 -*-
"""
第 14 步验收：缓存命中不得串数据 / 不得污染调用方

覆盖：
  A. 旧写法的最小复现（证明 bug 真实存在）
  B. 当前实现：job_url 不互相覆盖、cache_hit 不被篡改、调用方修改返回值不污染缓存
  C. SSE 链路 _result_cache 的同类风险检查

用法：python eval/test_cache_isolation.py
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

JD = "招聘Java开发工程师，要求精通Java与SpringBoot。"
RESUME = "候选人，3年Java经验，精通Java与SpringBoot。"


def part_a():
    """旧写法的最小复现：同一个 dict 既存进缓存又返回给调用方。"""
    print("=== A. 旧写法最小复现 ===")
    cache = {}

    def old_style_call(job_url):
        if "k" in cache:                          # 命中缓存
            payload = cache["k"]                  # ← 直接拿到缓存本体
            payload["cache_hit"] = True
            payload["job_url"] = job_url
            return payload
        payload = {"cache_hit": False, "job_url": job_url}   # 首次：同一个对象
        cache["k"] = payload
        return payload

    r1 = old_style_call("https://job/A")
    r2 = old_style_call("https://job/B")
    print(f"  第一次返回的 job_url = {r1['job_url']!r}（期望 https://job/A）")
    print(f"  第二次返回的 job_url = {r2['job_url']!r}")
    print(f"  第一次返回的 cache_hit = {r1['cache_hit']}（期望 False）")
    print(f"  r1 is r2 → {r1 is r2}（同一个对象，所以第二次把第一次的结果也改了）")
    leaked = r1["job_url"] != "https://job/A" or r1["cache_hit"] is not False
    print(f"  旧写法是否串数据: {leaked}")
    return leaked      # True 表示确实存在该 bug


async def _call(jd, resume, **kw):
    return await agent.analyze_agent(jd, resume, **kw)


def part_b():
    print("\n=== B. 当前实现 ===")
    config.DEEPSEEK_API_KEY = ""        # 关 LLM，快且确定性
    agent._analyze_cache.clear()

    r1 = asyncio.run(_call(JD, RESUME, job_url="https://job/A", tenant_id="t", session_id="s"))
    r2 = asyncio.run(_call(JD, RESUME, job_url="https://job/B", tenant_id="t", session_id="s"))

    print(f"  r1: cache_hit={r1['cache_hit']}  job_url={r1['job_url']!r}")
    print(f"  r2: cache_hit={r2['cache_hit']}  job_url={r2['job_url']!r}")
    print(f"  r1 is r2 → {r1 is r2}（期望 False：不得共享同一个对象）")

    ok_url = r1["job_url"] == "https://job/A" and r2["job_url"] == "https://job/B"
    ok_hit = r1["cache_hit"] is False and r2["cache_hit"] is True
    ok_identity = r1 is not r2
    print(f"  ① 岗位链接不互相覆盖: {ok_url}")
    print(f"  ② cache_hit 不被后续请求篡改: {ok_hit}")
    print(f"  ③ 两次返回不是同一对象: {ok_identity}")

    # ③ 调用方修改返回值，不得污染缓存
    r1["recommendation"]["type"] = "被调用方篡改"
    r1["match_result"]["score"] = -1
    r3 = asyncio.run(_call(JD, RESUME, job_url="https://job/C", tenant_id="t", session_id="s"))
    ok_pollute = r3["recommendation"]["type"] != "被调用方篡改" and r3["match_result"]["score"] != -1
    print(f"  ④ 调用方篡改返回值后，再次命中缓存仍是原值: {ok_pollute}"
          f"（type={r3['recommendation']['type']}, score={r3['match_result']['score']}）")

    # ⑤ 缓存里存的是副本（缓存对象与返回值不同一）
    key = agent._cache_key(JD, RESUME, "t", "s", "hr")
    cached_payload = agent._analyze_cache[key][1]
    ok_copy = cached_payload is not r3
    print(f"  ⑤ 缓存对象与返回值不同一: {ok_copy}")

    return ok_url and ok_hit and ok_identity and ok_pollute and ok_copy


def part_c():
    print("\n=== C. SSE 链路 _result_cache 检查 ===")
    agent._result_cache.clear()

    async def collect():
        st = {}
        out = []
        async for chunk in agent.run_agent(JD, RESUME, st, "t", "s", "hr"):
            out.append(chunk)
        return st, "".join(out)

    st1, out1 = asyncio.run(collect())
    st2, out2 = asyncio.run(collect())
    st3, out3 = asyncio.run(collect())
    print(f"  第1次 cache_hit={st1.get('cache_hit')}  第2次={st2.get('cache_hit')}  第3次={st3.get('cache_hit')}")
    print(f"  三次输出是否一致: {out1 == out2 == out3}")
    print(f"  缓存条目数 = {len(agent._result_cache)}（同 key 只应 1 条）")
    # _result_cache 存的是 str 列表，命中时逐条 yield（字符串不可变，不向调用方暴露列表本体）
    segs = list(agent._result_cache.values())[0][1]
    ok = out1 == out2 == out3 and st1.get("cache_hit") is False and st2.get("cache_hit") is True
    print(f"  结论: SSE 链路缓存的是不可变字符串列表、命中时逐条 yield，"
          f"不向调用方暴露列表本体 → {'无同类风险' if ok else '需进一步检查'}")
    return ok


if __name__ == "__main__":
    database.init_db()
    database.save_history = lambda *a, **k: None     # 不污染业务库
    trace.set_enabled(False)                         # 不污染 trace 表
    a = part_a()
    b = part_b()
    c = part_c()
    print("\n总结果:", "全部通过 ✅" if (a and b and c) else "存在失败 ❌")
    print("（A 段返回 True 表示旧写法**确实**会串数据，是 bug 存在的证据，不是失败）")
    sys.exit(0 if (a and b and c) else 1)
