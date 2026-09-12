# -*- coding: utf-8 -*-
"""
A6：构建 eval_set_v1_2.jsonl = v1_1 的 200 条（**逐字不动**） + 10 条"信息不足"用例。

新用例特征：
- `source = "ask_insufficient"`（便于分组统计）
- `gt.conclusion = "待定"`（追问分支返回待定，与 no_scorable 路径一致）
- `gt.expected_status = "need_more_info"`（A6 新增的期望值：应触发追问）
- `gt.ask_round_limit = 2`、`gt.expected_questions = [1, 3]`
- `label_basis = "ask_branch"`、`label_source = "exec_doc_A6"`

覆盖执行书点名的三类：只写"招个前端" / 只有一句话 / 必须技能为空（含"只提软技能"这一边界）。

用法：python eval/build_eval_set_v1_2.py
"""
import io
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

EVAL = Path(__file__).resolve().parent
SRC = EVAL / "eval_set_v1_1.jsonl"
DST = EVAL / "eval_set_v1_2.jsonl"

# (id, jd, resume, 说明)
NEW_CASES = [
    ("E201", "招个前端", "本科，3 年前端开发，熟悉 React。", "只写一句话：招个前端"),
    ("E202", "招聘后端", "本科，5 年后端开发，熟悉 Java。", "只写一句话：招聘后端"),
    ("E203", "找个测试", "本科，2 年测试经验。", "只写一句话：找个测试"),
    ("E204", "招聘运营", "本科，3 年运营经验。", "只写一句话：招聘运营"),
    ("E205", "招聘后端工程师，要求有良好的沟通能力和团队协作精神",
     "本科，5 年 Java 后端，熟悉 Spring Boot、MySQL。", "只有软技能要求 → 必须技能为空"),
    ("E206", "我们需要一个懂技术的人", "本科，4 年开发经验。", "只有一句话、无法定位岗位"),
    ("E207", "招聘产品经理，要求", "本科，3 年产品经验，会 Axure。", "只有一句话（要求后无内容）"),
    ("E208", "急招开发", "本科，3 年开发经验。", "只有一句话：急招开发"),
    ("E209", "招聘算法工程师（要求面议）", "硕士，2 年算法经验，做过推荐。", "必须技能为空、只说面议"),
    ("E210", "招聘实习生前台", "在读本科，无工作经验。", "只写一句话：招聘实习生前台"),
]


def main():
    src_lines = [l.rstrip("\n") for l in io.open(SRC, encoding="utf-8") if l.strip()]
    assert len(src_lines) == 200, "v1_1 应为 200 条，实际 %d" % len(src_lines)
    src_ids = {json.loads(l)["id"] for l in src_lines}

    new_lines = []
    for cid, jd, resume, note in NEW_CASES:
        assert cid not in src_ids, "id 冲突: %s" % cid
        new_lines.append(json.dumps({
            "id": cid,
            "source": "ask_insufficient",
            "jd": jd,
            "resume": resume,
            "gt": {
                "conclusion": "待定",
                "jd_required_skills": [],
                "jd_preferred_skills": [],
                "resume_skills": [],
                "expected_status": "need_more_info",
                "ask_round_limit": 2,
                "expected_questions": [1, 3],
            },
            "label_basis": "ask_branch",
            "label_source": "exec_doc_A6",
            "needs_human_review": False,
            "note": note,
            "review_reason": "",
        }, ensure_ascii=False))

    with io.open(DST, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(src_lines + new_lines) + "\n")

    # 自证：前 200 条与 v1_1 逐字一致
    out = [l.rstrip("\n") for l in io.open(DST, encoding="utf-8") if l.strip()]
    same = out[:200] == src_lines
    print("  写出: %s" % DST)
    print("  行数: %d（v1_1 200 + 新增 %d）" % (len(out), len(new_lines)))
    print("  前 200 条与 v1_1 逐字一致: %s" % same)
    print("  新增 id: %s" % [json.loads(l)["id"] for l in new_lines])
    return 0 if (len(out) == 210 and same) else 1


if __name__ == "__main__":
    sys.exit(main())
