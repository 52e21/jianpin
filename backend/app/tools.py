"""招聘 Agent 工具集：JD 多维解析 / 简历加权匹配 / 面试题生成 / 推荐结论。

- parse_jd / match_resume：纯规则，零 LLM（单次解析 <100ms）。
- generate_interview_questions / summarize_recommendation：按需调用 LLM。
"""

import os
import re
import time
from functools import lru_cache

# ---------------------------------------------------------------------------
# 预置知识库（可扩展）
# ---------------------------------------------------------------------------
SKILL_KEYWORDS = [
    # 后端
    "Java", "Spring Boot", "Spring", "MySQL", "Redis", "微服务", "消息队列",
    "Kafka", "RabbitMQ", "Python", "FastAPI", "Flask", "Django", "Go",
    "Rust", "C++", "C#", "Node.js", "Docker", "Kubernetes", "Linux", "Nginx",
    # 前端
    "React", "Vue", "Angular", "TypeScript", "JavaScript", "HTML", "CSS",
    "Webpack", "Vite", "小程序", "Flutter", "React Native",
    # 数据 / AI
    "SQL", "RAG", "大模型", "机器学习", "深度学习", "NLP", "数据分析",
    "数据挖掘", "数据仓库", "Hadoop", "Spark", "Flink", "Power BI",
    "Tableau", "Excel", "TensorFlow", "PyTorch", "OCR", "推荐算法",
    # 通用 / 业务
    "产品设计", "项目管理", "Axure", "Figma", "爬虫", "A/B测试",
    "需求分析", "用户研究", "增长",
]

EDUCATION_LEVELS = ["博士", "硕士", "本科", "大专"]

# ---------------------------------------------------------------------------
# 推荐口径（已拍定，2026-09-12）
# ---------------------------------------------------------------------------
# 需求文档 §5：`匹配度 ≥80 且缺失必须技能 ≤1 → 推荐`。
# 即**允许缺 1 项必须技能仍推荐**，因为技能维度只占 40% 权重，其余维度（经验/学历/软技能/加分）
# 足以支撑 ≥80 分。
#
# 决策记录：
#   - 短期**维持**该口径 —— 评测集里 21 条标注（annotator=spec_derived）依赖它；
#     改口径会连带触发阈值调整 + 分数重算 + 基线重跑。
#   - "必须技能一项都不能缺"是**产品决策**，已单独立项评估，**不为了评测集变绿而改规范**。
#   - 修改此常量必须同步更新 `eval/test_recommendation_policy.py`（口径闸门）与升级报告。
MAX_MISSING_REQUIRED_FOR_RECOMMEND = 1

# 技能别名表：同一技术的不同写法 → 归一后的规范名（必须存在于 SKILL_KEYWORDS 中）
# 只收录"同一技术的不同写法"，不收录能力标签（如"自动化测试""容器化"），
# 也不为了迎合评测集而扩充技能覆盖范围（那是"词表扩容"事项，由业务定位决定）。
SKILL_ALIASES = {
    "k8s": "Kubernetes",
    "k8s集群": "Kubernetes",
}
# 反查表：规范名 → 该技能的其它写法（用于简历侧的命中检测）
SKILL_ALIAS_REVERSE: dict = {}
for _alias, _canonical in SKILL_ALIASES.items():
    SKILL_ALIAS_REVERSE.setdefault(_canonical, []).append(_alias)

EDUCATION_MAJORS = [
    "计算机", "软件工程", "电子信息", "通信", "数学", "统计", "自动化",
    "人工智能", "数据科学",
]

INDUSTRY_KEYWORDS = [
    "互联网", "金融", "电商", "教育", "医疗", "游戏", "汽车", "制造",
    "AI", "人工智能", "大数据", "云计算", "SaaS", "ToB", "企业服务",
]

PROJECT_TYPE_KEYWORDS = [
    "高并发", "企业级", "分布式", "数据", "算法", "微服务", "平台",
    "中台", "ToB", "C端", "B端", "架构", "性能优化", "全栈",
]

SOFT_SKILLS_LIB = [
    "团队协作", "沟通能力", "抗压能力", "学习能力", "逻辑思维", "问题排查",
    "领导力", "执行力", "责任心", "主动性", "创新能力", "跨部门协作",
]

BONUS_PATTERNS = [
    "技术博客", "开源项目", "竞赛获奖", "证书", "博客", "开源", "专利",
    "英语", "海外背景", "大厂", "社区贡献", "ACM",
]

POSITION_TITLES = [
    "Java 开发工程师", "Java工程师", "Python 开发", "前端工程师", "前端开发",
    "后端开发工程师", "后端工程师", "数据分析师", "AI 产品经理", "产品经理",
    "算法工程师", "测试工程师", "运维工程师", "数据工程师", "架构师",
    "NLP 算法工程师", "大模型算法工程师", "机器学习工程师", "UI 设计师",
    "Android工程师", "iOS工程师", "DevOps 工程师", "安全工程师", "DBA",
]

LEVEL_RULES = [
    (("8年以上", "资深", "专家", "首席", "8 年"), "专家"),
    (("5年以上", "5 年", "架构", "带领团队", "主导"), "高级"),
    (("2-5", "2~5", "2 至 5", "独立负责", "2年以上"), "中级"),
    (("应届", "实习", "1年以下", "1 年以下"), "初级"),
]

DEPARTMENT_KEYWORDS = [
    "研发部", "技术部", "产品部", "设计部", "数据部", "算法部", "市场部",
    "运营部", "架构部", "AI Lab", "研究院", "中台部门",
]


def _find_first(text: str, keywords) -> str:
    for k in keywords:
        if k in text:
            return k
    return ""


# ---------------------------------------------------------------------------
# 事项 2：技能名匹配（写法归一 + 词边界）
# ---------------------------------------------------------------------------
# 分两层（与业务确认的口径一致）：
#   1) **写法变体**用归一化函数机械处理 —— 去空白与 . - _ / 并转小写。
#      Spring Boot / SpringBoot / spring-boot / SPRING BOOT 自动归一到同一形态，
#      不需要为每种写法枚举别名。
#   2) **缩写与跨技术别名**（k8s→Kubernetes、js→JavaScript 等）仍用 SKILL_ALIASES 显式枚举。
#
# 不能用 \b：C++ / C# / Node.js / A/B测试 含符号，\b 在 + # . / 之后不成立，
# 会导致这些技能永远匹配不上。改用语义化边界（见 _edge_ok）。
#
# 归一化的关键难点：去掉分隔符后就无法区分 "JavaScript" 与 "Java Script"，
# 因此这里保留"归一化下标 → 原文下标"的映射，**词边界始终在原文上判定**。
_SEP_RE = re.compile(r"[\s.\-_/]")
_ASCII_ALNUM_RE = re.compile(r"[A-Za-z0-9]")


