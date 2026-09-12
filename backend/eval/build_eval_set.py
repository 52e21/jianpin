# -*- coding: utf-8 -*-
"""
第 1 步：构建评测集 eval_set_v1.jsonl（200 条）

组成：
  - history          从 execution_history 捞出的"输入未被截断"的真实任务（PII 已脱敏）
  - sample_file      backend/.tmp/hire-tests/g1~g3.json
  - frontend_sample  前端 match.tsx 的 SAMPLE_JD / SAMPLE_RESUME
  - constructed      人工设计的边界用例（暴露已知缺陷）+ 模板生成用例

标注口径：**机器辅助初标 + 人工复核**（不是纯人工标注）
  - gt.jd_required_skills / jd_preferred_skills / resume_skills：由标注者阅读 JD/简历语义后写出，
    **不是**跑 parse_jd 得到的（否则就是拿被测实现当标准答案，指标必然 100%）
  - gt.conclusion：按需求文档 §5 的阈值规则（≥80 推荐 / <50 不推荐 / 50-79 待定）推导的期望值
  - needs_human_review：标注置信度低、或期望值与代码现状故意不一致的用例，标记待人工确认
"""
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(r"C:\Users\admin\Desktop\2\agent-assistant")
OUT_DIR = ROOT / "backend" / "eval"
OUT_DIR.mkdir(parents=True, exist_ok=True)
DB = ROOT / "backend" / "data" / "history.db"
SAMPLES = ROOT / "backend" / ".tmp" / "hire-tests"

TARGET = 200

# ---------------------------------------------------------------- PII 脱敏
KNOWN_NAMES = ["魏欣悦", "何立晴", "李四", "张三", "王五", "李雷", "赵工", "钱工",
               "周工", "孙工", "吴工", "郑工", "冯工", "陈工"]
PHONE_RE = re.compile(r"1[3-9]\d{9}")
EMAIL_RE = re.compile(r"[\w.\-]+@[\w\-]+\.\w+")


def mask(text: str) -> str:
    if not text:
        return ""
    for n in KNOWN_NAMES:
        text = text.replace(n, "候选人")
    text = PHONE_RE.sub("[手机号已脱敏]", text)
    text = EMAIL_RE.sub("[邮箱已脱敏]", text)
    return text


# ---------------------------------------------------------------- 真实数据源
def load_history():
    """从 execution_history 取输入未被截断的真实任务。"""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT task, result FROM execution_history ORDER BY id").fetchall()
    seen, out = set(), []
    for r in rows:
        task = r["task"] or ""
        if " | 简历: " not in task:
            continue
        if "…" in task:                      # 输入被截断，无法复现
            continue
        jd_part, resume_part = task.split(" | 简历: ", 1)
        jd = jd_part[4:] if jd_part.startswith("JD: ") else jd_part
        if jd.startswith("测试JD") or re.fullmatch(r"结果\d+", (r["result"] or "").strip()):
            continue                          # 测试垃圾数据
        key = (jd.strip(), resume_part.strip())
        if key in seen or not jd.strip() or not resume_part.strip():
            continue
        seen.add(key)
        out.append({"jd": jd.strip(), "resume": resume_part.strip(),
                    "note": "来自历史记录摘要；简历侧空白已被规范化"})
    conn.close()
    return out


def load_sample_files():
    out = []
    for p in sorted(SAMPLES.glob("*.json")):
        j = json.loads(p.read_text(encoding="utf-8-sig"))
        out.append({"jd": j["jd"], "resume": j["resume"], "note": f"来自 {p.name}"})
    return out


FRONTEND_JD = """高级 Java 开发工程师

岗位职责：
1. 负责公司核心业务系统的架构设计与开发
2. 参与技术方案评审，解决技术难题
3. 指导初中级工程师，提升团队技术水平
4. 优化系统性能，保障系统稳定性

任职要求：
1. 本科及以上学历，计算机相关专业
2. 5年以上 Java 开发经验，精通 Spring Boot、Spring Cloud
3. 熟练掌握 MySQL、Redis、Elasticsearch
4. 熟悉微服务架构，有高并发系统开发经验
5. 熟悉 Docker、Kubernetes
6. 具备良好的团队协作能力和沟通能力

加分项：
1. 有开源项目贡献经验
2. 有技术博客或技术分享经验
3. 有大厂背景优先"""

