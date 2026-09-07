"""招聘 Agent 工具集：JD 多维解析 / 简历加权匹配 / 面试题生成 / 推荐结论。

- parse_jd / match_resume：纯规则，零 LLM（单次解析 <100ms）。
- generate_interview_questions / summarize_recommendation：按需调用 LLM。
"""

import re

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
        if s.lower() in lower:
            all_skills.append(s)
    # 子串去重：若某技能是另一更长已命中技能的子串则丢弃（如 Spring⊂Spring Boot、SQL⊂MySQL）
    deduped_skills = []
    for s in all_skills:
        s_low = s.lower()
        if any(s_low in other.lower() and s != other for other in all_skills):
            continue
        deduped_skills.append(s)
    all_skills = deduped_skills

    required, preferred = [], []
    # 遍历技能所有出现位置：任一处在"必须"语境 → 必须；否则任一在"优先"语境 → 优先
    strong_words = ("必须", "精通", "熟练", "扎实", "硬性", "要求掌握", "必备")
    weak_words = ("优先", "加分", "了解", "熟悉", "掌握更佳", "更好", "如有")
    for s in all_skills:
        s_low = s.lower()
        is_req, is_pref = False, False
        start = 0
        while True:
            idx = lower.find(s_low, start)
            if idx < 0:
                break
            ctx = text[max(0, idx - 25): idx + len(s) + 25]
            if any(w in ctx for w in strong_words):
                is_req = True
                break
            if any(w in ctx for w in weak_words):
                is_pref = True
            start = idx + len(s_low)
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
    """技能命中检测（含否定语境排除）。"""
    lower = resume_text.lower()
    s = skill.lower()
    neg = ("不会", "不懂", "没有", "未接触", "未使用", "没接触", "没用过", "不熟悉",
           "不了解", "缺乏", "缺少", "只有了解", "仅了解", "了解不多", "了解一点",
           "未掌握", "不精通", "刚学", "在学", "学习中", "未曾", "从未", "没用",
           "没怎么用", "不太会", "不怎么会")
    idx = 0
    while True:
        pos = lower.find(s, idx)
        if pos < 0:
            return False
        before = lower[max(0, pos - 12):pos]
        after = lower[pos + len(s):pos + len(s) + 12]
        if any((n in before) or (n in after) for n in neg):
            idx = pos + len(s)
            continue
        return True


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
        match_score = 100
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
# 工具 3：generate_interview_questions —— 面试题生成（调 LLM）
# ---------------------------------------------------------------------------
async def generate_interview_questions(jd_text: str, resume_text: str, stats: dict = None, structured: bool = False):
    """根据 JD + 简历生成 3-5 个针对性面试题。

    structured=False → 返回纯文本问题列表（SSE 用）
    structured=True  → 返回 [{"category","difficulty","question"}]（analyze 用）
    """
    from openai import AsyncOpenAI

    from .config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

    if not DEEPSEEK_API_KEY:
        if structured:
            return [{"category": "提示", "difficulty": "初级", "question": "未配置 DEEPSEEK_API_KEY，无法生成面试题", "answer_points": [], "scoring_criteria": ""}]
        return ["（未配置 DEEPSEEK_API_KEY，无法生成面试题）"]

    client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL, timeout=30.0)
    if structured:
        prompt = (
            "你是资深技术面试官。请根据【岗位JD】和【候选人简历】生成 3-5 个有针对性、"
            "能考察候选人是否胜任的面试问题。\n"
            f"【岗位JD】\n{jd_text}\n\n【候选人简历】\n{resume_text}\n\n"
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
        prompt = (
            "你是资深技术面试官。请根据【岗位JD】和【候选人简历】生成 3-5 个有针对性、"
            "能考察候选人是否胜任的面试问题。\n"
            f"【岗位JD】\n{jd_text}\n\n【候选人简历】\n{resume_text}\n\n"
            "要求：问题要结合候选人简历中的经历追问，并覆盖 JD 的核心技能要求。"
            "只输出问题列表，每个问题一行，用 1. 2. 3. 编号，不要其它内容。"
        )
    try:
        resp = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
        )
        usage = getattr(resp, "usage", None)
        if stats is not None and usage is not None:
            stats["total_tokens"] += getattr(usage, "total_tokens", 0) or 0
            stats["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
            stats["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0
        content = (resp.choices[0].message.content or "").strip()

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
                        return out
                except Exception:
                    pass
            # JSON 解析失败 → 降级为纯文本行
            lines = [re.sub(r"^\s*\d+[.、)]\s*", "", ln.strip()) for ln in content.splitlines() if ln.strip()]
            return [{"category": "综合", "difficulty": "中级", "question": q,
                     "answer_points": [], "scoring_criteria": ""} for q in lines[:5]]

        questions = [ln.strip() for ln in content.splitlines() if ln.strip()]
        cleaned = [re.sub(r"^\s*\d+[.、)]\s*", "", q) for q in questions]
        return [q for q in cleaned if q][:5] or ["（模型未返回有效问题）"]
    except Exception as e:
        if structured:
            return [{"category": "错误", "difficulty": "-", "question": f"（面试题生成失败：{e}）",
                     "answer_points": [], "scoring_criteria": ""}]
        return [f"（面试题生成失败：{e}）"]


# ---------------------------------------------------------------------------
# 工具 4：summarize_recommendation —— 推荐结论（规则优先，按需调 LLM）
# ---------------------------------------------------------------------------
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

    if match_score >= 80 and len(missing) <= 1:
        reason = (
            f"匹配度 {match_score}%，命中 {'、'.join(matched) or '无'}，"
            + (f"仅缺失 {'、'.join(missing)}。" if missing else "核心要求全覆盖。")
            + "符合岗位核心要求，建议推荐进入投递。"
        )
        return {"conclusion": "推荐", "reason": reason, "llm_used": False}

    if match_score < 50:
        reason = (
            f"匹配度仅 {match_score}%，核心技能 {'、'.join(missing) or '未命中'} 缺失，"
            "与岗位要求差距较大，不建议推进。"
        )
        return {"conclusion": "不推荐", "reason": reason, "llm_used": False}

    # 中间地带：调 LLM 生成结论
    from openai import AsyncOpenAI

    from .config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

    if not DEEPSEEK_API_KEY:
        return {
            "conclusion": "待定",
            "reason": f"匹配度 {match_score}%，介于可推荐区间，需结合面试进一步评估（未配置 API Key，规则兜底）。",
            "llm_used": False,
        }

    client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL, timeout=30.0)
    prompt = (
        "你是招聘专家。根据以下候选人匹配评估信息，给出推荐结论：只能输出 推荐 / 待定 / 不推荐 三者之一，"
        "并给出一段不超过 3 行的理由。\n"
        f"匹配度：{match_score}%\n命中技能：{'、'.join(matched) or '无'}\n"
        f"缺失技能：{'、'.join(missing) or '无'}\n"
        f"拟面试问题：{'；'.join(questions)}\n"
        "输出格式：\n结论：xxx\n理由：xxx"
    )
    try:
        resp = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        usage = getattr(resp, "usage", None)
        if stats is not None and usage is not None:
            stats["total_tokens"] += getattr(usage, "total_tokens", 0) or 0
            stats["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
            stats["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0
        content = (resp.choices[0].message.content or "").strip()
        conclusion = "待定"
        for c in ("推荐", "不推荐", "待定"):
            if c in content[:60]:
                conclusion = c
                break
        reason = ""
        for ln in content.splitlines():
            if ln.strip().startswith("理由"):
                reason = ln.split("：", 1)[-1].strip()
                break
        if not reason:
            reason = content.replace("结论", "").replace(conclusion, "").strip("：: \n")[:150]
        return {"conclusion": conclusion, "reason": reason or content[:150], "llm_used": True}
    except Exception as e:
        return {"conclusion": "待定", "reason": f"匹配度 {match_score}%，LLM 汇总失败（{e}），建议人工复核。", "llm_used": False}


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
