import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";

interface ResultCardProps {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  collapsible?: boolean;
  defaultExpanded?: boolean;
  badge?: React.ReactNode;
}

export function ResultCard({
  title,
  icon,
  children,
  className,
  collapsible = false,
  defaultExpanded = true,
  badge,
}: ResultCardProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <Card
      className={cn(
        "overflow-hidden border-border/50 bg-card/80 backdrop-blur-sm",
        "transition-all duration-300 hover:shadow-lg hover:shadow-primary/5",
        className
      )}
    >
      <CardHeader
        className={cn(
          "flex flex-row items-center gap-3 pb-3",
          collapsible && "cursor-pointer hover:bg-muted/50 transition-colors"
        )}
        onClick={collapsible ? () => setExpanded(!expanded) : undefined}
      >
        {icon && (
          <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-[var(--tech-blue)] to-[var(--tech-indigo)] text-white">
            {icon}
          </div>
        )}
        <CardTitle className="text-base font-semibold flex-1">{title}</CardTitle>
        {badge}
        {collapsible && (
          <button
            className="p-1 rounded-md hover:bg-muted transition-colors"
            onClick={(e) => {
              e.stopPropagation();
              setExpanded(!expanded);
            }}
          >
            {expanded ? (
              <ChevronUp className="w-4 h-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="w-4 h-4 text-muted-foreground" />
            )}
          </button>
        )}
      </CardHeader>
      <div
        className={cn(
          "overflow-hidden transition-all duration-300",
          expanded ? "max-h-[2000px] opacity-100" : "max-h-0 opacity-0"
        )}
      >
        <CardContent className="pt-0">{children}</CardContent>
      </div>
    </Card>
  );
}

interface StatusCardProps {
  status: "recommended" | "pending" | "rejected";
  title: string;
  description: string;
  reasons: string[];
  className?: string;
}

export function StatusCard({
  status,
  title,
  description,
  reasons,
  className,
}: StatusCardProps) {
  const statusConfig = {
    recommended: {
      gradient: "from-[var(--success)] to-oklch(0.7 0.12 145)",
      bg: "bg-[var(--success)]/10",
      border: "border-[var(--success)]/30",
      text: "text-[var(--success)]",
      icon: "✓",
    },
    pending: {
      gradient: "from-[var(--warning)] to-oklch(0.85 0.1 85)",
      bg: "bg-[var(--warning)]/10",
      border: "border-[var(--warning)]/30",
      text: "text-amber-600",
      icon: "?",
    },
    rejected: {
      gradient: "from-[var(--danger)] to-oklch(0.65 0.15 25)",
      bg: "bg-[var(--danger)]/10",
      border: "border-[var(--danger)]/30",
      text: "text-[var(--danger)]",
      icon: "×",
    },
  };

  const config = statusConfig[status];

  return (
    <Card
      className={cn(
        "overflow-hidden border-2",
        config.border,
        config.bg,
        className
      )}
    >
      <CardContent className="p-6">
        <div className="flex items-start gap-4">
          <div
            className={cn(
              "flex items-center justify-center w-12 h-12 rounded-full text-xl font-bold text-white bg-gradient-to-br",
              config.gradient
            )}
          >
            {config.icon}
          </div>
          <div className="flex-1">
            <h3 className={cn("text-lg font-bold mb-1", config.text)}>
              {title}
            </h3>
            <p className="text-sm text-muted-foreground mb-3">{description}</p>
            <ul className="space-y-1.5">
              {reasons.map((reason, index) => (
                <li
                  key={index}
                  className="flex items-start gap-2 text-sm text-foreground/80"
                >
                  <span className={cn("mt-1 w-1.5 h-1.5 rounded-full", config.text.replace("text-", "bg-"))} />
                  {reason}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