def _norm_skill(s: str) -> str:
    """写法归一：去掉空白与 . - _ / 并转小写。"""
    return _SEP_RE.sub("", (s or "").lower())


def _norm_index(lower_text: str):
    """返回 (归一化文本, 位置映射)；位置映射把归一化下标映射回原文下标。"""
    chars, pos = [], []
    for i, ch in enumerate(lower_text):
        if _SEP_RE.fullmatch(ch):
            continue
        chars.append(ch)
        pos.append(i)
    return "".join(chars), tuple(pos)


@lru_cache(maxsize=64)
def _norm_index_cached(lower_text: str):
    """带缓存的归一化索引。

    同一个文本会被 ~70 个技能名各查一次（简历侧还更多），不缓存的话每查一次就重建
    索引 → 实测 P50 从 0.2ms 涨到 3.8ms。缓存后回到亚毫秒级。
    maxsize=64 足以覆盖"一次分析里的 JD + 简历"，且不会无限增长。
    """
    return _norm_index(lower_text)


def _edge_ok(lower_text: str, start: int, end: int, norm_token: str) -> bool:
    """词边界判定（在原文坐标上）。

    - 归一化技能名以 ASCII 字母/数字开头 → 左侧原文不能是 ASCII 字母/数字
      （拦 "Django" 里的 "go"、"MySQL" 里的 "SQL"）
    - 归一化技能名以 ASCII 字母/数字结尾 → 右侧原文不能是 ASCII 字母/数字
      （拦 "JavaScript" 里的 "Java"；而 "C++" 归一后以 '+' 结尾，不做右检查，故 "C++11" 仍命中）
    """
    head, tail = norm_token[:1], norm_token[-1:]
    if head.isascii() and head.isalnum() and start > 0 and _ASCII_ALNUM_RE.match(lower_text[start - 1]):
        return False
    if tail.isascii() and tail.isalnum() and end < len(lower_text) and _ASCII_ALNUM_RE.match(lower_text[end]):
        return False
    return True


def _find_spans(lower_text: str, token: str) -> list:
    """返回 token 在 lower_text 中所有满足词边界的出现区间 [(start, end), ...]（原文坐标）。

    写法变体（空格/点/连字符差异）会被归一化后匹配到，但边界仍按原文判定。
    """
    norm_token = _norm_skill(token)
    if not norm_token:
        return []
    norm_text, pos = _norm_index_cached(lower_text)
    out, idx = [], 0
    while True:
        p = norm_text.find(norm_token, idx)
        if p < 0:
            return out
        start = pos[p]
        end = pos[p + len(norm_token) - 1] + 1
        if _edge_ok(lower_text, start, end, norm_token):
            out.append((start, end))
        idx = p + 1


def _find_all(lower_text: str, token: str) -> list:
    """只返回起始位置（保留旧接口，供断言/调试使用）。"""
    return [s for s, _ in _find_spans(lower_text, token)]


def _token_hits(lower_text: str, token: str) -> bool:
    """是否存在满足词边界的出现（等价于原 `token in text` 的严格版）。"""
    if not token:
        return False
    if token in lower_text:                      # 快速路径：原文直接命中
        return bool(_find_spans(lower_text, token))
    return bool(_find_spans(lower_text, token))  # 写法变体路径


def _is_covered_by(short: str, long: str, lower_text: str) -> bool:
    """short 的每一次出现是否都被 long 的出现区间覆盖（即 short 从不独立成词）。

    用于子串去重：只有完全被覆盖才算冗余（Spring 在 Spring Boot 里），
    否则保留（Java 在 "精通 Java，熟悉 JavaScript" 里必须保留）。
    """
    long_spans = _find_spans(lower_text, long)
    if not long_spans:
        return False
    for ss, se in _find_spans(lower_text, short):
        if not any(a <= ss and se <= b for a, b in long_spans):
            return False
    return True


