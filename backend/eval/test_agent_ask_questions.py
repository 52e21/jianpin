# -*- coding: utf-8 -*-
"""
A3 验收：追问生成（1–3 个，规则优先、零 LLM）

覆盖：
  A. 数量与去重：1–3 条、互不重复
  B. 字段映射：必须技能 / 经验年限 / 学历 / 职责 各自映射到对应问法
  C. 优先级与上限：四项全缺时取前 3（技能→经验→学历），limit 参数生效
  D. 信息充足 → 不生成任何追问
  E. 具体性：能识别岗位名时问题里带上岗位名；识别不出时不出现 None/空括号
  F. 真实数据：评测集中判不足的 6 条 JD 各生成 1–3 条可回答的追问

用法：python eval/test_agent_ask_questions.py
"""
import io
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.ask import MAX_QUESTIONS, generate_questions, ask_for   # noqa: E402
from app.tools import parse_jd                                   # noqa: E402

EVAL = Path(__file__).resolve().parent
ALL_MISSING = ["required_skills", "experience_years", "education_level", "responsibilities"]


def part_a():
    print("=== A. 数量与去重 ===")
    ok = True
    for missing in ([], ["required_skills"], ALL_MISSING, ["education_level", "responsibilities"]):
        qs = generate_questions({"status": "insufficient", "missing_fields": missing})
        n_ok = (0 <= len(qs) <= MAX_QUESTIONS)
        uniq = len(qs) == len(set(qs))
        nonempty = all(q.strip() for q in qs)
        good = n_ok and uniq and nonempty
        ok &= good
        print("  missing=%-58s -> %d 条, 去重=%s %s" % (
            ",".join(missing) or "(无)", len(qs), uniq, "✔" if good else "✘"))
    print("  A 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_b():
    print("\n=== B. 字段 → 问法映射 ===")
    expect = {
        "required_skills": "必须技能",
        "experience_years": "几年相关经验",
        "education_level": "学历要求",
        "responsibilities": "主要负责",
    }
    ok = True
    for field, kw in expect.items():
        qs = generate_questions({"status": "insufficient", "missing_fields": [field]})
        good = len(qs) == 1 and kw in qs[0]
        ok &= good
        print("  %-20s -> %-58s %s" % (field, qs[0] if qs else "(空)", "✔" if good else "✘"))
    print("  B 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_c():
    print("\n=== C. 优先级与上限 ===")
    qs = generate_questions({"status": "insufficient", "missing_fields": ALL_MISSING})
    order = [q[:2] for q in qs]
    ok = len(qs) == MAX_QUESTIONS
    print("  全缺 → %d 条（上限 %d）%s" % (len(qs), MAX_QUESTIONS, "✔" if ok else "✘"))
    print("  前 3 条覆盖技能/经验/学历: %s" % all(
        kw in "".join(qs) for kw in ("必须技能", "几年相关经验", "学历要求")))
    ok &= all(kw in "".join(qs) for kw in ("必须技能", "几年相关经验", "学历要求"))
    q1 = generate_questions({"status": "insufficient", "missing_fields": ALL_MISSING}, limit=1)
    lim_ok = len(q1) == 1 and "必须技能" in q1[0]
    print("  limit=1 → %d 条（且取最高优先级）%s" % (len(q1), "✔" if lim_ok else "✘"))
    ok &= lim_ok
    print("  C 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_d():
    print("\n=== D. 信息充足不追问 ===")
    qs = generate_questions({"status": "sufficient", "missing_fields": []})
    r = ask_for("招聘 Java 后端工程师。职责：负责交易系统开发。"
                "要求：精通 Java、Spring Boot，3 年以上经验，本科及以上学历。")
    ok = qs == [] and r["status"] == "sufficient" and r["questions"] == []
    print("  直接调用: %s；ask_for: status=%s questions=%s %s" % (
        qs, r["status"], r["questions"], "✔" if ok else "✘"))
    print("  D 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_e():
    print("\n=== E. 具体性（带岗位名）===")
    r1 = ask_for("招聘后端工程师")
    r2 = ask_for("")
    named = any("「后端工程师」" in q for q in r1["questions"])
    unnamed_clean = all("「" not in q and "None" not in q for q in r2["questions"])
    ok = named and unnamed_clean and len(r1["questions"]) > 0 and len(r2["questions"]) > 0
    print("  识别出岗位名: %s -> %s" % (named, r1["questions"][:1]))
    print("  识别不出时不带空岗位名: %s -> %s" % (unnamed_clean, r2["questions"][:1]))
    print("  E 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


def part_f():
    print("\n=== F. 真实数据：评测集 6 条不足 JD 的追问 ===")
    rows = []
    for line in io.open(EVAL / "eval_set_v1_1.jsonl", encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        c = json.loads(line)
        r = ask_for(c["jd"])
        if r["status"] == "insufficient":
            rows.append((c["id"], c["jd"], r["questions"]))
    ok = len(rows) == 6 and all(1 <= len(q) <= MAX_QUESTIONS for _, _, q in rows)
    print("  判不足 %d 条（期望 6），每条追问数在 1-%d 之间: %s" % (
        len(rows), MAX_QUESTIONS, "✔" if ok else "✘"))
    for cid, jd, qs in rows:
        print("    %-6s %s" % (cid, (jd or "(空 JD)")[:34]))
        for q in qs:
            print("           - %s" % q)
    print("  F 结果: %s" % ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":
    a, b, c, d, e, f = part_a(), part_b(), part_c(), part_d(), part_e(), part_f()
    allok = all([a, b, c, d, e, f])
    print("\n总结果:", "全部通过 ✅" if allok else "存在失败 ❌")
    sys.exit(0 if allok else 1)
