import { createFileRoute, useNavigate, Link, useRouterState } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { CircularProgress } from "@/components/circular-progress";
import { ResultCard, StatusCard } from "@/components/result-card";
import { SkillTagGroup } from "@/components/skill-tag";
import { FeedbackBar } from "@/components/feedback-bar";
import { AskCard, type AskAnswer } from "@/components/ask-card";
import { API_BASE, getSessionId } from "@/lib/api";
import {
  Briefcase,
  Target,
  HelpCircle,
  CheckCircle,
  ChevronLeft,
  Building2,
  Award,
  Clock,
  GraduationCap,
  Users,
  Star,
  RotateCcw,
  ArrowRight,
  Send,
  Mail,
  XCircle,
  Lightbulb,
  AlertCircle,
} from "lucide-react";

export const Route = createFileRoute("/result")({
  component: ResultPage,
});

// 与后端 /api/agent/analyze 返回结构对应
export interface AnalyzeResult {
  jd_parse: {
    position: string;
    department: string;
    level: string;
    work_mode: string;
    responsibilities: string[];
    skills: { required: string[]; preferred: string[] };
    experience: { min_years: number; max_years: number; industry: string[]; project_type?: string[] };
    education: { level: string; major: string; is_strict: boolean };
    soft_skills: string[];
    bonus: string[];
  };
  match_result: {
    score: number;
    dimensions: {
      skills: number;
      experience: number;
      education: number;
      soft_skills: number;
      bonus: number;
    };
    matched_skills: string[];
    missing_skills: string[];
    bonus_skills: string[];
    summary: string;
  };
  interview_questions: Array<{
    category: string;
    difficulty: string;
    question: string;
    answer_points?: string[];
    scoring_criteria?: string;
  }>;
  recommendation: { type: string; reason: string; label?: string; role?: string };
  llm_calls: number;
  total_tokens: number;
  cache_hit: boolean;
  job_url?: string | null;
  /** 第 5/7 步新增：反馈接口按 task_id 定位本次分析 */
  task_id?: string;
  trace_id?: string;
  /** A4/A5：追问分支的响应状态（need_more_info / insufficient_final）；正常分析无此字段 */
  status?: string;
  ask?: {
    questions?: string[];
    round?: number;
    round_limit?: number;
    reason?: string;
    missing_fields?: string[];
  };
}

/** A4：追问续接要带原始 JD/简历（route state 优先，刷新后从 sessionStorage 取回） */
export const RESULT_INPUT_KEY = "lastAnalyzeInput";
interface AnalyzeInput {
  jd: string;
  resume: string;
  job_url?: string | null;
  role?: "hr" | "candidate";
}

function readStoredInput(): AnalyzeInput | null {
  try {
    const stored = sessionStorage.getItem(RESULT_INPUT_KEY);
    return stored ? (JSON.parse(stored) as AnalyzeInput) : null;
  } catch {
    return null;
  }
}

// 结果持久化（跳详情页返回不丢失）
export const RESULT_STORAGE_KEY = "lastAnalyzeResult";

function readStoredResult(): AnalyzeResult | null {
  try {
    const stored = sessionStorage.getItem(RESULT_STORAGE_KEY);
    return stored ? (JSON.parse(stored) as AnalyzeResult) : null;
  } catch {
    return null;
  }
}

