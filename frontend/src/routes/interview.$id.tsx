import { createFileRoute, Link, useRouterState } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  HelpCircle,
  Lightbulb,
  ArrowLeft,
  ChevronLeft,
  ListChecks,
  Gauge,
} from "lucide-react";

export const Route = createFileRoute("/interview/$id")({
  component: InterviewDetailPage,
});

// 面试题数据（含参考答案要点与评分标准）
export interface QuestionItem {
  category?: string;
  difficulty?: string;
  question: string;
  answer_points?: string[];
  scoring_criteria?: string;
}

function InterviewDetailPage() {
  // 从结果页路由 state 读取问题数据（结果页已持久化，返回时自动恢复）
  const location = useRouterState({ select: (s) => s.location });
  const stateData = (location.state as any) || {};
  const question = stateData.question as QuestionItem | undefined;
  const index = (stateData.index as number | undefined) ?? 0;

  const answerPoints = question?.answer_points ?? [];
  const hasAnswer = answerPoints.length > 0 || !!question?.scoring_criteria;

  if (!question) {
    return (
      <div className="min-h-screen bg-background flex flex-col items-center justify-center">
        <p className="text-muted-foreground mb-4">未获取到面试题数据，请从结果页进入</p>
        <Link to="/result">
          <Button>返回结果页</Button>
        </Link>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background pb-20">
      {/* Header */}
      <div className="sticky top-16 z-40 bg-background/80 backdrop-blur-md border-b border-border/50">
        <div className="container mx-auto px-4 py-4 max-w-3xl">
          <div className="flex items-center gap-4">
            <Link to="/result">
              <Button variant="ghost" size="sm" className="gap-2">
                <ChevronLeft className="w-4 h-4" />
                返回结果
              </Button>
            </Link>
            <div className="h-6 w-px bg-border" />
            <h1 className="text-lg font-semibold text-foreground">面试题详情</h1>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <main className="container mx-auto px-4 py-8 max-w-3xl">
        <div className="space-y-6 reveal">
          {/* 问题卡片 */}
          <Card className="border-primary/20">
            <CardContent className="p-6">
              <div className="flex items-start gap-4">
                <div className="flex items-center justify-center w-10 h-10 rounded-full bg-gradient-to-br from-[var(--tech-blue)] to-[var(--tech-indigo)] text-white">
                  <HelpCircle className="w-5 h-5" />
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                    <p className="text-sm text-muted-foreground">面试问题 {index + 1}</p>
                    {question.category && (
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
                        {question.category}
                      </span>
                    )}
                    {question.difficulty && (
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">
                        {question.difficulty}
                      </span>
                    )}
                  </div>
                  <h2 className="text-lg font-semibold text-foreground leading-relaxed">
                    {question.question}
                  </h2>
                </div>
              </div>
            </CardContent>
          </Card>

          {hasAnswer ? (
            <>
              {/* 答题要点 */}
              {answerPoints.length > 0 && (
                <Card className="bg-muted/30 border-muted">
                  <CardContent className="p-6">
                    <div className="flex items-start gap-4">
                      <div className="flex items-center justify-center w-10 h-10 rounded-full bg-[var(--tech-blue)]/10 text-[var(--tech-blue)]">
                        <ListChecks className="w-5 h-5" />
                      </div>
                      <div className="flex-1">
                        <p className="text-sm text-muted-foreground mb-3">参考答案要点</p>
                        <ul className="space-y-2.5">
                          {answerPoints.map((point, i) => (
                            <li key={i} className="flex items-start gap-2.5">
                              <span className="mt-1.5 w-5 h-5 rounded-full bg-[var(--tech-blue)]/10 text-[var(--tech-blue)] text-xs font-bold flex items-center justify-center shrink-0">
                                {i + 1}
                              </span>
                              <span className="text-sm text-foreground/90 leading-relaxed">
                                {point}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* 评分标准 */}
              {question.scoring_criteria && (
                <Card className="bg-[var(--warning)]/5 border-[var(--warning)]/20">
                  <CardContent className="p-6">
                    <div className="flex items-start gap-4">
                      <div className="flex items-center justify-center w-10 h-10 rounded-full bg-[var(--warning)]/10 text-amber-600">
                        <Gauge className="w-5 h-5" />
                      </div>
                      <div className="flex-1">
                        <p className="text-sm text-muted-foreground mb-1">评分标准</p>
                        <p className="text-sm text-foreground/90 leading-relaxed">
                          {question.scoring_criteria}
                        </p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )}
            </>
          ) : (
            <Card className="bg-muted/30 border-muted">
              <CardContent className="p-6">
                <div className="flex items-start gap-4">
                  <div className="flex items-center justify-center w-10 h-10 rounded-full bg-[var(--success)]/10 text-[var(--success)]">
                    <Lightbulb className="w-5 h-5" />
                  </div>
                  <div className="flex-1">
                    <p className="text-sm text-muted-foreground mb-1">考察方向</p>
                    <p className="text-foreground leading-relaxed">
                      该题用于考察候选人在 {question.category || "岗位核心技能"} 方向的实际能力。
                      建议结合候选人简历中的具体项目经历追问细节、遇到的难点与解决思路。
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* 提示 */}
          <div className="p-4 rounded-xl bg-muted/30 text-sm text-muted-foreground">
            <p>💡 提示：参考答案要点供面试官参考，实际面试中应根据候选人的回答灵活调整追问方向。</p>
          </div>

          {/* 返回按钮 */}
          <div className="flex items-center justify-center pt-6">
            <Link to="/result">
              <Button variant="outline" className="gap-2">
                <ArrowLeft className="w-4 h-4" />
                返回结果页
              </Button>
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}
