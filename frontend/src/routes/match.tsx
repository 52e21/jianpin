import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { FileUpload } from "@/components/file-upload";
import {
  Briefcase,
  FileText,
  Sparkles,
  AlertCircle,
  ChevronLeft,
  Loader2,
  Link2,
} from "lucide-react";
import { Link } from "@tanstack/react-router";
import { API_BASE, getSessionId } from "@/lib/api";

export const Route = createFileRoute("/match")({
  component: MatchPage,
});

// 示例数据（演示用）
export const SAMPLE_JD = `高级 Java 开发工程师

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
3. 有大厂背景优先`;

export const SAMPLE_RESUME = `张三
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
具备良好的团队协作能力和沟通能力，有开源项目贡献经验`;

function MatchPage() {
  const navigate = useNavigate();
  const [jdText, setJdText] = useState("");
  const [resumeText, setResumeText] = useState("");
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [jobUrl, setJobUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // 第 10 步：查看身份。hr → 推荐/待定/不推荐；candidate → 高/中/低匹配 + 建议
  const [role, setRole] = useState<"hr" | "candidate">("hr");

  // 填入示例数据
  const fillSampleData = () => {
    setJdText(SAMPLE_JD);
    setResumeText(SAMPLE_RESUME);
  };

  // 处理文件上传（调后端提取，零 LLM）
  const handleFileSelect = async (file: File) => {
    setUploadedFile(file);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`${API_BASE}/api/upload/resume`, {
        method: "POST",
        body: formData,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || "上传失败");
      }
      if (data.text) {
        setResumeText(data.text);
      } else {
        setError("未能从文件中提取到文字，请手动粘贴简历内容");
      }
    } catch (err: any) {
      setError(err.message || "文件解析失败，请手动粘贴简历内容");
    }
  };

  const handleFileRemove = () => {
    setUploadedFile(null);
    setError(null);
  };

  // 开始匹配：调后端结构化分析接口，成功后跳结果页
  const startMatching = async () => {
    if (!jdText.trim() || !resumeText.trim()) {
      setError("请输入 JD 和简历内容");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/agent/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jd: jdText,
          resume: resumeText,
          job_url: jobUrl.trim() || null,
          // 第 9 步：缓存按租户/会话隔离。当前无登录体系，
          // tenant_id 固定 default（等接入账号后替换为真实租户）；
          // session_id 每个浏览器会话生成一次并复用。
          tenant_id: "default",
          session_id: getSessionId(),
          // 第 10 步：角色（影响后端返回的结论文案，也参与缓存 key）
          role,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || "分析失败，请稍后重试");
      }
      navigate({
        to: "/result",
        state: { result: data, jd: jdText, resume: resumeText, role },
      });
    } catch (err: any) {
      setError(err.message || "网络错误，请稍后重试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="sticky top-16 z-40 bg-background/80 backdrop-blur-md border-b border-border/50">
        <div className="container mx-auto px-4 py-4 max-w-5xl">
          <div className="flex items-center gap-4">
            <Link to="/">
              <Button variant="ghost" size="sm" className="gap-2">
                <ChevronLeft className="w-4 h-4" />
                返回首页
              </Button>
            </Link>
            <div className="h-6 w-px bg-border" />
            <h1 className="text-lg font-semibold text-foreground">输入信息</h1>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <main className="container mx-auto px-4 py-4 max-w-5xl">
        {/* 输入区 - 紧凑布局 */}
        <div className="grid md:grid-cols-2 gap-4 mb-4">
          {/* JD 输入 */}
          <div className="space-y-2 reveal">
            <div className="flex items-center justify-between">
              <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                <Briefcase className="w-4 h-4 text-primary" />
                岗位 JD
              </label>
              <button
                onClick={fillSampleData}
                className="text-xs text-primary hover:text-primary/80 transition-colors"
              >
                填入示例
              </button>
            </div>
            <Textarea
              value={jdText}
              onChange={(e) => setJdText(e.target.value)}
              placeholder="请粘贴完整的岗位描述（JD）..."
              className="min-h-[180px] resize-none text-base"
              disabled={loading}
            />
            <p className="text-sm text-muted-foreground">
              支持粘贴文本，系统将自动解析职位要求
            </p>

            {/* 岗位链接（可选） */}
            <div className="pt-1">
              <label className="flex items-center gap-2 text-sm font-medium text-foreground mb-1.5">
                <Link2 className="w-4 h-4 text-muted-foreground" />
                岗位链接（可选）
              </label>
              <Input
                value={jobUrl}
                onChange={(e) => setJobUrl(e.target.value)}
                placeholder="粘贴该岗位的招聘网站链接"
                disabled={loading}
              />
              <p className="text-xs text-muted-foreground mt-1">
                填写后可一键投递到原岗位
              </p>
            </div>
          </div>

          {/* 简历输入 */}
          <div className="space-y-2 reveal" data-reveal-delay="100">
            <div className="flex items-center justify-between">
              <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                <FileText className="w-4 h-4 text-primary" />
                候选人简历
              </label>
              {uploadedFile && (
                <span className="text-xs text-muted-foreground">
                  {uploadedFile.name}
                </span>
              )}
            </div>
            <Textarea
              value={resumeText}
              onChange={(e) => setResumeText(e.target.value)}
              placeholder="请粘贴候选人简历内容，或上传 PDF/DOCX 文件..."
              className="min-h-[180px] resize-none text-base"
              disabled={loading}
            />
            <FileUpload
              onFileSelect={handleFileSelect}
              onFileRemove={handleFileRemove}
              disabled={loading}
            />
          </div>
        </div>

        {/* 错误提示 */}
        {error && (
          <div className="mb-4 p-3 rounded-xl bg-destructive/10 border border-destructive/20 text-destructive text-sm reveal">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4" />
              {error}
            </div>
          </div>
        )}

        {/* 第 10 步：身份切换 —— 决定结论文案（HR：推荐/待定/不推荐；求职者：高/中/低匹配） */}
        <div className="mb-4 flex flex-col items-center gap-2 reveal">
          <span className="text-xs text-muted-foreground">以什么身份查看结论？</span>
          <div className="inline-flex rounded-lg border border-border bg-card p-1">
            {([
              { key: "hr", text: "招聘方（HR）" },
              { key: "candidate", text: "求职者" },
            ] as const).map((r) => (
              <button
                key={r.key}
                type="button"
                onClick={() => setRole(r.key)}
                className={
                  "rounded-md px-4 py-1.5 text-sm transition-colors " +
                  (role === r.key
                    ? "bg-[var(--tech-blue)] text-white"
                    : "text-muted-foreground hover:text-foreground")
                }
              >
                {r.text}
              </button>
            ))}
          </div>
        </div>

        {/* 操作按钮 */}
        <div className="flex items-center justify-center reveal" data-reveal-delay="200">
          <Button
            onClick={startMatching}
            disabled={!jdText.trim() || !resumeText.trim() || loading}
            className="bg-gradient-to-r from-[var(--tech-blue)] to-[var(--tech-indigo)] text-white px-10 py-5 text-lg font-medium hover:opacity-90 transition-all hover:scale-105"
          >
            {loading ? (
              <>
                <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                分析中...
              </>
            ) : (
              <>
                <Sparkles className="w-5 h-5 mr-2" />
                开始匹配
              </>
            )}
          </Button>
        </div>
      </main>
    </div>
  );
}