function ResultPage() {
  const navigate = useNavigate();
  // 路由 state 优先（新匹配结果），无 state 时从 sessionStorage 恢复（详情页返回）
  const location = useRouterState({ select: (s) => s.location });
  const routeData = (location.state as any)?.result as AnalyzeResult | null;
  const [data, setData] = useState<AnalyzeResult | null>(() => routeData || readStoredResult());

  // A4：追问续接所需的原始输入（新匹配走 route state，刷新后用 sessionStorage）
  const routeState = (location.state ?? null) as any;
  const [input] = useState<AnalyzeInput | null>(() =>
    routeState?.jd
      ? { jd: routeState.jd, resume: routeState.resume ?? "", role: routeState.role }
      : readStoredInput()
  );
  useEffect(() => {
    if (input) {
      try {
        sessionStorage.setItem(RESULT_INPUT_KEY, JSON.stringify(input));
      } catch {
        /* 忽略存储失败 */
      }
    }
  }, [input]);

  // A4：把 HR 的补充回答提交回同一 session，后端合并进 JD 后重走 parse_jd 之后的链路
  const [askSubmitting, setAskSubmitting] = useState(false);
  const [askError, setAskError] = useState("");

  const submitAnswers = async (answers: AskAnswer[]) => {
    if (!input) {
      setAskError("缺少原始 JD/简历，请返回输入页重新匹配");
      return;
    }
    setAskSubmitting(true);
    setAskError("");
    try {
      const resp = await fetch(`${API_BASE}/api/agent/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jd: input.jd,
          resume: input.resume,
          job_url: input.job_url ?? null,
          tenant_id: "default",
          session_id: getSessionId(),
          role: input.role ?? "hr",
          answers,
        }),
      });
      const body = (await resp.json().catch(() => ({}))) as AnalyzeResult & { detail?: string };
      if (!resp.ok) throw new Error(body.detail || `请求失败（HTTP ${resp.status}）`);
      setData(body);
    } catch (err: any) {
      setAskError(err?.message || "网络错误，请稍后重试");
    } finally {
      setAskSubmitting(false);
    }
  };

  // 有数据时写入 sessionStorage（新匹配覆盖旧数据；详情页返回用）
  useEffect(() => {
    if (data) {
      try {
        sessionStorage.setItem(RESULT_STORAGE_KEY, JSON.stringify(data));
      } catch {
        /* 忽略存储失败 */
      }
    }
  }, [data]);

  const handleReset = () => {
    // 重新匹配：清空持久化结果
    try {
      sessionStorage.removeItem(RESULT_STORAGE_KEY);
    } catch {
      /* 忽略 */
    }
    navigate({ to: "/match" });
  };

  if (!data) {
    return (
      <div className="min-h-screen bg-background flex flex-col items-center justify-center">
        <p className="text-muted-foreground mb-4">暂无匹配结果，请先执行匹配</p>
        <button
          onClick={handleReset}
          className="px-6 py-2.5 rounded-lg bg-[var(--tech-blue)] text-white hover:opacity-90"
        >
          去输入信息
        </button>
      </div>
    );
  }

  // ---- A4/A5：追问分支 ----
  // 后端判定 JD 信息不足时会提前返回（此时**没有** match_result），
  // 若继续走下面的打分渲染会因 mr.dimensions 为空而崩，所以这里先分流。
  if (data.status === "need_more_info" || data.status === "insufficient_final") {
    const isFinal = data.status === "insufficient_final";
    return (
      <div className="min-h-screen bg-background pb-20">
        <div className="sticky top-16 z-40 bg-background/80 backdrop-blur-md border-b border-border/50">
          <div className="container mx-auto px-4 py-4 max-w-3xl flex items-center gap-4">
            <button
              onClick={handleReset}
              className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
            >
              <ChevronLeft className="w-4 h-4" />
              返回输入
            </button>
            <div className="h-6 w-px bg-border" />
            <h1 className="text-lg font-semibold text-foreground">
              {isFinal ? "待人工复核" : "需要补充岗位信息"}
            </h1>
            <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">零 LLM</span>
          </div>
        </div>
        <main className="container mx-auto px-4 py-8 max-w-3xl space-y-6">
          <AskCard
            questions={data.ask?.questions ?? []}
            round={data.ask?.round}
            roundLimit={data.ask?.round_limit ?? 2}
            reason={data.ask?.reason}
            final={isFinal}
            submitting={askSubmitting}
            error={askError}
            onSubmit={submitAnswers}
            onBack={handleReset}
          />
        </main>
      </div>
    );
  }

  const jd = data.jd_parse;
  const mr = data.match_result;
  const dims = mr.dimensions;
  const score = mr.score;

  // 推荐结论颜色映射（绿/黄/红）
  const recMap: Record<string, "recommended" | "pending" | "rejected"> = {
    推荐: "recommended",
    待定: "pending",
    不推荐: "rejected",
  };
  const recStatus = recMap[data.recommendation.type] || "pending";
  const recTitleMap = { recommended: "推荐", pending: "待定", rejected: "不推荐" };
  // 第 10 步：后端按 role 给出的展示文案（求职者版为"高匹配，建议投递"等）；
  // 缺省回退到 HR 文案，保证旧结果也能正常显示。
  const recTitle = data.recommendation.label || recTitleMap[recStatus];

  // 点击面试题 → 跳详情页（路由 state 携带问题）
  const handleQuestionClick = (index: number) => {
    const q = data.interview_questions[index];
    navigate({
      to: "/interview/$id",
      params: { id: String(index) },
      state: { question: q, index },
    });
  };

  const summaryLines = mr.summary ? mr.summary.split("；").filter(Boolean) : [];

  return (
    <div className="min-h-screen bg-background pb-20">
      {/* Header */}
      <div className="sticky top-16 z-40 bg-background/80 backdrop-blur-md border-b border-border/50">
        <div className="container mx-auto px-4 py-4 max-w-5xl">
          <div className="flex items-center gap-4">
            <Link to="/match">
              <button className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
                <ChevronLeft className="w-4 h-4" />
                返回输入
              </button>
            </Link>
            <div className="h-6 w-px bg-border" />
            <h1 className="text-lg font-semibold text-foreground">匹配结果</h1>
            {data.cache_hit && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700">⚡ 缓存命中</span>
            )}
            {data.llm_calls === 0 && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">零 LLM</span>
            )}
          </div>
        </div>
      </div>

      {/* Main Content */}
      <main className="container mx-auto px-4 py-8 max-w-5xl space-y-6">
        {/* JD 解析结果 */}
        <ResultCard title="JD 解析结果" icon={<Briefcase className="w-4 h-4" />} className="reveal">
          <div className="grid md:grid-cols-2 gap-6">
            {/* 基本信息 */}
            <div className="space-y-4">
              <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/50">
                <Building2 className="w-5 h-5 text-primary" />
                <div>
                  <p className="text-xs text-muted-foreground">职位</p>
                  <p className="font-medium">{jd.position || "未识别"}</p>
                </div>
              </div>
              <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/50">
                <Award className="w-5 h-5 text-primary" />
                <div>
                  <p className="text-xs text-muted-foreground">级别</p>
                  <p className="font-medium">{jd.level || "未识别"}</p>
                </div>
              </div>
              <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/50">
                <Clock className="w-5 h-5 text-primary" />
                <div>
                  <p className="text-xs text-muted-foreground">工作模式</p>
                  <p className="font-medium">{jd.work_mode || "未识别"}</p>
                </div>
              </div>
              {jd.department && (
                <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/50">
                  <Users className="w-5 h-5 text-primary" />
                  <div>
                    <p className="text-xs text-muted-foreground">部门</p>
                    <p className="font-medium">{jd.department}</p>
                  </div>
                </div>
              )}
            </div>

            {/* 技能要求 */}
            <div className="space-y-4">
              {jd.skills.required.length > 0 && (
                <div>
                  <p className="text-sm font-medium text-foreground mb-2 flex items-center gap-2">
                    <Target className="w-4 h-4 text-primary" />
                    必须技能
                  </p>
                  <SkillTagGroup skills={jd.skills.required} type="required" />
                </div>
              )}
              {jd.skills.preferred.length > 0 && (
                <div>
                  <p className="text-sm font-medium text-foreground mb-2 flex items-center gap-2">
                    <Star className="w-4 h-4 text-muted-foreground" />
                    优先技能
                  </p>
                  <SkillTagGroup skills={jd.skills.preferred} type="preferred" />
                </div>
              )}
              {jd.soft_skills.length > 0 && (
                <div>
                  <p className="text-sm font-medium text-foreground mb-2">软技能</p>
                  <div className="flex flex-wrap gap-2">
                    {jd.soft_skills.map((s) => (
                      <span key={s} className="px-2.5 py-1 text-xs rounded-full bg-violet-100 text-violet-700">
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* 职责 / 经验 / 学历 */}
          <div className="grid md:grid-cols-3 gap-4 mt-6 pt-6 border-t border-border">
            {jd.responsibilities.length > 0 && (
              <div className="flex items-start gap-3">
                <HelpCircle className="w-5 h-5 text-primary mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-foreground">岗位职责</p>
                  <p className="text-sm text-muted-foreground">
                    {jd.responsibilities.slice(0, 3).join("；") || "未识别"}
                  </p>
                </div>
              </div>
            )}
            <div className="flex items-start gap-3">
              <Clock className="w-5 h-5 text-primary mt-0.5" />
              <div>
                <p className="text-sm font-medium text-foreground">经验要求</p>
                <p className="text-sm text-muted-foreground">
                  {jd.experience.min_years
                    ? `${jd.experience.min_years}${jd.experience.max_years ? "-" + jd.experience.max_years : "+"} 年`
                    : "未指定"}
                  {jd.experience.industry.length > 0 ? ` | ${jd.experience.industry.join("、")}` : ""}
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <GraduationCap className="w-5 h-5 text-primary mt-0.5" />
              <div>
                <p className="text-sm font-medium text-foreground">学历要求</p>
                <p className="text-sm text-muted-foreground">
                  {jd.education.level || "不限"} | {jd.education.major || "不限"}
                  {jd.education.is_strict && " (硬性要求)"}
                </p>
              </div>
            </div>
          </div>
        </ResultCard>

        {/* 匹配结果 */}
        <ResultCard title="简历匹配结果" icon={<Target className="w-4 h-4" />} className="reveal">
          <div className="flex flex-col md:flex-row items-center gap-8">
            {/* 综合匹配度 */}
            <div className="flex flex-col items-center">
              <CircularProgress value={score} size={140} strokeWidth={10} label="综合匹配度" />
            </div>

            {/* 分项得分 */}
            <div className="flex-1 grid grid-cols-2 md:grid-cols-3 gap-4">
              <div className="text-center p-4 rounded-xl bg-muted/50">
                <p className="text-2xl font-bold text-primary">{dims.skills}%</p>
                <p className="text-xs text-muted-foreground mt-1">技能匹配</p>
              </div>
              <div className="text-center p-4 rounded-xl bg-muted/50">
                <p className="text-2xl font-bold text-primary">{dims.experience}%</p>
                <p className="text-xs text-muted-foreground mt-1">经验匹配</p>
              </div>
              <div className="text-center p-4 rounded-xl bg-muted/50">
                <p className="text-2xl font-bold text-primary">{dims.education}%</p>
                <p className="text-xs text-muted-foreground mt-1">学历匹配</p>
              </div>
              <div className="text-center p-4 rounded-xl bg-muted/50">
                <p className="text-2xl font-bold text-primary">{dims.soft_skills}%</p>
                <p className="text-xs text-muted-foreground mt-1">软技能</p>
              </div>
              <div className="text-center p-4 rounded-xl bg-muted/50">
                <p className="text-2xl font-bold text-primary">{dims.bonus}%</p>
                <p className="text-xs text-muted-foreground mt-1">加分项</p>
              </div>
            </div>
          </div>

          {/* 技能对比 */}
          <div className="mt-6 pt-6 border-t border-border grid md:grid-cols-2 gap-6">
            {mr.matched_skills.length > 0 && (
              <div>
                <p className="text-sm font-medium text-foreground mb-2 flex items-center gap-2">
                  <CheckCircle className="w-4 h-4 text-[var(--success)]" />
                  命中技能 ({mr.matched_skills.length})
                </p>
                <SkillTagGroup skills={mr.matched_skills} type="matched" showIcons />
              </div>
            )}
            {mr.missing_skills.length > 0 && (
              <div>
                <p className="text-sm font-medium text-foreground mb-2 flex items-center gap-2">
                  <XCircle className="w-4 h-4 text-[var(--danger)]" />
                  缺失技能 ({mr.missing_skills.length})
                </p>
                <SkillTagGroup skills={mr.missing_skills} type="missing" showIcons />
              </div>
            )}
          </div>

          {summaryLines.length > 0 && (
            <p className="text-xs text-muted-foreground mt-4">{summaryLines.join(" | ")}</p>
          )}
        </ResultCard>

        {/* 面试题 */}
        {data.interview_questions.length > 0 && (
          <ResultCard title="面试题推荐" icon={<HelpCircle className="w-4 h-4" />} className="reveal">
            <div className="space-y-3">
              {data.interview_questions.map((item, i) => (
                <div
                  key={i}
                  onClick={() => handleQuestionClick(i)}
                  className="flex items-center justify-between p-4 rounded-xl bg-muted/30 hover:bg-muted/50 transition-colors cursor-pointer group"
                >
                  <div className="flex items-start gap-3 flex-1">
                    <div className="flex items-center justify-center w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-bold shrink-0">
                      {i + 1}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="text-[11px] px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
                          {item.category || "综合"}
                        </span>
                        <span className="text-[11px] px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">
                          {item.difficulty || "中级"}
                        </span>
                      </div>
                      <p className="text-sm text-foreground">{item.question}</p>
                    </div>
                  </div>
                  <ArrowRight className="w-5 h-5 text-muted-foreground group-hover:text-primary group-hover:translate-x-1 transition-all shrink-0" />
                </div>
              ))}
            </div>
            <p className="text-xs text-muted-foreground mt-4">点击面试题查看参考答案</p>
          </ResultCard>
        )}

        {/* 推荐结论 */}
        <div className="reveal">
          <StatusCard
            status={recStatus}
            title={recTitle}
            description={data.recommendation.reason || "暂无理由"}
            reasons={[
              `综合匹配度 ${score}%，命中 ${mr.matched_skills.length} 项技能`,
              mr.missing_skills.length > 0 ? `缺失技能：${mr.missing_skills.slice(0, 3).join("、")}` : "核心技能全覆盖",
              score < 50 ? "匹配度过低，本次未调用 LLM 生成面试题（成本控制）" : `面试题 ${data.interview_questions.length} 题`,
            ]}
          />
          {/* 第 8 步：采纳 / 改判 / 反馈（回流评测集） */}
          <FeedbackBar taskId={data.task_id} originalConclusion={data.recommendation.type} />
        </div>

        {/* 投递简历通道 - 仅匹配度 ≥50 显示 */}
        {score >= 50 && (
          <div className="reveal">
            <ResultCard
              title="投递简历"
              icon={<Send className="w-4 h-4" />}
              className="border-[var(--success)]/30 bg-gradient-to-br from-[var(--success)]/5 to-[var(--success)]/10"
            >
              <div className="flex flex-col md:flex-row items-center justify-between gap-4">
                <div className="flex items-center gap-4">
                  <div className="flex items-center justify-center w-12 h-12 rounded-full bg-[var(--success)]/10 text-[var(--success)]">
                    <Mail className="w-6 h-6" />
                  </div>
                  <div>
                    <h4 className="text-lg font-semibold text-foreground">
                      该岗位与您的匹配度达标
                    </h4>
                    <p className="text-sm text-muted-foreground">
                      {data.job_url
                        ? `综合匹配度 ${score}%，点击下方按钮前往原岗位投递`
                        : "综合匹配度达标，但未填写岗位链接"}
                    </p>
                  </div>
                </div>
                {data.job_url ? (
                  <Button
                    onClick={() => window.open(data.job_url!, "_blank")}
                    className="bg-[var(--success)] hover:bg-[var(--success)]/90 text-white px-8"
                  >
                    <Send className="w-4 h-4 mr-2" />
                    投递简历
                  </Button>
                ) : (
                  <Button disabled className="px-8 opacity-50 cursor-not-allowed">
                    <Send className="w-4 h-4 mr-2" />
                    投递简历
                  </Button>
                )}
              </div>
              {!data.job_url && (
                <p className="text-xs text-amber-600 mt-3 flex items-center gap-1">
                  <AlertCircle className="w-3 h-3" />
                  未填写岗位链接，无法投递
                </p>
              )}
            </ResultCard>
          </div>
        )}

        {/* 重新匹配按钮 */}
        <div className="flex items-center justify-center gap-4 pt-6 reveal">
          <button
            onClick={handleReset}
            className="flex items-center gap-2 px-6 py-2.5 rounded-lg border border-border text-foreground hover:bg-muted transition-colors"
          >
            <RotateCcw className="w-4 h-4 mr-2" />
            重新匹配
          </button>
          {data.llm_calls > 0 && (
            <span className="text-xs text-muted-foreground flex items-center gap-1">
              <Lightbulb className="w-3 h-3" />
              LLM 调用 {data.llm_calls} 次 · {data.total_tokens} tokens
            </span>
          )}
        </div>
      </main>
    </div>
  );
}
