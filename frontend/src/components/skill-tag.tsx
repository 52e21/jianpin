import { cn } from "@/lib/utils";
import { Check, Minus } from "lucide-react";

interface SkillTagProps {
  name: string;
  type?: "required" | "preferred" | "matched" | "missing";
  showIcon?: boolean;
  className?: string;
}

export function SkillTag({
  name,
  type = "required",
  showIcon = false,
  className,
}: SkillTagProps) {
  const variants = {
    required: "bg-gradient-to-br from-[var(--tech-blue)] to-[var(--tech-indigo)] text-white border-transparent",
    preferred: "bg-muted text-muted-foreground border-border",
    matched: "bg-[var(--success)]/10 text-[var(--success)] border-[var(--success)]/30",
    missing: "bg-[var(--danger)]/10 text-[var(--danger)] border-[var(--danger)]/30",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-full border transition-all duration-200 hover:scale-105",
        variants[type],
        className
      )}
    >
      {showIcon && (
        type === "matched" ? (
          <Check className="w-3 h-3" />
        ) : type === "missing" ? (
          <Minus className="w-3 h-3" />
        ) : null
      )}
      {name}
    </span>
  );
}

interface SkillTagGroupProps {
  skills: string[];
  type?: "required" | "preferred" | "matched" | "missing";
  showIcons?: boolean;
  className?: string;
}

export function SkillTagGroup({
  skills,
  type = "required",
  showIcons = false,
  className,
}: SkillTagGroupProps) {
  if (skills.length === 0) return null;

  return (
    <div className={cn("flex flex-wrap gap-2", className)}>
      {skills.map((skill) => (
        <SkillTag key={skill} name={skill} type={type} showIcon={showIcons} />
      ))}
    </div>
  );
}
