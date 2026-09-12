# -*- coding: utf-8 -*-
"""
事项 2 验收：技能名匹配加词边界

覆盖：
  A. 子串不再误命中（JavaScript/Java、Django/go、MySQL/SQL）
  B. 含符号技能名不被边界打断（C++ / C# / Node.js / Vue.js / A/B测试）
  C. 否定语境仍生效
  D. JD 侧子串去重收紧（Java 与 JavaScript 各自保留；Spring 仍被 Spring Boot 吸收）
  E. 200 条评测集差异，并把三类"变不一致"分开登记：
       - 标注口径待复核（事项 3 处理）
       - 别名写法缺口（待与用户确认批次）
       - 词表覆盖不足（已登记，业务决定）

用法：python eval/test_skill_boundary.py
"""
import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import app.agent as agent              # noqa: E402
import app.config as config            # noqa: E402
import app.database as database        # noqa: E402
import app.trace as trace              # noqa: E402
from app.tools import _contains_skill, parse_jd, match_resume   # noqa: E402
from eval_registry import (KNOWN_LABEL_ISSUES, PENDING_ALIAS,   # noqa: E402
                           KNOWN_DICT_GAPS, ALLOWED_REGRESSIONS)

EVAL = Path(__file__).resolve().parent


def part_a():
    print("=== A. 子串不再误命中（核心验收）===")
    cases = [
        ("精通 JavaScript 与 TypeScript", "Java", False, "JavaScript 不得命中 Java"),
        ("使用 Django 开发后端", "Go", False, "Django 不得命中 go"),
        ("长期使用 MySQL", "SQL", False, "MySQL 不得命中 SQL"),
        ("精通 PostgreSQL", "SQL", False, "PostgreSQL 不得命中 SQL"),
    ]
    ok = True
    for text, skill, expect, desc in cases:
        got = _contains_skill(text, skill)
        ok &= got == expect
        print(f"  {'OK  ' if got == expect else 'FAIL'} {desc:<30} = {got}")
    return ok


def part_b():
    print("\n=== B. 含符号技能名不被边界打断（回归保护）===")
    cases = [
        ("精通 Java 开发", "Java", True),
        ("精通 Go 语言", "Go", True),
        ("熟悉 C++11 标准", "C++", True),
        ("精通 C#", "C#", True),
        ("使用 Node.js 开发", "Node.js", True),
        ("熟悉 Vue.js", "Vue", True),
        ("用 Spring Boot 开发", "Spring", True),
        ("做 A/B测试", "A/B测试", True),
        ("精通 k8s 集群运维", "Kubernetes", True),
    ]
    ok = True
    for text, skill, expect in cases:
        got = _contains_skill(text, skill)
        ok &= got == expect
        print(f"  {'OK  ' if got == expect else 'FAIL'} {text!r} 命中 {skill!r} = {got}")
    return ok


def part_c():
    print("\n=== C. 否定语境仍生效 ===")
    cases = [("不会 k8s", "Kubernetes", False), ("不熟悉 JavaScript", "React", False),
             ("精通 Java", "Java", True)]
    ok = True
    for text, skill, expect in cases:
        got = _contains_skill(text, skill)
        ok &= got == expect
        print(f"  {'OK  ' if got == expect else 'FAIL'} {text!r} / {skill!r} = {got}")
    return ok


def part_d():
    print("\n=== D. JD 侧子串去重收紧 ===")
    print("  （原规则：短名是长名子串就丢弃 → 会把 Java 当成 JavaScript 的冗余而误删）")
    checks = [
        ("招聘前端工程师，要求精通 Java，熟悉 JavaScript 优先。", {"Java", "JavaScript"},
         "Java 有独立出现 → 两者都保留"),
        ("招聘后端工程师，精通 Spring Boot 与 MySQL。", {"Spring Boot", "MySQL"},
         "Spring 被 Spring Boot 吸收；SQL 被 MySQL 吸收"),
    ]
    ok = True
    for jd, expect, desc in checks:
        p = parse_jd(jd)
        got = set(p["skills"]["required"]) | set(p["skills"]["preferred"])
        good = got == expect
        ok &= good
        print(f"  {'OK  ' if good else 'FAIL'} {desc}")
        print(f"       required={p['skills']['required']} preferred={p['skills']['preferred']}（期望集合 {sorted(expect)}）")
    # 端到端：JavaScript 不该救活 Java 的匹配
    p = parse_jd("招聘前端工程师，要求精通 Java。")
    mr = match_resume(p, "候选人，3年前端经验，精通 JavaScript 与 TypeScript。")
    e2e = mr["match_score"] == 0
    ok &= e2e
    print(f"  {'OK  ' if e2e else 'FAIL'} 端到端：JavaScript 不命中 Java → 分数={mr['match_score']}（期望 0）")
    return ok


def part_e():
    print("\n=== E. 200 条评测集差异 ===")
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
    print(f"\n  【本次修复变一致】{len(fixed)} 条: {fixed}")
    print(f"  【变不一致】{len(broke)} 条，按类别登记：")
    for i in broke:
        c = next(x for x in cases if x["id"] == i)
        if i in KNOWN_LABEL_ISSUES:
            kind = "标注口径待复核（事项 3）"
        elif i in PENDING_ALIAS:
            kind = "别名写法缺口（待确认批次）"
        else:
            kind = "词表覆盖不足（业务决定）"
        print(f"    {i}: {base.get(i)}→{preds.get(i)}（期望 {gt[i]}）  【{kind}】 JD={c['jd'][:30]!r}")
    print(f"\n  【未登记的回归（必须为空）】: {unregistered if unregistered else '无 ✔'}")
    print(f"\n  E 结果: {'PASS' if not unregistered else 'FAIL'}")
    return not unregistered


if __name__ == "__main__":
    database.init_db()
    database.save_history = lambda *a, **k: None
    database.upsert_ask_session = lambda *a, **k: None   # A1/A4：测试不写追问会话状态
    a, b, c, d, e = part_a(), part_b(), part_c(), part_d(), part_e()
    print("\n总结果:", "全部通过 ✅" if all([a, b, c, d, e]) else "存在失败 ❌")
    sys.exit(0 if all([a, b, c, d, e]) else 1)