# ---------------------------------------------------------------------------
# 工具 1：parse_jd —— 八维度 JD 结构化解析（纯规则，零 LLM）
# ---------------------------------------------------------------------------
def parse_jd(jd_text: str) -> dict:
    """从 JD 文本提取完整岗位画像（职位/部门/级别/职责/技能/经验/学历/软技能/加分项/工作模式）。"""
    text = jd_text or ""
    lower = text.lower()

    # ---------- 3.1 职位名称 / 部门 / 级别 ----------
    position = ""
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    for t in POSITION_TITLES:
        if t in text and (t in first_line or position == ""):
            position = t
            break
    if not position and "招聘" in first_line:
        m = re.search(r"招聘\s*([^，。,\s]{2,20})", first_line)
        if m:
            position = m.group(1).strip()

    department = _find_first(text, DEPARTMENT_KEYWORDS)

    level = ""
    for keys, lv in LEVEL_RULES:
        if any(k in text for k in keys):
            level = lv
            break
    if not level:
        if "初级" in text:
            level = "初级"
        elif "中级" in text:
            level = "中级"

    # ---------- 3.2 岗位职责 ----------
    responsibilities = []
    duty_verbs = ("负责", "参与", "完成", "推动", "主导", "搭建", "设计", "开发", "维护",
                  "优化", "跟进", "配合", "协助", "支持", "编写", "实现", "落地", "承担")
    filter_words = ("我们提供", "公司是", "福利", "薪资", "五险一金", "氛围")

    # 优先从"职责"关键词之后切分
    work_text = text
    for marker in ("岗位职责", "职责", "工作内容", "职位描述"):
        idx = work_text.find(marker)
        if idx >= 0:
            work_text = work_text[idx + len(marker):]
            break

    sentences = re.split(r"[。；;\n]", work_text)
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        # 去掉句首非职责前缀（如"岗位：Java 开发工程师"），动词必须出现在句首 6 字内
        stripped = re.sub(r"^[^，。]{0,10}?[：:]\s*", "", s)
        candidate = s
        if stripped.startswith(duty_verbs):
            candidate = stripped
        if not candidate.startswith(duty_verbs):
            continue
        # 取动词到第一个标点或限制长度
        if len(candidate) <= 100 and not any(f in candidate for f in filter_words):
            responsibilities.append(candidate)
    # 若仍为空，退回从全文找以动词开头且短于 40 字的片断
    if not responsibilities:
        for s in re.split(r"[。；;\n]", text):
            s = s.strip()
            if s.startswith(duty_verbs) and len(s) <= 80 and not any(f in s for f in filter_words):
                responsibilities.append(s)
    responsibilities = list(dict.fromkeys(responsibilities))[:6]

    # ---------- 3.3 技能要求：必须 vs 优先 ----------
    all_skills = []
    for s in SKILL_KEYWORDS:
        # 事项 2：加词边界，避免 "JavaScript" 命中 "Java"、"Django" 命中 "go"
        if _find_all(lower, s):
            all_skills.append(s)
    # 别名归一（事项 1 附带修复）：中英写法差异不算两个技能 —— 例如 JD 写 "K8S"、
    # 简历写 "k8s 集群运维"，都必须归一到 Kubernetes，否则会出现"JD 无可评分维度"的假象。
    # 注意：别名表只收录**同一技术的不同写法**；像"自动化测试""容器化"这类**能力标签**
    # 不进技能词表（由业务定位决定，不因评测集而加）。
    for alias, canonical in SKILL_ALIASES.items():
        if _find_all(lower, alias) and canonical not in all_skills:
            all_skills.append(canonical)
    # 子串去重（事项 2 同步收紧）：
    # 原规则是"短技能名是长技能名的子串就丢弃"，用来合并 Spring⊂Spring Boot、SQL⊂MySQL。
    # 但加了词边界后 Java 与 JavaScript 是**两个不同技能**，原规则会把 Java 误删。
    # 新规则：只有当短技能名的**每一次出现都被长技能名的出现覆盖**（即它从不独立成词）时才算冗余。
    #   精通 Java，熟悉 JavaScript → Java 有独立出现 → 两者都保留 ✔
    #   精通 Spring Boot          → Spring 只出现在 Spring Boot 内部 → 丢弃 Spring ✔
    deduped_skills = []
    for s in all_skills:
        s_low = s.lower()
        if any(s_low in other.lower() and s != other and _is_covered_by(s, other, lower)
               for other in all_skills):
            continue
            continue
        deduped_skills.append(s)
    all_skills = deduped_skills

    required, preferred = [], []
    # 遍历技能所有出现位置：任一处在"必须"语境 → 必须；否则任一在"优先"语境 → 优先
    strong_words = ("必须", "精通", "熟练", "扎实", "硬性", "要求掌握", "必备")
    weak_words = ("优先", "加分", "了解", "熟悉", "掌握更佳", "更好", "如有")
    for s in all_skills:
        is_req, is_pref = False, False
        for (start, end) in _find_spans(lower, s):
            ctx = text[max(0, start - 25): end + 25]
            if any(w in ctx for w in strong_words):
                is_req = True
                break
            if any(w in ctx for w in weak_words):
                is_pref = True
        if is_req:
            required.append(s)
        else:
            preferred.append(s)  # 含 is_pref 与无语境项（先归优先，下方按数量兜底）

    # 若 JD 未明确区分，前 3 个技能作为必须，其余为优先
    if not required:
        if all_skills:
            required = all_skills[:3]
            preferred = all_skills[3:]
    # 兜底：必须为空则全放优先
    if not required and not preferred:
        pass

    # ---------- 3.4 经验要求 ----------
    min_years, max_years = 0, 0
    exp_m = re.search(r"(\d+)\s*[-~到至]\s*(\d+)\s*年", text)
    if exp_m:
        min_years, max_years = int(exp_m.group(1)), int(exp_m.group(2))
    else:
        m2 = re.search(r"(\d+)\s*年以上", text)
        if m2:
            min_years = int(m2.group(1))
        else:
            m3 = re.search(r"(\d+)\s*年", text)
            if m3:
                min_years = int(m3.group(1))

    industry = [k for k in INDUSTRY_KEYWORDS if k in text]
    project_type = [k for k in PROJECT_TYPE_KEYWORDS if k in text]

    # ---------- 3.5 学历要求 ----------
    edu_level = ""
    for lv in EDUCATION_LEVELS:
        if lv in text:
            edu_level = lv
            break
    if not edu_level:
        edu_level = "不限"
    major = ""
    for mj in EDUCATION_MAJORS:
        if mj in text and ("专业" in text or mj in text):
            major = mj + ("相关" if "相关" in text and mj in text else "")
            break
    if not major:
        major = "专业不限"
    is_strict = any(w in text for w in ("必须", "统招", "硬性", "要求本科", "要求硕士"))

    # ---------- 3.6 软技能 ----------
    soft_skills = [s for s in SOFT_SKILLS_LIB if s in text]

    # ---------- 3.7 加分项 ----------
    bonus = []
    for b in BONUS_PATTERNS:
        idx = text.find(b)
        if idx >= 0:
            # 只看是否在"优先/加分"语境下（否则容易误报）
            pre = text[max(0, idx - 20): idx]
            if any(w in pre for w in ("优先", "加分", "有", "具有", "具备")):
                bonus.append("有" + b if not b.startswith("有") else b)
    # 通用兜底：出现"优先/加分"句子，尝试收集短语
    if not bonus:
        for m in re.finditer(r"(?:优先|加分)[^。\n]{0,30}", text):
            seg = m.group()
            for b in BONUS_PATTERNS:
                if b in seg and "有" + b not in bonus and b not in bonus:
                    bonus.append("有" + b if not b.startswith("有") else b)
    # 去重（含子串去重："有博客" 是 "有技术博客" 的子集时保留更长的）
    bonus = list(dict.fromkeys(bonus))[:4]
    deduped = []
    for b in bonus:
        core = b.replace("有", "")
        if any((core in (x.replace("有", ""))) and (x != b) for x in bonus):
            continue  # 自己是更短的那个，跳过
        deduped.append(b)
    bonus = deduped[:4]

    # ---------- 3.8 工作模式 ----------
    work_mode = "现场"
    if "远程" in text:
        work_mode = "远程"
    elif "混合" in text or "混合办公" in text:
        work_mode = "混合办公"
    elif "可居家" in text:
        work_mode = "可居家"

    return {
        "position": position,
        "department": department,
        "level": level,
        "responsibilities": responsibilities,
        "skills": {"required": required, "preferred": preferred},
        "experience": {"min_years": min_years, "max_years": max_years, "industry": industry, "project_type": project_type},
        "education": {"level": edu_level, "major": major, "is_strict": is_strict},
        "soft_skills": soft_skills,
        "bonus": bonus,
        "work_mode": work_mode,
    }


