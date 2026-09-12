import { useState } from "react";
import { HelpCircle, Loader2, AlertCircle, Send, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export interface AskAnswer {
  question: string;
  answer: string;
}

interface AskCardProps {
  /** 后端追问分支返回的问题（1–3 条） */
  questions: string[];
  /** 当前是第几轮追问 */
  round?: number;
  /** 追问轮数上限（后端 ROUND_LIMIT，默认 2） */
  roundLimit?: number;
  /** 判定为信息不足的原因（缺失了哪些字段） */
  reason?: string;
  /** true = 追问已达上限（insufficient_final），此时不再展示输入框 */
  final?: boolean;
  submitting?: boolean;
  error?: string;
  onSubmit: (answers: AskAnswer[]) => void;
  onBack?: () => void;
}

/**
 * Agent 追问卡片（A3/A4 的前端落地）。
 *
 * 后端判定 JD 信息不足时会提前返回 `status=need_more_info` + `ask.questions`（不消耗 LLM）；
 * 这里把问题渲染成可填写的输入框，HR 提交后由父组件带 `answers` 重新请求同一 session_id。
 */
export function AskCard({
  questions,
  round,
  roundLimit = 2,
  reason,
  final = false,
  submitting = false,
  error = "",
  onSubmit,
  onBack,
}: AskCardProps) {
  const [answers, setAnswers] = useState<string[]>(() => questions.map(() => ""));

  const filled = answers.map((a) => a.trim()).filter(Boolean).length;
  const canSubmit = !submitting && filled > 0 && questions.length > 0;

  const handleSubmit = () => {
    onSubmit(
      questions.map((q, i) => ({ question: q, answer: (answers[i] ?? "").trim() })).filter((a) => a.answer)
    );
  };

  return (
    <div className="rounded-xl border border-amber-300/60 bg-amber-50/50 p-6 space-y-5 reveal">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 w-9 h-9 rounded-lg bg-amber-100 flex items-center justify-center shrink-0">
          <HelpCircle className="w-5 h-5 text-amber-600" />
        </div>
        <div className="space-y-1">
          <h2 className="text-base font-semibold text-foreground">
            {final ? "岗位信息不足，已转人工复核" : "岗位信息不足，需要你补充几点"}
          </h2>
          <p className="text-sm text-muted-foreground">
            {final
              ? `已追问 ${roundLimit} 轮仍未补全关键信息，结论暂记「待定」，请补充 JD 后重新匹配。`
              : `当前第 ${round ?? 1} / ${roundLimit} 轮追问。补充后系统会重新解析 JD 并继续匹配。`}
            {reason ? `（判定原因：${reason}）` : ""}
          </p>
        </div>
      </div>

      {!final && questions.length > 0 && (
        <div className="space-y-4">
          {questions.map((q, i) => (
            <div key={i} className="space-y-2">
              <label className="text-sm font-medium text-foreground" htmlFor={`ask-${i}`}>
                {i + 1}. {q}
              </label>
              <Textarea
                id={`ask-${i}`}
                rows={2}
                value={answers[i] ?? ""}
                placeholder="请补充说明（留空表示该项暂不提供）"
                disabled={submitting}
                onChange={(e) => {
                  const next = [...answers];
                  next[i] = e.target.value;
                  setAnswers(next);
                }}
              />
            </div>
          ))}
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2 text-sm text-red-600">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="flex items-center gap-3">
        {!final && (
          <Button onClick={handleSubmit} disabled={!canSubmit} className="gap-2">
            {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            {submitting ? "重新匹配中…" : "提交补充并重新匹配"}
          </Button>
        )}
        {onBack && (
          <Button variant="outline" onClick={onBack} className="gap-2">
            <RotateCcw className="w-4 h-4" />
            返回修改 JD
          </Button>
        )}
        {!final && (
          <span className="text-xs text-muted-foreground">
            至少填 1 项才能提交（已填 {filled}/{questions.length}）
          </span>
        )}
      </div>
    </div>
  );
}