FRONTEND_RESUME = """张三
13800138000 | zhangsan@email.com

教育背景
本科 | 计算机科学与技术 | 某某大学

工作经验
5年 Java 开发经验

某某科技有限公司（2020-至今）
高级 Java 开发工程师
- 负责核心业务系统开发，使用 Spring Boot、Spring Cloud
- 数据库使用 MySQL、Redis
- 熟悉 Docker、Kubernetes 部署
- 具备良好的团队协作能力和沟通能力

技能
Java、Spring Boot、Spring Cloud、MySQL、Redis、Docker、Kubernetes、Git、Linux

项目经验
电商平台核心系统（2021-2023）
- 使用 Spring Boot 开发微服务架构
- 实现高并发订单处理，QPS 5000+
- 使用 Redis 缓存优化查询性能

自我评价
具备良好的团队协作能力和沟通能力，有开源项目贡献经验"""


def load_frontend_sample():
    return [{"jd": FRONTEND_JD, "resume": FRONTEND_RESUME, "note": "来自前端 match.tsx 示例数据"}]


# ---------------------------------------------------------------- 人工设计边界用例
# (jd, resume, req_skills, pref_skills, resume_skills, conclusion, review, reason)
HAND_CASES = [
    # A. 无技能可匹配 —— 暴露 total_w=0 → 100 分逻辑漏洞（期望值与代码现状故意不一致）
    ("招聘人力专员", "候选人，2年HR经验，负责招聘渠道维护与员工关系处理。",
     [], [], [], "待定", True, "用于暴露『JD 无可识别技能时分母为0→满分推荐』缺陷；业务期望为待定而非推荐"),
    ("招聘行政助理", "候选人，1年行政经验，负责办公用品采购与会议安排。",
     [], [], [], "待定", True, "同上：无可识别技能时不应给满分推荐"),
    ("招聘新媒体运营（专业不限）", "候选人，负责公众号日常运营与内容排版，会用剪映。",
     [], [], [], "待定", True, "同上：无可识别技能，期望不全盘推荐"),

    # B. 否定语境
    ("招聘前端工程师，要求精通 React 与 TypeScript。",
     "候选人，2年前端经验，主要使用 Vue，不会 React，TypeScript 不熟悉。",
     ["React", "TypeScript"], [], ["Vue"], "不推荐", False, "否定语境：不会React/不熟悉TS 均不应计为命中"),
    ("招聘后端工程师，要求精通 Redis 与消息队列。",
     "候选人，3年后端经验，未使用过 Redis，仅了解消息队列概念。",
     ["Redis", "消息队列"], [], [], "不推荐", False, "否定语境：未使用过/仅了解"),
    ("招聘运维工程师，要求熟悉 Docker 与 Kubernetes。",
     "候选人，2年运维经验，精通 Nginx 与 Linux，从未接触 Kubernetes，Docker 在学。",
     ["Docker", "Kubernetes"], [], ["Nginx", "Linux"], "不推荐", False, "否定语境：从未接触/在学"),
    ("招聘数据分析师，要求精通 SQL 与 Python。",
     "候选人，不了解 SQL，只会用 Excel 做透视表。",
     ["SQL", "Python"], [], ["Excel"], "不推荐", False, "否定语境：不了解"),

    # C. 子串陷阱
    ("招聘后端工程师，要求精通 SQL。",
     "候选人，3年经验，长期使用 MySQL 与 PostgreSQL 做数据查询优化。",
     ["SQL"], [], ["MySQL"], "推荐", True, "子串陷阱：MySQL 是否应算命中 SQL，需人工确认口径"),
    ("招聘后端工程师，要求精通 Spring。",
     "候选人，4年经验，精通 Spring Boot 与 Spring Cloud 微服务开发。",
     ["Spring"], [], ["Spring Boot"], "推荐", True, "子串陷阱：Spring Boot 是否应算命中 Spring，需人工确认"),
    ("招聘前端工程师，要求精通 Java。",
     "候选人，3年前端经验，精通 JavaScript 与 TypeScript。",
     ["Java"], [], ["JavaScript"], "不推荐", False, "子串陷阱：JavaScript 不应算命中 Java"),
    ("招聘前端工程师，要求熟悉 Vue。",
     "候选人，2年经验，使用 Vue.js 开发多个后台系统。",
     ["Vue"], [], ["Vue.js"], "推荐", True, "子串陷阱：Vue.js 是否算命中 Vue，需人工确认"),

    # D. 大小写 / 中英混排
    ("招聘运维工程师，要求熟悉 K8S 与容器化。",
     "候选人，3年经验，精通 k8s 集群运维与 Docker 容器化部署。",
     ["Kubernetes", "Docker"], [], ["Kubernetes", "Docker"], "推荐", True, "中英混排：k8s/K8S/Kubernetes 应视为同一技能"),
    ("招聘后端工程师，要求精通 SpringBoot。",
     "候选人，3年经验，精通 springboot 与 MySQL。",
     ["Spring Boot", "MySQL"], [], ["Spring Boot", "MySQL"], "推荐", True, "写法差异：SpringBoot/springboot/Spring Boot 应归一"),
    ("招聘前端工程师，要求精通 REACT。",
     "候选人，2年经验，精通 react 与 TypeScript。",
     ["React", "TypeScript"], [], ["React", "TypeScript"], "推荐", True, "大小写不敏感"),

    # E. 学历
    ("招聘后端工程师，要求本科以上学历，精通 Java。",
     "候选人，3年 Java 开发经验，精通 Java 与 Spring Boot。",
     ["Java"], [], ["Java"], "待定", True, "简历未写学历，期望不得因学历缺失直接判不推荐"),
    ("招聘算法工程师，要求硕士以上学历，精通 PyTorch。",
     "候选人，3年算法经验，本科学历，精通 PyTorch 与 TensorFlow。",
     ["PyTorch"], [], ["PyTorch", "TensorFlow"], "待定", True, "学历不满足硬性要求，期望为待定而非推荐"),
    ("招聘数据工程师，学历不限，要求精通 Spark。",
     "候选人，博士学历，4年经验，精通 Spark 与 Flink。",
     ["Spark"], [], ["Spark"], "推荐", False, "学历不限时不应因学历拉分"),
    ("招聘后端工程师，要求统招本科，精通 Go。",
     "候选人，大专学历，4年 Go 开发经验，精通 Go 与 Docker。",
     ["Go"], [], ["Go", "Docker"], "待定", True, "硬性学历要求 + 学历不足，期望待定"),

    # F. 经验
    ("招聘 Java 开发工程师，要求 5 年以上经验，精通 Java。",
     "候选人，4年 Java 经验，精通 Java 与 MySQL。",
     ["Java"], [], ["Java", "MySQL"], "待定", True, "经验差1年，期望不因1年差距判不推荐"),
    ("招聘 Java 开发工程师，要求 5 年以上经验，精通 Java。",
     "候选人，1年 Java 经验，了解 Java 基础语法。",
     ["Java"], [], [], "不推荐", True, "经验差距4年 + 仅了解，期望不推荐"),
    ("招聘前端工程师，要求 2 年以上经验，精通 React。",
     "候选人，8年前端经验，精通 React 与 Vue。",
     ["React"], [], ["React", "Vue"], "推荐", True, "经验超上限，期望小幅扣分但不影响推荐"),
    ("招聘测试工程师，要求精通 Python。",
     "候选人，2年测试开发经验，精通 Python 与自动化测试。",
     ["Python"], [], ["Python"], "推荐", False, "无年限要求，技能命中即推荐"),

    # G. 必须 vs 优先语境
    ("招聘后端工程师，必须精通 Java，熟悉 Redis 优先。",
     "候选人，3年经验，精通 Java，会使用 Redis。",
     ["Java"], ["Redis"], ["Java", "Redis"], "推荐", False, "必须/优先语境区分"),
    ("招聘后端工程师，了解 Kafka 即可，必须掌握 MySQL。",
     "候选人，3年经验，精通 MySQL，了解 Kafka。",
     ["MySQL"], ["Kafka"], ["MySQL", "Kafka"], "推荐", False, "了解类语境应归优先而非必须"),
    ("招聘后端工程师，要求 Java、Spring Boot、MySQL 三项技能。",
     "候选人，3年经验，精通 Java 与 Spring Boot，不熟悉 MySQL。",
     ["Java", "Spring Boot", "MySQL"], [], ["Java", "Spring Boot"], "待定", True, "未明确区分必须/优先时按前3项兜底为必须，缺1项"),
    ("招聘后端工程师，要求 Java 与 Spring Boot，熟悉 Docker 加分。",
     "候选人，3年经验，精通 Java 与 Spring Boot，熟悉 Docker 与 Kubernetes。",
     ["Java", "Spring Boot"], ["Docker"], ["Java", "Spring Boot", "Docker", "Kubernetes"], "推荐", False, "加分项命中"),

    # H. 加分项
    ("招聘 Java 工程师，精通 Java。加分项：有开源项目贡献经验。",
     "候选人，4年经验，精通 Java，有开源项目贡献与个人技术博客。",
     ["Java"], [], ["Java"], "推荐", False, "加分项命中"),
    ("招聘 Java 工程师，精通 Java。加分项：有大厂背景优先。",
     "候选人，4年经验，精通 Java，曾在某互联网大厂任职。",
     ["Java"], [], ["Java"], "推荐", False, "大厂背景加分命中"),
    ("招聘 Java 工程师，精通 Java。加分项：有技术博客或技术分享经验。",
     "候选人，4年经验，精通 Java，无任何对外技术分享。",
     ["Java"], [], ["Java"], "推荐", True, "加分项未命中，不应影响核心结论"),

    # I. 工作模式
    ("招聘后端工程师，支持远程办公，精通 Python。",
     "候选人，3年经验，精通 Python 与 FastAPI。",
     ["Python"], [], ["Python"], "推荐", False, "远程办公模式识别"),
    ("招聘后端工程师，混合办公，精通 Go。",
     "候选人，3年经验，精通 Go 与 Docker。",
     ["Go"], [], ["Go", "Docker"], "推荐", False, "混合办公模式识别"),

    # J. 极端输入
    ("招聘后端工程师，精通 Java。" + "负责核心系统开发与性能优化。" * 150,
     "候选人，3年经验，精通 Java 与 MySQL。",
     ["Java"], [], ["Java", "MySQL"], "推荐", True, "超长 JD（约3000字），考察上下文与token控制"),
    ("招聘后端工程师，精通 Java。",
     "候选人，3年经验，精通 Java。" + "参与过多个高并发项目，负责订单系统与支付系统的开发与维护。" * 120,
     ["Java"], [], ["Java"], "推荐", True, "超长简历（约1万字），考察上下文裁剪"),
    ("招聘后端工程师", "候选人，3年经验，精通 Java。",
     [], [], ["Java"], "待定", True, "JD 只有标题无技能要求，期望待定"),
    ("", "候选人，3年经验，精通 Java。",
     [], [], ["Java"], "不推荐", True, "空 JD 边界：接口层应直接报错"),
    ("招聘后端工程师，精通 Java。", "",
     ["Java"], [], [], "不推荐", True, "空简历边界：接口层应直接报错"),

    # K. 分数边界
    ("招聘后端工程师，精通 Java 与 MySQL，熟悉 Redis 优先。",
     "候选人，3年经验，精通 Java 与 MySQL，熟悉 Redis 与 Docker。",
     ["Java", "MySQL"], ["Redis"], ["Java", "MySQL", "Redis", "Docker"], "推荐", True, "全部命中，期望落在推荐区间上沿"),
    ("招聘后端工程师，精通 Java、Spring Boot、MySQL 与 Redis。",
     "候选人，3年经验，精通 Java 与 Spring Boot，不熟悉 MySQL 与 Redis。",
     ["Java", "Spring Boot", "MySQL", "Redis"], [], ["Java", "Spring Boot"], "待定", True, "技能命中 50%，期望落在中间区间"),
    ("招聘后端工程师，精通 Java 与 Python。",
     "候选人，2年经验，不会 Java，不懂 Python。",
     ["Java", "Python"], [], [], "不推荐", True, "零命中，期望落在不推荐区间下沿"),

    # L. 岗位多样性（覆盖词表）
    ("招聘测试工程师，要求熟悉自动化测试与 Selenium，了解 JMeter。",
     "候选人，3年测试经验，精通 Selenium 与 JMeter，会写 Python 脚本。",
     ["Selenium"], ["JMeter"], ["Selenium", "JMeter", "Python"], "推荐", False, "测试岗覆盖"),
    ("招聘产品经理，要求具备需求分析与 Axure 原型能力，有项目管理经验。",
     "候选人，4年产品经验，精通需求分析与 Axure，负责过完整项目管理流程。",
     ["需求分析", "Axure"], ["项目管理"], ["需求分析", "Axure", "项目管理"], "推荐", False, "产品岗覆盖"),
    ("招聘算法工程师，要求精通 PyTorch 与 NLP，有推荐算法经验。",
     "候选人，3年算法经验，精通 PyTorch 与 NLP，做过推荐算法项目。",
     ["PyTorch", "NLP", "推荐算法"], [], ["PyTorch", "NLP", "推荐算法"], "推荐", False, "算法岗覆盖"),
    ("招聘数据仓库工程师，要求精通 Hadoop、Spark 与 Flink。",
     "候选人，4年数仓经验，精通 Hadoop 与 Spark，了解 Flink。",
     ["Hadoop", "Spark"], ["Flink"], ["Hadoop", "Spark", "Flink"], "推荐", False, "数仓岗覆盖"),
    ("招聘 UI 设计师，要求精通 Figma，有用户研究经验。",
     "候选人，3年设计经验，精通 Figma，做过用户研究与增长设计。",
     ["Figma", "用户研究"], [], ["Figma", "用户研究"], "推荐", False, "设计岗覆盖"),
]