# ---------------------------------------------------------------------------
# 工具 2：match_resume —— 加权匹配度（纯规则，零 LLM）
# 综合匹配度 = 技能40% + 经验25% + 学历15% + 软技能10% + 加分项10%
# ---------------------------------------------------------------------------
def _contains_skill(resume_text: str, skill: str) -> bool:
    """技能命中检测（含否定语境排除 + 别名归一）。

    别名归一很关键：JD 侧把 "K8S" 归一到 Kubernetes 后，简历侧也必须能用 "k8s" 命中，
    否则会出现"JD 识别出了技能、简历却永远匹配不上"的单边错配。
    """
    for candidate in [skill] + SKILL_ALIAS_REVERSE.get(skill, []):
        if _contains_token(resume_text, candidate):
            return True
    return False


# 否定词表与"小句边界"标点（事项 3 复核时新增：窗口必须按小句截断）
_NEGATION_WORDS = ("不会", "不懂", "没有", "未接触", "未使用", "没接触", "没用过", "不熟悉",
                   "不了解", "缺乏", "缺少", "只有了解", "仅了解", "了解不多", "了解一点",
                   "未掌握", "不精通", "刚学", "在学", "学习中", "未曾", "从未", "没用",
                   "没怎么用", "不太会", "不怎么会")
# 只把真正的标点当小句边界。**空格不算**——"不会 React" 是合法的相邻否定，
# 若把空格当边界，会漏掉这类否定（我在诊断脚本第一版就犯过这个错）。
_CLAUSE_PUNCT = "，。；;、,！!？?：:（）()\n"


def _clause_bounded(window: str, from_left: bool) -> str:
    """把窗口截断到同一小句内：左侧窗口取最后一个标点之后，右侧窗口取第一个标点之前。"""
    if from_left:
        for i in range(len(window) - 1, -1, -1):
            if window[i] in _CLAUSE_PUNCT:
                return window[i + 1:]
        return window
    for i, ch in enumerate(window):
        if ch in _CLAUSE_PUNCT:
            return window[:i]
    return window


def _contains_token(resume_text: str, token: str) -> bool:
    """单个词形的出现检测（带词边界 + 否定语境窗口）。

    - 事项 2：用 _find_spans 取代裸 find —— "精通 JavaScript" 不会被判为命中 Java。
    - 事项 3 复核：否定窗口**按小句截断**。原实现取前后各 12 字符、会跨过标点，于是
      "精通 Java 与 Spring Boot，不熟悉 MySQL" 里的 Spring Boot 被邻居的"不熟悉"误伤，
      本应命中的技能被判缺失（实测影响 15 条用例、一致率 63.0%→70.5%）。
    """
    lower = (resume_text or "").lower()
    s = (token or "").lower()
    if not s:
        return False
    for pos, end in _find_spans(lower, s):
        before = _clause_bounded(lower[max(0, pos - 12):pos], from_left=True)
        after = _clause_bounded(lower[end:end + 12], from_left=False)
        if any((n in before) or (n in after) for n in _NEGATION_WORDS):
            continue
        return True
    return False


