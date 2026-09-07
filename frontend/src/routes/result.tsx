import { createFileRoute, useNavigate, Link, useRouterState } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { CircularProgress } from "@/components/circular-progress";
import { ResultCard, StatusCard } from "@/components/result-card";
import { SkillTagGroup } from "@/components/skill-tag";
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
  recommendation: { type: string; reason: string };
  llm_calls: number;
  total_tokens: number;
  cache_hit: boolean;
  job_url?: string | null;
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
            title={recTitleMap[recStatus]}
            description={data.recommendation.reason || "暂无理由"}
            reasons={[
              `综合匹配度 ${score}%，命中 ${mr.matched_skills.length} 项技能`,
              mr.missing_skills.length > 0 ? `缺失技能：${mr.missing_skills.slice(0, 3).join("、")}` : "核心技能全覆盖",
              score < 50 ? "匹配度过低，本次未调用 LLM 生成面试题（成本控制）" : `面试题 ${data.interview_questions.length} 题`,
            ]}
          />
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