# ---------------------------------------------------------------- 模板生成
POSITIONS = ["Java 开发工程师", "前端工程师", "后端开发工程师", "数据分析师", "算法工程师",
             "测试工程师", "运维工程师", "数据工程师", "产品经理", "NLP 算法工程师",
             "机器学习工程师", "DevOps 工程师", "Go 开发工程师", "Python 开发"]
SKILLS = ["Java", "Spring Boot", "Python", "Go", "React", "Vue", "TypeScript", "JavaScript",
          "MySQL", "Redis", "Kafka", "Docker", "Kubernetes", "Linux", "Nginx", "SQL",
          "FastAPI", "Django", "Flask", "Spring", "微服务", "消息队列", "PyTorch",
          "TensorFlow", "NLP", "机器学习", "数据分析", "Spark", "Flink", "Hadoop",
          "Figma", "Axure", "需求分析", "项目管理", "爬虫", "OCR"]
NEG = ["不会", "不熟悉", "不了解", "未使用过", "从未接触"]
SOFT = ["团队协作", "沟通能力", "抗压能力", "学习能力"]
EDUS = ["本科", "硕士", "大专", "博士"]


def gen_templates(n):
    """模板生成用例；技能标签来自模板定义（不是跑代码得到的）。"""
    out = []
    i = 0
    while len(out) < n:
        i += 1
        pos = POSITIONS[i % len(POSITIONS)]
        req = [SKILLS[(i * 3) % len(SKILLS)], SKILLS[(i * 3 + 1) % len(SKILLS)]]
        pref = [SKILLS[(i * 5 + 2) % len(SKILLS)]]
        if len(set(req + pref)) < 3:
            continue
        years = 2 + (i % 6)
        edu = EDUS[i % len(EDUS)]
        soft = SOFT[i % len(SOFT)]

        jd = (f"招聘{pos}。岗位职责：负责核心业务模块的设计与开发，参与技术方案评审，优化系统性能。"
              f"任职要求：{edu}以上学历，{years}年以上相关经验，必须精通{req[0]}与{req[1]}，"
              f"熟悉{pref[0]}优先，具备良好的{soft}。")

        # 命中策略：全命中 / 缺1必需 / 缺全部 / 命中但被否定
        mode = i % 4
        if mode == 0:
            hit, negated = req + pref, []
        elif mode == 1:
            hit, negated = [req[0]] + pref, []
        elif mode == 2:
            hit, negated = [], []
        else:
            hit, negated = [req[0]], [req[1]]

        parts = []
        if hit:
            parts.append("精通" + "、".join(hit))
        for sk in negated:
            parts.append(f"{NEG[i % len(NEG)]}{sk}")
        if not parts:
            parts.append("主要使用 Excel 处理日常报表")
        resume = (f"候选人{chr(65 + i % 8)}，{edu}学历，{years + (i % 3) - 1}年相关经验，"
                  f"{'，'.join(parts)}，具备良好的{soft}。")

        resume_skills = sorted(set(hit))
        if mode == 0:
            conclusion, review = "推荐", False
        elif mode == 2:
            conclusion, review = "不推荐", False
        else:
            conclusion, review = "待定", True

        out.append({
            "jd": jd, "resume": resume,
            "req": req, "pref": pref, "resume_skills": resume_skills,
            "conclusion": conclusion, "review": review,
            "reason": f"模板生成模式{mode}（{'全命中' if mode == 0 else '部分命中' if mode in (1, 3) else '全缺失'}）",
            "note": "模板生成，技能标签由模板定义而非代码输出",
        })
    return out