def match_resume(jd_result: dict, resume_text: str) -> dict:
    """按 JD 多维画像加权匹配简历。"""
    text = resume_text or ""
    lower = text.lower()
    required = jd_result.get("skills", {}).get("required", []) or []
    preferred = jd_result.get("skills", {}).get("preferred", []) or []
    exp = jd_result.get("experience", {}) or {}
    edu = jd_result.get("education", {}) or {}
    soft = jd_result.get("soft_skills", []) or []
    bonus = jd_result.get("bonus", []) or []

    # ---- 技能匹配（40%）: 必须×3 / 优先×1 ----
    hit_req, hit_pref = 0, 0
    for s in required:
        if _contains_skill(text, s):
            hit_req += 1
    for s in preferred:
        if _contains_skill(text, s):
            hit_pref += 1
    total_w = len(required) * 3 + len(preferred) * 1
    hit_w = hit_req * 3 + hit_pref * 1
    skill_score = round(hit_w / total_w * 100) if total_w else 0

    # ---- 经验匹配（25%）：年限 80% + 行业 20% ----
    min_y = exp.get("min_years") or 0
    max_y = exp.get("max_years") or 0
    exp_score = 100
    m = re.search(r"(\d+)\s*年", text)
    resume_y = int(m.group(1)) if m else 0
    if min_y and resume_y and resume_y < min_y:
        # 差 1 年内按比例扣
        diff = min_y - resume_y
        exp_score = max(0, 100 - diff * 25)
    elif max_y and resume_y and resume_y > max_y:
        exp_score = 90  # 超上限小幅扣分
    # 行业交集
    jd_industry = exp.get("industry") or []
    industry_hit = 0
    for ind in jd_industry:
        if ind.lower() in lower:
            industry_hit = 1
            break
    exp_score = exp_score * 0.8 + (100 if industry_hit else 0) * 0.2 if jd_industry else exp_score

    # ---- 学历匹配（15%）----
    edu_score = 100
    jd_level = edu.get("level") or "不限"
    if jd_level in ("博士", "硕士", "本科", "大专"):
        # 简历学历按出现最高档粗评
        resume_level = 0
        for i, lv in enumerate(("大专", "本科", "硕士", "博士")):
            if lv in text:
                resume_level = i + 1
        jd_level_rank = {"大专": 1, "本科": 2, "硕士": 3, "博士": 4}.get(jd_level, 2)
        if resume_level == 0:
            edu_score = 60
        elif resume_level < jd_level_rank:
            edu_score = max(0, 100 - (jd_level_rank - resume_level) * 30)
        elif resume_level >= jd_level_rank:
            edu_score = 100
    else:
        edu_score = 100  # 不限

    # ---- 软技能匹配（10%）----
    soft_hit = sum(1 for s in soft if s in text)
    soft_score = round(soft_hit / len(soft) * 100) if soft else 100

    # ---- 加分项匹配（10%）----
    bonus_hit = 0
    for b in bonus:
        core = b.replace("有", "").strip()
        if core and core in text:
            bonus_hit += 1
    bonus_score = round(bonus_hit / len(bonus) * 100) if bonus else 100

    # ---- 综合（仅对有要求的维度加权并归一化）----
    # 权重：技能40 / 经验25 / 学历15 / 软技能10 / 加分10
    has_soft = len(soft) > 0
    has_bonus = len(bonus) > 0
    has_exp = bool(exp.get("min_years") or exp.get("industry"))
    # 学历"不限/专业不限"不算硬要求；仅当 JD 明确层次才算
    has_edu = jd_level in ("博士", "硕士", "本科", "大专")
    has_skill = len(required) + len(preferred) > 0

    weights = {
        "skill": 0.40 if has_skill else 0,
        "exp": 0.25 if has_exp else 0,
        "edu": 0.15 if has_edu else 0,
        "soft": 0.10 if has_soft else 0,
        "bonus": 0.10 if has_bonus else 0,
    }
    total_w = sum(weights.values())
    if total_w <= 0:
        # 事项 1：JD 未识别出任何可评分维度（技能/经验/学历/软技能/加分全为空）。
        # 原实现直接给 100 分，于是走到"≥80 且缺失≤1 → 推荐"，产出
        # "匹配度 100% / 命中 无 / 核心要求全覆盖"这种自相矛盾的结论（真实历史数据里出现过）。
        # 现在返回 0 分 + 显式标记，由编排层判定为"待定（建议人工复核）"。
        return {
            "match_score": 0,
            "matched_skills": [],
            "missing_skills": [],
            "summary": "JD 未识别出可评分维度，建议人工复核",
            # 供编排层判定用的机器标记
            "no_scorable_dimension": True,
            # 同时按待办要求给出直接可用的结论字段（additive，不影响既有读取方）
            "conclusion": "待定",
            "reason": "JD 未识别出可评分维度，建议人工复核",
            "dimensions": {
                "skill_score": 0, "exp_score": 0, "edu_score": 0,
                "soft_score": 0, "bonus_score": 0,
            },
        }
    else:
        # 归一化权重
        scores = {
            "skill": skill_score,
            "exp": exp_score if has_exp else 100,
            "edu": edu_score if has_edu else 100,
            "soft": soft_score if has_soft else 100,
            "bonus": bonus_score if has_bonus else 100,
        }
        match_score = int(round(
            sum(scores[k] * weights[k] for k in weights) / total_w
        ))

    hit_skill = [s for s in required if _contains_skill(text, s)] + [s for s in preferred if _contains_skill(text, s)]
    miss_req = [s for s in required if not _contains_skill(text, s)]

    parts = []
    if required:
        parts.append(f"必须技能命中 {hit_req}/{len(required)}")
    if preferred and hit_pref:
        parts.append(f"优先命中 {hit_pref}")
    if min_y and resume_y < min_y:
        parts.append(f"经验 {resume_y}年 不足{min_y}年")
    if miss_req:
        parts.append("缺 " + "、".join(miss_req))
    summary = "；".join(parts) if parts else (f"命中 {len(hit_skill)} 项要求")

    return {
        "match_score": max(0, min(100, match_score)),
        "matched_skills": hit_skill,
        "missing_skills": miss_req,
        "summary": summary,
        # 维度明细（前端/日志可展示）
        "dimensions": {
            "skill_score": max(0, min(100, skill_score)),
            "exp_score": max(0, min(100, round(exp_score))),
            "edu_score": max(0, min(100, edu_score)),
            "soft_score": max(0, min(100, soft_score)),
            "bonus_score": max(0, min(100, bonus_score)),
        },
    }


# ---------------------------------------------------------------------------
# 第 6 步：结构化上下文构造（替代"JD 全文 + 简历全文"直塞）
# ---------------------------------------------------------------------------
_EXP_DATE_RE = re.compile(r"((19|20)\d{2}\s*[年./\-]|至今|现在|present)", re.I)
_EXP_ANCHOR_WORDS = ("公司", "科技", "有限", "集团", "研究院", "事业部", "部门", "中心",
                     "工程师", "开发", "经理", "专员", "设计师", "分析师", "实习生",
                     "任职", "工作经历", "项目经验", "项目", "负责")
_EXP_SECTION_STOP = ("教育背景", "教育经历", "学历", "技能", "专业技能", "自我评价",
                     "获奖", "证书", "兴趣爱好", "个人信息")
_EXP_BLOCK_MAX_CHARS = 180


def extract_experiences(resume_text: str, max_n: int = 3) -> list:
    """从简历文本中规则抽取最多 max_n 段"核心经历"。

    策略（三级兜底，保证一定能返回列表）：
      1) 锚点扫描：含年份区间/「至今」或含公司/职位关键词的行作为锚点，
         把锚点行及其后若干行合并为一段，遇到下一个锚点或章节标题（技能/教育背景…）时收束；
      2) 若无锚点：按空行分块，取最长的 max_n 块；
      3) 若仍无：按句号切分，取最长的 max_n 句。
    每段截断到 180 字，避免把 token 省回来的又花回去。
    """
    text = (resume_text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        return []

    lines = [ln.strip() for ln in text.split("\n")]
    blocks, cur = [], []
    MAX_LINES_PER_BLOCK = 4

    def flush():
        if cur:
            blocks.append(" ".join(cur).strip())
            cur.clear()

    for ln in lines:
        if not ln:
            flush()
            continue
        if any(s in ln for s in _EXP_SECTION_STOP) and len(ln) <= 12:
            flush()
            continue
        is_anchor = bool(_EXP_DATE_RE.search(ln)) or any(w in ln for w in _EXP_ANCHOR_WORDS)
        if is_anchor and cur:
            flush()
        if is_anchor or cur:
            cur.append(ln)
            if len(cur) >= MAX_LINES_PER_BLOCK:
                flush()

    flush()
    blocks = [b for b in blocks if len(b) >= 8]                 # 丢掉过短噪声

    if not blocks:                                              # 兜底 2：按空行分块
        blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if len(b.strip()) >= 8]
    if not blocks:                                              # 兜底 3：按句号切分
        blocks = [s.strip() for s in re.split(r"[。；;]", text) if len(s.strip()) >= 8]

    blocks.sort(key=len, reverse=True)
    out, seen = [], set()
    for b in blocks:
        key = b[:40]
        if key in seen:
            continue
        seen.add(key)
        out.append(b[:_EXP_BLOCK_MAX_CHARS])
        if len(out) >= max_n:
            break
    return out


