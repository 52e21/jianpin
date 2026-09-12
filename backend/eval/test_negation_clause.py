# -*- coding: utf-8 -*-
"""
事项 3 复核修复验收：否定窗口必须按小句截断

背景：原实现取技能前后各 12 字符找否定词、**会跨过标点**，于是
      "精通 Java 与 Spring Boot，不熟悉 MySQL" 里的 Spring Boot
      被邻居的"不熟悉"误伤 → 本应命中的技能被判缺失。

覆盖：
  A. 邻居否定不再误伤（正向技能仍命中）
  B. 真实否定仍然生效（相邻否定、跨标点的否定）
  C. 端到端：E041 场景分数与命中集
  D. 200 条评测集差异 + 与模拟结果核对

用法：python eval/test_negation_clause.py
"""
import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import app.agent as agent          # noqa: E402
import app.config as config        # noqa: E402
import app.database as database    # noqa: E402
import app.trace as trace          # noqa: E402
from app.tools import _contains_skill, match_resume, parse_jd   # noqa: E402
from eval_registry import ALLOWED_REGRESSIONS   # noqa: E402

EVAL = Path(__file__).resolve().parent


def part_a():
    print("=== A. 邻居否定不再误伤（正向技能仍命中）===")
    cases = [
        ("候选人，3年经验，精通 Java 与 Spring Boot，不熟悉 MySQL。", "Spring Boot"),
        ("精通Redis，未使用过Kafka，具备良好的学习能力。", "Redis"),
        ("精通消息队列，不了解PyTorch，具备良好的学习能力。", "消息队列"),
        ("精通项目管理，未使用过爬虫，具备良好的学习能力。", "项目管理"),
    ]
    ok = True
    for text, skill in cases:
        got = _contains_skill(text, skill)
        ok &= got
        print(f"  {'OK  ' if got else 'FAIL'} {skill!r} 在 {text[:34]!r} 应命中 = {got}")
    return ok


def part_b():
    print("\n=== B. 真实否定仍然生效 ===")
    cases = [
        ("候选人，3年经验，精通 Java 与 Spring Boot，不熟悉 MySQL。", "MySQL"),
        ("精通Redis，未使用过Kafka，具备良好的学习能力。", "Kafka"),
        ("不会 React，TypeScript 不熟悉。", "React"),
        ("不会 React，TypeScript 不熟悉。", "TypeScript"),
        ("不会 k8s", "Kubernetes"),
        ("未使用过 Redis，仅了解消息队列概念。", "Redis"),
        ("从未接触 Kubernetes，Docker 在学。", "Kubernetes"),
        ("不了解 SQL，只会用 Excel 做透视表。", "SQL"),
    ]
    ok = True
    for text, skill in cases:
        got = _contains_skill(text, skill)
        ok &= got is False
        print(f"  {'OK  ' if got is False else 'FAIL'} {skill!r} 在 {text[:34]!r} 不得命中 = {got}")
    return ok


def part_c():
    print("\n=== C. 端到端：E041 场景 ===")
    p = parse_jd("招聘后端工程师，要求 Java、Spring Boot、MySQL 三项技能。")
    mr = match_resume(p, "候选人，3年经验，精通 Java 与 Spring Boot，不熟悉 MySQL。")
    ok = (mr["match_score"] == 67 and "Spring Boot" in mr["matched_skills"]
          and mr["missing_skills"] == ["MySQL"])
    print(f"  分数={mr['match_score']}（修复前 33，期望 67）")
    print(f"  命中={mr['matched_skills']}  缺失={mr['missing_skills']}")
    print(f"  C 结果: {'PASS' if ok else 'FAIL'}")
    return ok


def part_d():
    print("\n=== D. 200 条评测集差异 ===")
    cases = [json.loads(l) for l in (EVAL / "eval_set_v1.jsonl").open(encoding="utf-8") if l.strip()]
    base = {c["id"]: c["pred_conclusion"] for c in
            json.load((EVAL / "baseline.json").open(encoding="utf-8"))["cases"]}
    gt = {c["id"]: c["gt"]["conclusion"] for c in cases}

    config.DEEPSEEK_API_KEY = ""
    trace.set_enabled(False)
    preds = {}
    for c in cases:
        agent._analyze_cache.clear()
        r = asyncio.run(agent.analyze_agent(c["jd"], c["resume"], tenant_id="t", session_id="s"))
        preds[c["id"]] = r["recommendation"]["type"]

    oa = sum(1 for i in gt if base.get(i) == gt[i])
    na = sum(1 for i in gt if preds.get(i) == gt[i])
    fixed = [i for i in gt if base.get(i) != gt[i] and preds.get(i) == gt[i]]
    broke = [i for i in gt if base.get(i) == gt[i] and preds.get(i) != gt[i]]
    unregistered = [i for i in broke if i not in ALLOWED_REGRESSIONS]
    print(f"  一致率: 基线 {oa}/200={oa/2:.1f}%  →  现在 {na}/200={na/2:.1f}%")
    print(f"  变一致 {len(fixed)} 条: {fixed}")
    print(f"  变不一致 {len(broke)} 条: {broke}（已登记项：{sorted(ALLOWED_REGRESSIONS)}）")
    print(f"  未登记回归: {unregistered if unregistered else '无 ✔'}")
    ok = (na >= 141) and not unregistered
    print(f"\n  D 结果: {'PASS' if ok else 'FAIL'}（期望一致率 ≥141/200，与模拟结果吻合）")
    return ok


if __name__ == "__main__":
    database.init_db()
    database.save_history = lambda *a, **k: None
    database.upsert_ask_session = lambda *a, **k: None   # A1/A4：测试不写追问会话状态
    a, b, c, d = part_a(), part_b(), part_c(), part_d()
    print("\n总结果:", "全部通过 ✅" if all([a, b, c, d]) else "存在失败 ❌")
    sys.exit(0 if all([a, b, c, d]) else 1)
