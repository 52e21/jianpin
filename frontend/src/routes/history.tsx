import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { API_BASE } from "@/lib/api";
import {
  Search,
  Trash2,
  History,
  ChevronLeft,
  ChevronRight,
  FileText,
  Calendar,
  Target,
  ArrowLeft,
  RefreshCw,
  Zap,
  ExternalLink,
} from "lucide-react";

export const Route = createFileRoute("/history")({
  component: HistoryPage,
});

const ITEMS_PER_PAGE = 10;

// 与后端 /api/agent/history 返回结构对应
interface HistoryRecord {
  id: number;
  task: string;
  result: string;
  llm_calls: number;
  total_tokens: number;
  cache_hit: number;
  duration_ms: number;
  job_url?: string;
  created_at: string;
}

function HistoryPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [records, setRecords] = useState<HistoryRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [clearDialogOpen, setClearDialogOpen] = useState(false);
  const [selectedRecord, setSelectedRecord] = useState<HistoryRecord | null>(null);
  const [detailDialogOpen, setDetailDialogOpen] = useState(false);

  // 从后端加载当前页
  const loadRecords = async (page = currentPage) => {
    setLoading(true);
    try {
      const offset = (page - 1) * ITEMS_PER_PAGE;
      const res = await fetch(
        `${API_BASE}/api/agent/history?limit=${ITEMS_PER_PAGE}&offset=${offset}`
      );
      if (!res.ok) return;
      const data = await res.json();
      setRecords(data.records || []);
      setTotal(data.total || 0);
      setCurrentPage(page);
    } catch {
      /* 静默 */
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadRecords(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 本地搜索过滤（仅当前页内过滤，后端分页为准）
  const filteredRecords = useMemo(() => {
    if (!searchQuery.trim()) return records;
    const q = searchQuery.toLowerCase();
    return records.filter(
      (r) => r.task.toLowerCase().includes(q) || r.result.toLowerCase().includes(q)
    );
  }, [records, searchQuery]);

  const totalPages = Math.max(1, Math.ceil(total / ITEMS_PER_PAGE));

  // 删除单条
  const handleDelete = (record: HistoryRecord) => {
    setSelectedRecord(record);
    setDeleteDialogOpen(true);
  };

  const confirmDelete = async () => {
    if (!selectedRecord) return;
    try {
      const res = await fetch(`${API_BASE}/api/agent/history/${selectedRecord.id}`, {
        method: "DELETE",
      });
      if (res.ok) {
        // 当前页只剩这一条且非第一页 → 前一页
        const willBeEmpty = filteredRecords.length === 1 && currentPage > 1;
        await loadRecords(willBeEmpty ? currentPage - 1 : currentPage);
      }
    } catch {
      /* 静默 */
    }
    setDeleteDialogOpen(false);
    setSelectedRecord(null);
  };

  // 清空全部
  const handleClearAll = () => setClearDialogOpen(true);

  const confirmClearAll = async () => {
    try {
      await fetch(`${API_BASE}/api/agent/history`, { method: "DELETE" });
      setRecords([]);
      setTotal(0);
      setCurrentPage(1);
    } catch {
      /* 静默 */
    }
    setClearDialogOpen(false);
  };

  // 查看详情
  const handleViewDetail = (record: HistoryRecord) => {
    setSelectedRecord(record);
    setDetailDialogOpen(true);
  };

  const formatDate = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  return (
    <div className="min-h-screen bg-background">
      {/* 主内容区 */}
      <main className="container mx-auto px-4 py-8 max-w-5xl">
        {/* 标题区 */}
        <div className="flex items-center gap-4 mb-8 reveal">
          <Link to="/">
            <Button variant="ghost" size="icon" className="rounded-full">
              <ArrowLeft className="w-5 h-5" />
            </Button>
          </Link>
          <div className="flex-1">
            <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
              <History className="w-6 h-6 text-primary" />
              历史记录
            </h1>
            <p className="text-sm text-muted-foreground">共 {total} 条匹配记录</p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => loadRecords(1)}
            title="刷新"
          >
            <RefreshCw className="w-4 h-4" />
          </Button>
        </div>

        {/* 搜索栏 */}
        <div className="flex items-center gap-3 mb-6 reveal" data-reveal-delay="100">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setCurrentPage(1);
              }}
              placeholder="搜索 JD 摘要或结果内容..."
              className="pl-10"
            />
          </div>
          {total > 0 && (
            <Button
              variant="outline"
              onClick={handleClearAll}
              className="text-destructive hover:text-destructive"
            >
              <Trash2 className="w-4 h-4 mr-2" />
              清空全部
            </Button>
          )}
        </div>

        {/* 记录列表 */}
        {loading ? (
          <div className="flex justify-center py-16">
            <div className="animate-spin w-8 h-8 border-2 border-primary border-t-transparent rounded-full" />
          </div>
        ) : filteredRecords.length > 0 ? (
          <div className="space-y-4 reveal" data-reveal-delay="200">
            {filteredRecords.map((record) => (
              <Card
                key={record.id}
                className="overflow-hidden hover:shadow-md transition-shadow cursor-pointer"
                onClick={() => handleViewDetail(record)}
              >
                <CardContent className="p-5">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-2 flex-wrap">
                        {record.cache_hit === 1 && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full bg-green-100 text-green-700">
                            <Zap className="w-3 h-3" />
                            缓存命中
                          </span>
                        )}
                        {record.llm_calls > 0 && (
                          <span className="px-2 py-0.5 text-xs rounded-full bg-violet-100 text-violet-700">
                            LLM×{record.llm_calls}
                          </span>
                        )}
                        {record.total_tokens > 0 && (
                          <span className="px-2 py-0.5 text-xs rounded-full bg-amber-100 text-amber-700">
                            {record.total_tokens} tokens
                          </span>
                        )}
                        <span className="flex items-center gap-1 text-xs text-muted-foreground">
                          <Calendar className="w-3 h-3" />
                          {formatDate(record.created_at)}
                        </span>
                      </div>
                      <p className="text-sm text-foreground line-clamp-2">
                        <span className="font-medium">任务：</span>
                        {record.task.length > 120 ? record.task.slice(0, 120) + "…" : record.task}
                      </p>
                      <p className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
                        <FileText className="w-3 h-3" />
                        耗时 {record.duration_ms}ms · 点击查看完整结果
                      </p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="text-destructive hover:text-destructive"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(record);
                        }}
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}

            {/* 分页（后端分页） */}
            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-2 pt-4">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => loadRecords(Math.max(1, currentPage - 1))}
                  disabled={currentPage === 1}
                >
                  <ChevronLeft className="w-4 h-4" />
                </Button>
                <span className="text-sm text-muted-foreground px-4">
                  {currentPage} / {totalPages}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => loadRecords(Math.min(totalPages, currentPage + 1))}
                  disabled={currentPage === totalPages}
                >
                  <ChevronRight className="w-4 h-4" />
                </Button>
              </div>
            )}
          </div>
        ) : (
          /* 空状态 */
          <div className="text-center py-20 reveal" data-reveal-delay="200">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-muted mb-4">
              <History className="w-8 h-8 text-muted-foreground" />
            </div>
            <h3 className="text-lg font-medium text-foreground mb-2">
              {searchQuery ? "未找到匹配记录" : "暂无历史记录"}
            </h3>
            <p className="text-sm text-muted-foreground mb-6">
              {searchQuery
                ? "请尝试更换搜索关键词"
                : "开始匹配简历后，记录将自动保存到这里"}
            </p>
            <Link to="/">
              <Button className="bg-gradient-to-r from-[var(--tech-blue)] to-[var(--tech-indigo)] text-white">
                <Target className="w-4 h-4 mr-2" />
                开始匹配
              </Button>
            </Link>
          </div>
        )}
      </main>

      {/* 删除确认对话框 */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
            <DialogDescription>
              确定要删除这条匹配记录吗？此操作无法撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              取消
            </Button>
            <Button variant="destructive" onClick={confirmDelete}>
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 清空确认对话框 */}
      <Dialog open={clearDialogOpen} onOpenChange={setClearDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认清空</DialogTitle>
            <DialogDescription>
              确定要清空所有历史记录吗？此操作无法撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setClearDialogOpen(false)}>
              取消
            </Button>
            <Button variant="destructive" onClick={confirmClearAll}>
              清空全部
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 详情对话框 */}
      <Dialog open={detailDialogOpen} onOpenChange={setDetailDialogOpen}>
        <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
          {selectedRecord && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <FileText className="w-5 h-5 text-primary" />
                  历史详情 #{selectedRecord.id}
                </DialogTitle>
                <DialogDescription>
                  {formatDate(selectedRecord.created_at)} · 耗时 {selectedRecord.duration_ms}ms
                  {selectedRecord.cache_hit === 1 ? " · 缓存命中" : ""}
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-6 py-4">
                {/* 任务摘要 */}
                <div>
                  <h4 className="text-sm font-medium text-foreground mb-2 flex items-center gap-2">
                    <Target className="w-4 h-4 text-primary" />
                    任务摘要
                  </h4>
                  <div className="p-4 rounded-xl bg-muted/30 text-sm text-foreground max-h-40 overflow-y-auto whitespace-pre-wrap">
                    {selectedRecord.task}
                  </div>
                </div>

                {/* 完整结果 */}
                <div>
                  <h4 className="text-sm font-medium text-foreground mb-2 flex items-center gap-2">
                    <FileText className="w-4 h-4 text-primary" />
                    完整结果
                  </h4>
                  <div className="p-4 rounded-xl bg-muted/30 text-sm text-muted-foreground max-h-80 overflow-y-auto whitespace-pre-wrap">
                    {selectedRecord.result}
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  <span className="px-2.5 py-1 text-xs rounded-full bg-violet-100 text-violet-700">
                    LLM 调用 {selectedRecord.llm_calls} 次
                  </span>
                  {selectedRecord.total_tokens > 0 && (
                    <span className="px-2.5 py-1 text-xs rounded-full bg-amber-100 text-amber-700">
                      消耗 {selectedRecord.total_tokens} tokens
                    </span>
                  )}
                  {selectedRecord.job_url && (
                    <a
                      href={selectedRecord.job_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-full bg-[var(--tech-blue)]/10 text-[var(--tech-blue)] hover:bg-[var(--tech-blue)]/20 transition-colors"
                    >
                      <ExternalLink className="w-3 h-3" />
                      查看岗位链接
                    </a>
                  )}
                </div>
              </div>

              <DialogFooter>
                <Button variant="outline" onClick={() => setDetailDialogOpen(false)}>
                  关闭
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