def build_interview_context(jd_parse: dict, match_result: dict, resume_text: str,
                            max_exp: int = 3) -> str:
    """把 jd_parse + match_result + 简历经历，压成一段紧凑的结构化上下文。

    包含：必须技能 / 优先技能 / 缺失技能 / 已命中技能 / 匹配度与五维得分 / 最多 3 段核心经历。
    """
    jd_parse = jd_parse or {}
    match_result = match_result or {}
    skills = jd_parse.get("skills", {}) or {}
    req = list(skills.get("required", []) or [])
    pref = list(skills.get("preferred", []) or [])
    matched = list(match_result.get("matched_skills", []) or [])
    missing = list(match_result.get("missing_skills", []) or [])
    dims = match_result.get("dimensions", {}) or {}
    score = match_result.get("score", match_result.get("match_score", ""))

    def _dim(*names):
        """兼容两种维度命名：analyze 用 skills/experience/...，match_resume 用 skill_score/exp_score/..."""
        for n in names:
            if n in dims:
                return dims[n]
        return "-"

    lines = [
        f"【岗位必须技能】{'、'.join(req) if req else '未识别出明确技能'}",
        f"【岗位优先技能】{'、'.join(pref) if pref else '未要求'}",
        f"【缺失技能（必须但未命中）】{'、'.join(missing) if missing else '无'}",
        f"【已命中技能】{'、'.join(matched) if matched else '无'}",
        (f"【综合匹配度】{score}%（技能 {_dim('skills', 'skill_score')} / 经验 {_dim('experience', 'exp_score')}"
         f" / 学历 {_dim('education', 'edu_score')} / 软技能 {_dim('soft_skills', 'soft_score')}"
         f" / 加分 {_dim('bonus', 'bonus_score')}）"),
        "【候选人核心经历】",
    ]
    exps = extract_experiences(resume_text, max_exp)
    if exps:
        for i, e in enumerate(exps, 1):
            lines.append(f"{i}. {e}")
    else:
        lines.append("（未能抽取到结构化经历，请围绕岗位必须技能与缺失技能出题）")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 工具 3：generate_interview_questions —— 面试题生成（调 LLM）
