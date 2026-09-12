# -*- coding: utf-8 -*-
"""Agent 子模块（A2–A5）：JD 信息充分性判定 + 追问状态机。

插入点（执行书第二部分）：`parse_jd` 之后、`match_resume` 之前的分支：

    parse_jd
       ↓
    [Agent 子模块]
       ├─ 信息充足 → 继续主链路（现状不变）
       └─ 信息不足 → 生成追问返回（A3）→ HR 补充后重走 parse_jd 之后的链路（A4），最多 2 轮（A5）

本模块只做**判定与状态推演**（纯函数、零 LLM），不替换主链路；
是否提前返回追问由编排层决定，判定为 sufficient 时行为与加 Agent 之前完全一致。
"""
from __future__ import annotations

import re

# 判定口径（执行书 A2）：required_skills 为空，或"缺失字段 ≥ 2" → insufficient
REQUIRED_SKILLS_FIELD = "required_skills"
OPTIONAL_FIELDS = ("responsibilities", "experience_years", "education_level")
MAX_MISSING_FIELDS = 2
ROUND_LIMIT = 2          # A5：最多追问 2 轮，超出走"待定"

# 校准补充：JD 里"技能性表述"（要求/熟悉/精通…）——用于区分
#   「JD 没提技能」 vs 「我们的技能词表没覆盖」
# 依据（200 条评测集校准）：按字面规则会把 7/200 判为不足，其中 E056
# （"招聘测试工程师，要求熟悉自动化测试与 Selenium，了解 JMeter"）明显写了技能，
# 只是词表缺 Selenium/JMeter/自动化测试 → 误追问。加上该信号后可消歧。
SKILL_PHRASE_RE = re.compile(r"(要求|熟悉|精通|掌握|了解|会用|具备|至少|擅长)[^。；;，,]{1,24}")


def _present(value) -> bool:
    """字段是否"给到了"（None / 空串 / 空列表都算缺失）。"""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def signals(jd_parse: dict, jd_text: str = "") -> dict:
    """把 JD 解析结果折算成"信息是否给到"的信号（便于解释、校准与测试）。

    `jd_text` 可选：传了才能算 `skill_phrase`（技能性表述），否则按"无表述"处理。
    """
    jd = jd_parse or {}
    skills = jd.get("skills") or {}
    exp = jd.get("experience") or {}
    edu = jd.get("education") or {}
    phrase = SKILL_PHRASE_RE.search(jd_text or "")
    return {
        "required_skills": list(skills.get("required") or []),
        "responsibilities": list(jd.get("responsibilities") or []),
        "experience_years": exp.get("min_years"),
        "education_level": edu.get("level") or "",
        "skill_phrase": phrase.group(0) if phrase else "",
    }


def sufficiency(jd_parse: dict, jd_text: str = "") -> dict:
    """判定 JD 信息是否充足（纯函数，零 LLM）。

    规则（经 200 条评测集校准）：
      1) 技能信号：词表命中 required_skills **或** 出现技能性表述（要求/熟悉/精通…）；
      2) 若**完全没有任何技能信号**，且 职责/经验/学历 至少再缺 1 项 → insufficient（该追问）；
      3) 其余 → sufficient（继续主链路，行为与加 Agent 之前一致）。

    另外把执行书的**字面规则**结果一并返回（`doc_rule`），便于对照与报告，不参与判定。
    """
    sig = signals(jd_parse, jd_text)
    missing = []
    if not _present(sig[REQUIRED_SKILLS_FIELD]):
        missing.append(REQUIRED_SKILLS_FIELD)
    for f in OPTIONAL_FIELDS:
        if not _present(sig[f]):
            missing.append(f)

    has_skill_signal = _present(sig[REQUIRED_SKILLS_FIELD]) or _present(sig["skill_phrase"])
    other_missing = [f for f in missing if f != REQUIRED_SKILLS_FIELD]
    if not has_skill_signal and len(other_missing) >= 1:
        status = "insufficient"
        reason = "JD 未给出技能要求，且缺少 %s" % "、".join(other_missing)
    else:
        status, reason = "sufficient", ""

    # 执行书字面规则（仅对照用）
    if not _present(sig[REQUIRED_SKILLS_FIELD]):
        doc_status, doc_reason = "insufficient", "JD 未给出任何必须技能"
    elif len(missing) >= MAX_MISSING_FIELDS:
        doc_status = "insufficient"
        doc_reason = "缺失 %d 项关键信息：%s" % (len(missing), "、".join(missing))
    else:
        doc_status, doc_reason = "sufficient", ""

    return {
        "status": status,
        "missing_fields": missing,
        "reason": reason,
        "signals": sig,
        "doc_rule": {"status": doc_status, "reason": doc_reason},
    }


def should_ask(round_no: int, status: str = "insufficient") -> bool:
    """A5：只有"信息不足"且追问轮数未到上限时，才继续追问。"""
    return status == "insufficient" and int(round_no or 0) < ROUND_LIMIT


if __name__ == "__main__":
    # 自检 + 用评测集做阈值校准（不调 LLM）
    import io
    import json
    import os

    from .tools import parse_jd

    demos = [
        ("空 JD", ""),
        ("只有一句话", "招聘前端。"),
        ("只有技能", "招聘前端工程师，要求精通 React。"),
        ("技能但词表没有", "招聘测试工程师，要求熟悉自动化测试与 Selenium，了解 JMeter。"),
        ("完整 JD", "招聘 Java 后端工程师。职责：负责交易系统服务端开发与性能优化。"
                    "要求：精通 Java、Spring Boot、MySQL，3 年以上经验，本科及以上学历。"),
    ]
    print("  样例：")
    for name, jd in demos:
        r = sufficiency(parse_jd(jd), jd)
        print("    %-14s -> %-12s missing=%-44s doc_rule=%s" % (
            name, r["status"], ",".join(r["missing_fields"]), r["doc_rule"]["status"]))

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "eval", "eval_set_v1_1.jsonl")
    tot = refined = literal = 0
    refined_ids, avoided = [], []
    for line in io.open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        c = json.loads(line)
        tot += 1
        r = sufficiency(parse_jd(c["jd"]), c["jd"])
        if r["status"] == "insufficient":
            refined += 1
            refined_ids.append((c["id"], r["missing_fields"], c["jd"][:40]))
        if r["doc_rule"]["status"] == "insufficient":
            literal += 1
            if r["status"] == "sufficient":
                avoided.append((c["id"], r["signals"]["skill_phrase"], c["jd"][:40]))

    print("\n  评测集校准（%d 条）：" % tot)
    print("    执行书字面规则判 insufficient : %d 条（%.1f%%）" % (literal, 100.0 * literal / tot))
    print("    校准后规则判 insufficient     : %d 条（%.1f%%）" % (refined, 100.0 * refined / tot))
    print("    被校准规则避免的误追问（字面会判、其实写了技能）: %d 条" % len(avoided))
    for cid, phrase, jd in avoided[:6]:
        print("      %-6s skill_phrase=%-22s %s" % (cid, phrase[:22], jd))
    print("    校准后仍判不足的用例：")
    for cid, miss, jd in refined_ids[:12]:
        print("      %-6s missing=%-48s %s" % (cid, ",".join(miss), jd))
