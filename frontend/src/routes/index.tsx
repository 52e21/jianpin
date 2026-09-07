import { createFileRoute, Link } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import {
  Sparkles,
  ArrowRight,
  Zap,
  Brain,
  Target,
  HelpCircle,
  BarChart3,
  ChevronRight
} from "lucide-react";

export const Route = createFileRoute("/")({
  component: LandingPage,
});

function LandingPage() {
  const features = [
    {
      icon: Brain,
      title: "智能 JD 解析",
      description: "自动提取职位要求、技能标签、经验要求等关键信息"
    },
    {
      icon: Target,
      title: "精准简历匹配",
      description: "多维度计算匹配度，识别命中与缺失技能"
    },
    {
      icon: HelpCircle,
      title: "面试题生成",
      description: "针对候选人背景智能生成针对性面试问题"
    },
    {
      icon: BarChart3,
      title: "推荐结论",
      description: "基于匹配结果给出推荐/待定/不推荐的决策建议"
    }
  ];

  return (
    <div className="min-h-screen bg-background">
      {/* Hero Section */}
      <section className="relative pt-20 pb-32 overflow-hidden">
        {/* Background decoration */}
        <div className="absolute inset-0 overflow-hidden">
          <div className="absolute -top-1/2 -right-1/4 w-[800px] h-[800px] rounded-full bg-gradient-to-br from-[var(--tech-blue)]/10 to-[var(--tech-indigo)]/5 blur-3xl" />
          <div className="absolute -bottom-1/4 -left-1/4 w-[600px] h-[600px] rounded-full bg-gradient-to-tr from-[var(--tech-cyan)]/10 to-transparent blur-3xl" />
        </div>

        <div className="container mx-auto px-4 relative z-10">
          <div className="text-center max-w-4xl mx-auto reveal">
            {/* Badge */}
            <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-primary/10 text-primary text-sm font-medium mb-6 border border-primary/20">
              <Zap className="w-4 h-4" />
              AI 驱动的简聘
            </div>

            {/* Main Title */}
            <h1 className="text-5xl md:text-6xl lg:text-7xl font-bold text-foreground mb-6 leading-tight">
              <span className="bg-gradient-to-r from-[var(--tech-blue)] to-[var(--tech-indigo)] bg-clip-text text-transparent">
                简聘
              </span>
            </h1>

            {/* Subtitle */}
            <h2 className="text-2xl md:text-3xl font-semibold text-foreground/80 mb-4">
              智能简历匹配系统
            </h2>

            {/* Description */}
            <p className="text-lg md:text-xl text-muted-foreground mb-10 max-w-2xl mx-auto leading-relaxed">
              输入岗位 JD 和候选人简历，AI 自动完成解析、匹配、生成面试题与推荐结论
            </p>

            {/* CTA Button */}
            <Link to="/match">
              <Button
                size="lg"
                className="bg-gradient-to-r from-[var(--tech-blue)] to-[var(--tech-indigo)] text-white px-10 py-6 text-lg font-medium hover:opacity-90 transition-all hover:scale-105 hover:shadow-xl hover:shadow-primary/25"
              >
                <Sparkles className="w-5 h-5 mr-2" />
                开始匹配
                <ArrowRight className="w-5 h-5 ml-2" />
              </Button>
            </Link>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="py-20 bg-muted/30">
        <div className="container mx-auto px-4">
          <div className="text-center mb-16 reveal">
            <h3 className="text-2xl md:text-3xl font-bold text-foreground mb-4">
              核心功能
            </h3>
            <p className="text-muted-foreground max-w-xl mx-auto">
              全流程智能化处理，让招聘更高效
            </p>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6 max-w-6xl mx-auto">
            {features.map((feature, index) => (
              <div
                key={feature.title}
                className="group p-6 rounded-2xl bg-card border border-border/50 hover:border-primary/30 hover:shadow-lg hover:shadow-primary/5 transition-all duration-300 reveal"
                data-reveal-delay={index * 100}
              >
                <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-[var(--tech-blue)] to-[var(--tech-indigo)] text-white mb-4 group-hover:scale-110 transition-transform">
                  <feature.icon className="w-6 h-6" />
                </div>
                <h4 className="text-lg font-semibold text-foreground mb-2">
                  {feature.title}
                </h4>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {feature.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="py-20">
        <div className="container mx-auto px-4">
          <div className="text-center mb-16 reveal">
            <h3 className="text-2xl md:text-3xl font-bold text-foreground mb-4">
              使用流程
            </h3>
            <p className="text-muted-foreground max-w-xl mx-auto">
              简单三步，快速完成简历匹配
            </p>
          </div>

          <div className="flex flex-col md:flex-row items-center justify-center gap-8 max-w-4xl mx-auto">
            {[
              { step: "1", title: "输入 JD", desc: "粘贴岗位描述" },
              { step: "2", title: "上传简历", desc: "粘贴简历内容" },
              { step: "3", title: "获取结果", desc: "查看匹配分析" }
            ].map((item, index) => (
              <div key={item.step} className="flex items-center gap-8">
                <div className="text-center reveal" data-reveal-delay={index * 150}>
                  <div className="flex items-center justify-center w-16 h-16 rounded-full bg-gradient-to-br from-[var(--tech-blue)] to-[var(--tech-indigo)] text-white text-2xl font-bold mb-3 mx-auto">
                    {item.step}
                  </div>
                  <h4 className="text-lg font-semibold text-foreground mb-1">
                    {item.title}
                  </h4>
                  <p className="text-sm text-muted-foreground">{item.desc}</p>
                </div>
                {index < 2 && (
                  <ChevronRight className="hidden md:block w-8 h-8 text-muted-foreground/50" />
                )}
              </div>
            ))}
          </div>

          {/* CTA */}
          <div className="text-center mt-16 reveal">
            <Link to="/match">
              <Button
                size="lg"
                className="bg-gradient-to-r from-[var(--tech-blue)] to-[var(--tech-indigo)] text-white px-10 py-6 text-lg font-medium hover:opacity-90 transition-all hover:scale-105"
              >
                <Sparkles className="w-5 h-5 mr-2" />
                立即开始
                <ArrowRight className="w-5 h-5 ml-2" />
              </Button>
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