# ---------------------------------------------------------------------------
async def generate_interview_questions(jd_text: str, resume_text: str, stats: dict = None,
                                       structured: bool = False, context: str = None,
                                       rag_skills: list = None):
    """根据 JD + 简历生成 3-5 个针对性面试题。

    structured=False → 返回纯文本问题列表（SSE 用）
    structured=True  → 返回 [{"category","difficulty","question"}]（analyze 用）
    context          → 第 6 步新增：结构化上下文（由 build_interview_context 生成）。
                       传入时不再塞 JD/简历全文；为 None 时保持旧行为（向后兼容）。
    rag_skills       → R6 新增：JD 解析出的技能列表。非空时做**只读检索**，把「岗位能力参考」
                       块追加进 prompt；检索不可用/结果为空时完全走原路径（零影响）。
                       约束：只注入面试题生成，**不注入 match_resume**（匹配打分必须可复现）。
                       开关：RAG_ENABLED=1 才启用。**默认 0（关闭）** —— R7 两轮 A/B 实测
                       相关性未提升、token +22~31%，已按执行书回滚接线（模块保留）。
    """
    from openai import AsyncOpenAI

    from .config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
    from . import trace as _trace

    _t0 = time.perf_counter()
    _trace_id = (stats or {}).get("trace_id", "")
    _task_id = (stats or {}).get("task_id", "")

    def _done(result, raw="", finish="", tokens=0, degraded=False, reason="", llm_called=False):
        """写节点 Trace 后返回原结果（行为与埋点前一致）。

        修复（llm_calls 计数 bug）：**由节点自己回报"是否真的调用了 LLM"**，
        不再让编排层用"返回文本是否以某个前缀开头"去猜。
        原实现判的是 "（未配置"（带全角括号），而实际占位文案没有括号 →
        没调 LLM 却被记成 1 次（实测 164/200 条出现 llm_calls>0 但 tokens=0）。
        """
        if stats is not None:
            stats["questions_llm_called"] = bool(llm_called)
        _trace.record(
            _trace_id, _task_id, "generate_interview_questions",
            input_hash=_trace.hash_input(jd_text, resume_text),
            output=result, tokens=tokens,
            latency_ms=(time.perf_counter() - _t0) * 1000,
            degraded=degraded, degrade_reason=reason,
            raw_response=raw, finish_reason=finish,
        )
        return result

    if not DEEPSEEK_API_KEY:
        if structured:
            return _done([{"category": "提示", "difficulty": "初级", "question": "未配置 DEEPSEEK_API_KEY，无法生成面试题", "answer_points": [], "scoring_criteria": ""}],
                         degraded=True, reason="未配置 DEEPSEEK_API_KEY")
        return _done(["（未配置 DEEPSEEK_API_KEY，无法生成面试题）"],
                     degraded=True, reason="未配置 DEEPSEEK_API_KEY")

    client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL, timeout=30.0)

    # ---- 输入块：有结构化上下文时不再塞 JD/简历全文；输出格式按 structured 决定 ----
    if context:
        source_desc = "以下结构性信息"
        source_block = context
        extra_req = ("要求：① 至少 2 题直接针对【缺失技能】考察；"
                     "② 至少 2 题追问【候选人核心经历】中的具体细节（问做法、取舍、结果）；"
                     "③ 覆盖【岗位必须技能】。\n")
    else:
        source_desc = "【岗位JD】和【候选人简历】"
        source_block = f"【岗位JD】\n{jd_text}\n\n【候选人简历】\n{resume_text}"
        extra_req = "要求：问题要结合候选人简历中的经历追问，并覆盖 JD 的核心技能要求。\n"

    if structured:
        format_req = (
            "每道题必须包含：question（问题）、category（技术能力/项目经验/软技能）、"
            "difficulty（初级/中级/高级）、answer_points（3-5 个答题要点）、"
            "scoring_criteria（评分标准说明，如何算合格/优秀）。\n"
            "只输出 JSON 数组，不要输出其它内容，格式如下：\n"
            '[{"category": "技术能力", "difficulty": "中级", "question": "问题内容", '
            '"answer_points": ["要点1", "要点2", "要点3"], '
            '"scoring_criteria": "能说出核心机制得 70%，能结合实际案例得 100%"}, '
            '{"category": "项目经验", "difficulty": "高级", "question": "问题内容", '
            '"answer_points": ["要点1", "要点2"], '
            '"scoring_criteria": "评分说明"}]'
        )
    else:
        format_req = "只输出问题列表，每个问题一行，用 1. 2. 3. 编号，不要其它内容。"

    # ---- R6：只读检索增强（岗位能力参考）----
    # 【默认关闭 —— 由 R7 实测结论决定】
    # 两轮 A/B（同 10 条用例，n=20）：注入后「题目覆盖检索到的能力点」0.33→0.71（提升、可复现），
    # 但 LLM 盲评 7.50→6.70 / 7.20→6.60（合并均值 -0.70，SD 1.35，t=-2.33，10 降 7 平 3 升），
    # 同时 token +22%~31%。按执行书 R7「面试题相关性：持平或提升」判定为**未通过**，
    # 故回滚接线：默认不注入，但**保留整个 RAG 模块**（R1–R5）与开关，便于改设计后复测。
    # 复现实验 / 改注入设计时：设 RAG_ENABLED=1。
    # 另：检索失败/为空时 rag_block 为空串 → prompt 与加 RAG 之前**逐字一致**（可安全降级）。
    # 只在这里注入；match_resume / parse_jd 完全不碰（打分与判定必须可复现）。
    rag_block = ""
    if rag_skills and os.environ.get("RAG_ENABLED", "0") != "0":
        try:
            from .rag.inject import capability_context_for_skills

            _rag = capability_context_for_skills(rag_skills)
            rag_block = (_rag.get("text") or "").strip()
            if stats is not None:
                stats["rag_chars"] = _rag.get("chars", 0)
                stats["rag_chunk_ids"] = list(_rag.get("ids") or [])
                stats["rag_modes"] = list(_rag.get("modes") or [])
        except Exception as _e:                     # 依赖缺失 / 模型不可用 / 索引异常
            rag_block = ""
            if stats is not None:
                stats["rag_error"] = "%s: %s" % (type(_e).__name__, str(_e)[:80])
    rag_section = (rag_block + "\n\n") if rag_block else ""

    prompt = (
        f"你是资深技术面试官。请根据{source_desc}生成 3-5 个有针对性、"
        "能考察候选人是否胜任的面试问题。\n"
        + extra_req
        + source_block + "\n\n"
        + rag_section
        + format_req
    )
    resp = None                    # 用于判定"是否真的收到了模型响应"（= 计一次调用）
    try:
        resp = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
        )
        usage = getattr(resp, "usage", None)
        _call_tokens = getattr(usage, "total_tokens", 0) or 0 if usage is not None else 0
        if stats is not None and usage is not None:
            stats["total_tokens"] += getattr(usage, "total_tokens", 0) or 0
            stats["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
            stats["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0
        content = (resp.choices[0].message.content or "").strip()
        _finish = getattr(resp.choices[0], "finish_reason", "") or ""

        if structured:
            # 提取 JSON 数组（模型可能带 ```json 围栏）
            import json as _json

            m = re.search(r"\[.*\]", content, re.S)
            if m:
                try:
                    arr = _json.loads(m.group())
                    out = []
                    for item in arr[:5]:
                        if isinstance(item, dict) and item.get("question"):
                            points = item.get("answer_points") or []
                            if isinstance(points, str):
                                points = [points]
                            out.append({
                                "category": str(item.get("category", "综合")),
                                "difficulty": str(item.get("difficulty", "中级")),
                                "question": str(item["question"]),
                                "answer_points": [str(p) for p in points][:6],
                                "scoring_criteria": str(item.get("scoring_criteria", "")),
                            })
                    if out:
                        return _done(out, raw=content, finish=_finish, tokens=_call_tokens,
                                     llm_called=True)
                except Exception:
                    pass
            # JSON 解析失败 → 降级为纯文本行
            lines = [re.sub(r"^\s*\d+[.、)]\s*", "", ln.strip()) for ln in content.splitlines() if ln.strip()]
            return _done([{"category": "综合", "difficulty": "中级", "question": q,
                           "answer_points": [], "scoring_criteria": ""} for q in lines[:5]],
                         raw=content, finish=_finish, tokens=_call_tokens,
                         degraded=True, reason="JSON 解析失败，降级为按行切分的纯文本",
                         llm_called=True)          # 收到了模型响应 → 计一次调用

        questions = [ln.strip() for ln in content.splitlines() if ln.strip()]
        cleaned = [re.sub(r"^\s*\d+[.、)]\s*", "", q) for q in questions]
        _res = [q for q in cleaned if q][:5] or ["（模型未返回有效问题）"]
        return _done(_res, raw=content, finish=_finish, tokens=_call_tokens,
                     degraded=(_res == ["（模型未返回有效问题）"]),
                     reason="模型未返回有效问题" if _res == ["（模型未返回有效问题）"] else "",
                     llm_called=True)              # 收到了模型响应 → 计一次调用
    except Exception as e:
        # 收到了响应但后续处理失败时，token 已经计过 → 仍应算一次调用，
        # 保证「tokens>0 ⟺ 计一次调用」这个不变量（老数据里存在 tokens>0 却 llm_calls=0 的行）。
        _called = resp is not None
        if structured:
            return _done([{"category": "错误", "difficulty": "-", "question": f"（面试题生成失败：{e}）",
                           "answer_points": [], "scoring_criteria": ""}],
                         degraded=True, reason=f"{type(e).__name__}: {e}", llm_called=_called)
        return _done([f"（面试题生成失败：{e}）"],
                     degraded=True, reason=f"{type(e).__name__}: {e}", llm_called=_called)


# ---------------------------------------------------------------------------
# 工具 4：summarize_recommendation —— 推荐结论（规则优先，按需调 LLM）
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 第 12 步：结论枚举解析（修 "不推荐" 被解析成 "推荐" 的反转 bug）
# ---------------------------------------------------------------------------
_CONCLUSION_ENUM = ("推荐", "待定", "不推荐")


def parse_conclusion(content: str) -> str:
    """把模型输出收敛到 推荐/待定/不推荐 三个枚举值。

    原实现是 `for c in ("推荐","不推荐","待定"): if c in content[:60]`，
    因为 **"推荐" 是 "不推荐" 的子串**，模型返回"不推荐"时会先命中"推荐" —— 结论直接反转，
    这是最危险的方向（本该拒掉的候选人被推荐）。

    现在的顺序：
      1) 先在「结论：X」处做**精确匹配**（容忍前后 Markdown 符号与标点）
      2) 再按**长度倒序**做子串匹配（"不推荐" 一定先于 "推荐" 判断）
      3) 都匹配不到 → 兜底 "待定"
    """
    text = (content or "").strip()
    head = text[:60]

    # 1) 精确匹配「结论：X」
    m = re.search(r"结论\s*[:：]\s*\**\s*([^\s，。,.；;、\n*]+)", head)
    if m:
        v = m.group(1).strip()
        if v in _CONCLUSION_ENUM:
            return v

    # 2) 长度倒序子串匹配
    for c in ("不推荐", "待定", "推荐"):
        if c in head:
            return c

    # 3) 兜底
    return "待定"


async def summarize_recommendation(
    match_score: int,
    matched_skills: list,
    missing_skills: list,
    questions: list,
    stats: dict = None,
) -> dict:
    """输出推荐结论。

    - 匹配度 ≥80 且缺失必须技能 ≤1：规则直接 "推荐"，零 LLM
    - 匹配度 <50：规则直接 "不推荐"，零 LLM
    - 其他（50-79）：调 LLM 生成结论
    """
    matched = matched_skills or []
    missing = missing_skills or []

    from . import trace as _trace

    _t0 = time.perf_counter()
    _trace_id = (stats or {}).get("trace_id", "")
    _task_id = (stats or {}).get("task_id", "")

    def _done(result, raw="", finish="", tokens=0, degraded=False, reason=""):
        """写节点 Trace 后返回原结果（行为与埋点前完全一致）。"""
        _trace.record(
            _trace_id, _task_id, "summarize_recommendation",
            input_hash=_trace.hash_input(match_score, matched, missing),
            output=result, tokens=tokens,
            latency_ms=(time.perf_counter() - _t0) * 1000,
            degraded=degraded, degrade_reason=reason,
            raw_response=raw, finish_reason=finish,
        )
        return result

    if match_score >= 80 and len(missing) <= MAX_MISSING_REQUIRED_FOR_RECOMMEND:
        reason = (
            f"匹配度 {match_score}%，命中 {'、'.join(matched) or '无'}，"
            + (f"仅缺失 {'、'.join(missing)}。" if missing else "核心要求全覆盖。")
            + "符合岗位核心要求，建议推荐进入投递。"
        )
        return _done({"conclusion": "推荐", "reason": reason, "llm_used": False})

    if match_score < 50:
        reason = (
            f"匹配度仅 {match_score}%，核心技能 {'、'.join(missing) or '未命中'} 缺失，"
            "与岗位要求差距较大，不建议推进。"
        )
        return _done({"conclusion": "不推荐", "reason": reason, "llm_used": False})

    # 中间地带：调 LLM 生成结论
    from openai import AsyncOpenAI

    from .config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

    if not DEEPSEEK_API_KEY:
        return _done({
            "conclusion": "待定",
            "reason": f"匹配度 {match_score}%，介于可推荐区间，需结合面试进一步评估（未配置 API Key，规则兜底）。",
            "llm_used": False,
        }, degraded=True, reason="未配置 DEEPSEEK_API_KEY，中间区间走规则兜底")

    client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL, timeout=30.0)
    prompt = (
        "你是招聘专家。根据以下候选人匹配评估信息，给出推荐结论：只能输出 推荐 / 待定 / 不推荐 三者之一，"
        "并给出一段不超过 3 行的理由。\n"
        f"匹配度：{match_score}%\n命中技能：{'、'.join(matched) or '无'}\n"
        f"缺失技能：{'、'.join(missing) or '无'}\n"
        f"拟面试问题：{'；'.join(questions)}\n"
        "输出格式：\n结论：xxx\n理由：xxx"
    )
    resp = None                    # 用于判定"是否真的收到了模型响应"（= 计一次调用）
    try:
        resp = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        usage = getattr(resp, "usage", None)
        _call_tokens = getattr(usage, "total_tokens", 0) or 0 if usage is not None else 0
        if stats is not None and usage is not None:
            stats["total_tokens"] += getattr(usage, "total_tokens", 0) or 0
            stats["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
            stats["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0
        content = (resp.choices[0].message.content or "").strip()
        _finish = getattr(resp.choices[0], "finish_reason", "") or ""
        # 第 12 步：改用 parse_conclusion（原实现在此处把"不推荐"解析成"推荐"）
        conclusion = parse_conclusion(content)
        reason = ""
        for ln in content.splitlines():
            if ln.strip().startswith("理由"):
                reason = ln.split("：", 1)[-1].strip()
                break
        if not reason:
            reason = content.replace("结论", "").replace(conclusion, "").strip("：: \n")[:150]
        return _done({"conclusion": conclusion, "reason": reason or content[:150], "llm_used": True},
                     raw=content, finish=_finish, tokens=_call_tokens)
    except Exception as e:
        # 同 generate_interview_questions：收到了响应（token 已计）就算一次调用
        return _done({"conclusion": "待定",
                      "reason": f"匹配度 {match_score}%，LLM 汇总失败（{e}），建议人工复核。",
                      "llm_used": resp is not None},
                     degraded=True, reason=f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 工具注册表（保留统一入口）
# ---------------------------------------------------------------------------
TOOLS_MAP = {
    "parse_jd": parse_jd,
    "match_resume": match_resume,
    "generate_interview_questions": generate_interview_questions,
    "summarize_recommendation": summarize_recommendation,
}


def get_tool_names() -> list:
    return list(TOOLS_MAP.keys())