# ---------------------------------------------------------------- 组装
def build():
    entries = []

    def add(src, jd, resume, req, pref, rskills, conclusion, review, reason, note=""):
        entries.append({
            "id": f"E{len(entries) + 1:03d}",
            "source": src,
            "jd": mask(jd),
            "resume": mask(resume),
            "gt": {
                "jd_required_skills": req,
                "jd_preferred_skills": pref,
                "resume_skills": rskills,
                "conclusion": conclusion,
            },
            "label_source": "machine_assisted",
            "label_basis": "annotator_reads_text" if src != "constructed" or reason.startswith("模板") else "spec_rule+annotator",
            "needs_human_review": review,
            "review_reason": reason if review else "",
            "note": note,
        })

    # 1) 真实历史（结论按需求文档阈值规则推导；技能标注由标注者阅读文本写出）
    hist = load_history()
    hist_labels = {
        "招聘数据分析师，要求熟悉Python与SQL，2年经验。": (["Python", "SQL"], [], ["Python", "SQL"], "推荐"),
        "招聘前端工程师，要求React和TypeScript。": (["React", "TypeScript"], [], ["React", "TypeScript"], "推荐"),
        "招聘前端工程师。要求：精通React和TypeScript，熟悉组件化开发。": (["React", "TypeScript"], [], ["Vue", "HTML", "CSS", "JavaScript"], "不推荐"),
        "招聘数据分析师，要求熟悉Python与SQL。": (["Python", "SQL"], [], ["Python", "SQL"], "推荐"),
        "招聘Java开发工程师。要求3年经验，必须精通SpringBoot与MySQL，熟悉Redis加分。": (["Spring Boot", "MySQL"], ["Redis"], ["Java", "Spring Boot", "MySQL"], "推荐"),
        "招聘前端工程师，要求精通React和TypeScript。": (["React", "TypeScript"], [], ["Vue"], "不推荐"),
        "招聘Java开发（扩招）。要求：精通Java与SpringBoot，3年经验，本科以上。": (["Java", "Spring Boot"], [], ["Java", "Spring Boot"], "推荐"),
        "招聘Java后端（新开HC）。要求：精通Java、SpringBoot，3年经验。": (["Java", "Spring Boot"], [], ["Java", "Spring Boot"], "推荐"),
        "招聘Java开发。要求：Java与SpringBoot2年经验。": (["Java", "Spring Boot"], [], ["Java", "Spring Boot"], "推荐"),
        "招聘数据分析师，要求Python与SQL。": (["Python", "SQL"], [], ["Python", "SQL"], "推荐"),
        "人力专员": ([], [], [], "待定"),
        "招聘数据分析师，要求Python与SQL。": (["Python", "SQL"], [], ["Python", "SQL"], "推荐"),
    }
    for h in hist:
        jd = h["jd"]
        if jd in hist_labels:
            req, pref, rs, concl = hist_labels[jd]
        else:                                     # 未命中映射表 → 标为待复核
            req, pref, rs, concl = [], [], [], "待定"
        review = jd not in hist_labels or jd == "人力专员"
        reason = ("历史真实输入，技能标注需人工复核" if jd not in hist_labels
                  else "暴露 total_w=0 满分逻辑缺陷，期望结论需人工确认" if jd == "人力专员" else "")
        add("history", jd, h["resume"], req, pref, rs, concl, review, reason, h["note"])

    # 2) 样本文件
    for s in load_sample_files():
        jd, rs = s["jd"], s["resume"]
        if "RAG" in jd:
            add("sample_file", jd, rs, ["大模型", "RAG", "Python", "SQL"], [], ["RAG", "大模型", "Python"], "待定", True, "样本文件，结论期望需人工确认", s["note"])
        elif "数据分析师" in jd:
            add("sample_file", jd, rs, ["Python", "SQL"], ["Excel", "Power BI"], ["Python", "SQL", "Excel", "Power BI"], "推荐", False, "", s["note"])
        else:
            add("sample_file", jd, rs, ["React", "TypeScript"], [], ["Vue", "HTML", "CSS", "JavaScript"], "不推荐", False, "", s["note"])

    # 3) 前端示例
    for s in load_frontend_sample():
        add("frontend_sample", s["jd"], s["resume"],
            ["Java", "Spring Boot", "MySQL", "Redis", "Docker", "Kubernetes"],
            ["Spring Cloud", "开源项目"], ["Java", "Spring Boot", "Spring Cloud", "MySQL", "Redis", "Docker", "Kubernetes"],
            "推荐", False, "", s["note"])

    # 4) 人工设计边界用例
    for (jd, rs, req, pref, rsk, concl, review, reason) in HAND_CASES:
        add("constructed", jd, rs, req, pref, rsk, concl, review, reason, "人工设计的边界用例")

    # 5) 模板生成，补足 200
    remain = TARGET - len(entries)
    for t in gen_templates(remain):
        add("constructed", t["jd"], t["resume"], t["req"], t["pref"], t["resume_skills"],
            t["conclusion"], t["review"], t["reason"], t["note"])

    return entries[:TARGET]


def main():
    entries = build()
    out = OUT_DIR / "eval_set_v1.jsonl"
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # ---- 验收自检 ----
    problems = []
    if len(entries) != TARGET:
        problems.append(f"条数 {len(entries)} != {TARGET}")
    for e in entries:
        blob = e["jd"] + e["resume"]
        if PHONE_RE.search(blob):
            problems.append(f"{e['id']} 含手机号")
        if EMAIL_RE.search(blob):
            problems.append(f"{e['id']} 含邮箱")
        for n in KNOWN_NAMES:
            if n in blob:
                problems.append(f"{e['id']} 含姓名 {n}")
        if not e["gt"]["conclusion"] in ("推荐", "待定", "不推荐"):
            problems.append(f"{e['id']} 结论非法")
    from collections import Counter
    src = Counter(e["source"] for e in entries)
    review = sum(1 for e in entries if e["needs_human_review"])

    print(f"输出: {out}")
    print(f"总条数: {len(entries)}")
    print(f"来源分布: {dict(src)}")
    print(f"待人工复核: {review} 条")
    print(f"PII/结构校验: {'通过' if not problems else '失败'}")
    for p in problems[:20]:
        print("  -", p)


if __name__ == "__main__":
    main()
