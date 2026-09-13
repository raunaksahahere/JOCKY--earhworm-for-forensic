import { AlertTriangle, Info, ShieldAlert } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { Indicator } from "@/lib/types";

const LEVEL_STYLE: Record<Indicator["level"], string> = {
  info: "border-info/30 bg-info/10 text-info",
  warning: "border-warning/30 bg-warning/10 text-warning",
  critical: "border-critical/30 bg-critical/10 text-critical",
};

const LEVEL_ICON: Record<Indicator["level"], typeof Info> = {
  info: Info,
  warning: AlertTriangle,
  critical: ShieldAlert,
};

export function IndicatorBadges({ indicators }: { indicators: Indicator[] | undefined }) {
  if (!indicators || indicators.length === 0) return null;

  return (
    <TooltipProvider delayDuration={150}>
      <div className="flex flex-wrap gap-1.5">
        {indicators.map((indicator, i) => {
          const Icon = LEVEL_ICON[indicator.level];
          return (
            <Tooltip key={`${indicator.label}-${i}`}>
              <TooltipTrigger asChild>
                <span
                  className={cn(
                    "inline-flex cursor-default items-center gap-1 rounded border px-1.5 py-0.5 text-[10.5px] font-medium",
                    LEVEL_STYLE[indicator.level],
                  )}
                >
                  <Icon className="h-3 w-3" strokeWidth={2} />
                  {indicator.label}
                </span>
              </TooltipTrigger>
              <TooltipContent className="max-w-64 bg-popover text-popover-foreground">
                {indicator.detail}
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </TooltipProvider>
  );
}
