# -*- coding: utf-8 -*-
"""
接口契约用例集执行器（E051 从"结论一致率"搬到这里的落点）

背景：E051（空 JD）原标"不推荐"无依据——管线并未判定为不推荐，只是没有可评分维度。
      而空 JD 在**接口层**已被 /api/agent/analyze 拦截返回 400，属于**接口契约**。
      评测脚本直接调编排函数、绕过了接口校验，等于用编排层的兜底行为去衡量接口层该负责的事 —— 测错了层。
      因此：契约类断言在本文件用 TestClient 执行；E051 只在评测集里保留一条
      "编排层对空 JD 不崩"的边界记录，并标 exclude_from_agreement。

用法：python eval/test_contract_set.py
"""
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import app.database as database    # noqa: E402
import app.trace as trace          # noqa: E402
from app.main import app           # noqa: E402

EVAL = Path(__file__).resolve().parent

try:
    from fastapi.testclient import TestClient
except Exception as e:             # pragma: no cover
    print("无法导入 TestClient:", e)
    sys.exit(2)


def main():
    database.init_db()
    trace.set_enabled(False)
    database.save_history = lambda *a, **k: None     # 契约用例不落业务库
    client = TestClient(app)

    cases = [json.loads(l) for l in
             (EVAL / "contract_set_v1.jsonl").open(encoding="utf-8") if l.strip()]
    ok = True
    print(f"接口契约用例集：{len(cases)} 条\n")
    for c in cases:
        r = client.request(c["method"], c["endpoint"], json=c["payload"])
        detail = ""
        try:
            detail = str(r.json().get("detail", ""))
        except Exception:
            pass
        good = (r.status_code == c["expect_status"]
                and c["expect_detail_contains"] in detail)
        ok &= good
        print(f"  {'OK  ' if good else 'FAIL'} {c['id']} {c['method']} {c['endpoint']}")
        print(f"        期望 {c['expect_status']} 且 detail 含「{c['expect_detail_contains']}」"
              f" → 实际 {r.status_code} / {detail[:40]}")
        print(f"        {c['note']}")

    # 附带验证：编排层对空 JD 不会崩（边界行为本身仍要保证）
    print("\n  边界行为（不计入一致率）：编排层对空 JD 不崩")
    import asyncio
    import app.agent as agent
    import app.config as config
    config.DEEPSEEK_API_KEY = ""
    agent._analyze_cache.clear()
    try:
        r = asyncio.run(agent.analyze_agent("", "候选人，3年经验，精通 Java。",
                                            tenant_id="t", session_id="contract"))
        boundary_ok = r["recommendation"]["type"] in ("待定", "不推荐", "推荐")
        print(f"    {'OK  ' if boundary_ok else 'FAIL'} 返回结论={r['recommendation']['type']}"
              f"（不抛异常即可）")
        ok &= boundary_ok
    except Exception as e:
        print(f"    FAIL 抛出异常: {type(e).__name__}: {e}")
        ok = False

    print("\n总结果:", "全部通过 ✅" if ok else "存在失败 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
