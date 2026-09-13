import { cn } from "@/lib/utils";

type Tone = "success" | "warning" | "critical" | "info" | "muted";

const DOT_TONE: Record<Tone, string> = {
  success: "bg-success shadow-[0_0_10px_var(--color-success)]",
  warning: "bg-warning shadow-[0_0_10px_var(--color-warning)]",
  critical: "bg-critical shadow-[0_0_10px_var(--color-critical)]",
  info: "bg-info shadow-[0_0_10px_var(--color-info)]",
  muted: "bg-muted-foreground/50",
};

const TEXT_TONE: Record<Tone, string> = {
  success: "text-success",
  warning: "text-warning",
  critical: "text-critical",
  info: "text-info",
  muted: "text-muted-foreground",
};

export function StatusPill({
  tone,
  label,
  pulse = false,
  className,
}: {
  tone: Tone;
  label: string;
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full border border-border bg-surface/60 px-2.5 py-1 text-xs font-medium",
        className,
      )}
    >
      <span className="relative flex h-1.5 w-1.5">
        {pulse && (
          <span
            className={cn(
              "absolute inline-flex h-full w-full animate-ping rounded-full opacity-60",
              DOT_TONE[tone],
            )}
          />
        )}
        <span className={cn("relative inline-flex h-1.5 w-1.5 rounded-full", DOT_TONE[tone])} />
      </span>
      <span className={cn("font-mono tracking-tight", TEXT_TONE[tone])}>{label}</span>
    </span>
  );
}
