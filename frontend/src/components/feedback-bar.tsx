import { useState } from "react";
import { ThumbsUp, PencilLine, MessageSquare, Loader2, CheckCircle2, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { API_BASE } from "@/lib/api";

const CONCLUSIONS = ["推荐", "待定", "不推荐"] as const;
type Conclusion = (typeof CONCLUSIONS)[number];

interface FeedbackBarProps {
  /** 后端 /api/agent/analyze 返回的 task_id；缺失时禁用反馈（例如旧的历史结果） */
  taskId?: string | null;
  /** 系统原本给出的结论，用于展示改判方向 */
  originalConclusion: string;
}

type Status = "idle" | "submitting" | "done" | "error";

export function FeedbackBar({ taskId, originalConclusion }: FeedbackBarProps) {
  const [status, setStatus] = useState<Status>("idle");
  const [message, setMessage] = useState("");
  const [recorded, setRecorded] = useState("");

  const [rejudgeOpen, setRejudgeOpen] = useState(false);
  const [commentOpen, setCommentOpen] = useState(false);
  const [comment, setComment] = useState("");

  const disabled = !taskId || status === "submitting";

  async function submit(action: "采纳" | "改判" | "反馈", newConclusion = "", cmt = "") {
    if (!taskId) return;
    setStatus("submitting");
    setMessage("");
    try {
      const resp = await fetch(`${API_BASE}/api/agent/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_id: taskId,
          action,
          new_conclusion: newConclusion,
          comment: cmt,
        }),
      });
      const body = (await resp.json().catch(() => ({}))) as Record<string, unknown>;
      if (!resp.ok) {
        setStatus("error");
        setMessage(String(body.detail ?? body.message ?? `请求失败（HTTP ${resp.status}）`));
        return;
      }
      setStatus("done");
      setRecorded(
        action === "改判"
          ? `已记录改判：${originalConclusion || "原结论"} → ${newConclusion}`
          : `已记录：${action}`,
      );
      setRejudgeOpen(false);
      setCommentOpen(false);
      setComment("");
    } catch (e) {
      setStatus("error");
      setMessage(e instanceof Error ? e.message : "网络异常，请稍后重试");
    }
  }

  return (
    <div className="mt-3 rounded-xl border border-border bg-card p-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <MessageSquare className="h-4 w-4" />
          <span>这个结论对你有帮助吗？你的反馈会回流到评测集，用于优化匹配规则。</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={disabled}
            onClick={() => submit("采纳")}
            className="gap-1.5"
          >
            <ThumbsUp className="h-3.5 w-3.5" />
            采纳
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={disabled}
            onClick={() => setRejudgeOpen(true)}
            className="gap-1.5"
          >
            <PencilLine className="h-3.5 w-3.5" />
            改判
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={disabled}
            onClick={() => setCommentOpen(true)}
            className="gap-1.5"
          >
            <MessageSquare className="h-3.5 w-3.5" />
            反馈
          </Button>
        </div>
      </div>

      {status === "submitting" && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> 正在提交…
        </p>
      )}
      {status === "done" && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-[var(--success)]">
          <CheckCircle2 className="h-3.5 w-3.5" /> {recorded}
        </p>
      )}
      {status === "error" && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-[var(--danger)]">
          <AlertCircle className="h-3.5 w-3.5" /> {message}
        </p>
      )}
      {!taskId && (
        <p className="mt-2 text-xs text-muted-foreground">
          该结果缺少 task_id（可能来自升级前的历史记录），暂时无法提交反馈。
        </p>
      )}

      {/* 改判弹窗：选择新结论 */}
      <Dialog open={rejudgeOpen} onOpenChange={setRejudgeOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>改判结论</DialogTitle>
            <DialogDescription>
              系统原结论为「{originalConclusion || "未知"}」，请选择你认为正确的结论。
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2 py-2">
            {CONCLUSIONS.map((c) => (
              <Button
                key={c}
                variant={c === originalConclusion ? "secondary" : "outline"}
                disabled={status === "submitting"}
                onClick={() => submit("改判", c)}
                className="justify-start"
              >
                {c}
                {c === originalConclusion && (
                  <span className="ml-2 text-xs text-muted-foreground">（与原结论一致）</span>
                )}
              </Button>
            ))}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRejudgeOpen(false)}>
              取消
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 反馈弹窗：文字说明 */}
      <Dialog open={commentOpen} onOpenChange={setCommentOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>补充反馈</DialogTitle>
            <DialogDescription>写下你的意见（例如：技能识别不准、结论偏严）。</DialogDescription>
          </DialogHeader>
          <Textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="例如：简历里的 Kubernetes 没被识别出来"
            rows={4}
          />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCommentOpen(false)}>
              取消
            </Button>
            <Button disabled={status === "submitting" || !comment.trim()} onClick={() => submit("反馈", "", comment)}>
              提交
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
