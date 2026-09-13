import { CheckCircle2, Clock, Terminal, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { formatDuration } from "@/lib/format";

export function ResultHeader({
  command,
  action,
  status,
  executionTimeMs,
}: {
  command: string;
  action: string | null;
  status: "completed" | "failed" | string;
  executionTimeMs: number | null | undefined;
}) {
  const succeeded = status === "completed";
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-4">
      <div className="flex min-w-0 items-center gap-2.5">
        <Terminal className="h-4 w-4 shrink-0 text-muted-foreground" />
        <code className="truncate font-mono text-[13px] text-foreground">{command}</code>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {action && (
          <Badge
            variant="outline"
            className="border-border-strong font-mono text-[10.5px] uppercase text-muted-foreground"
          >
            {action}
          </Badge>
        )}
        <Badge
          className={
            succeeded
              ? "gap-1 border-success/30 bg-success/10 text-success hover:bg-success/10"
              : "gap-1 border-critical/30 bg-critical/10 text-critical hover:bg-critical/10"
          }
          variant="outline"
        >
          {succeeded ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
          {succeeded ? "Completed" : "Failed"}
        </Badge>
        <Badge
          variant="outline"
          className="gap-1 border-border-strong font-mono text-[10.5px] text-muted-foreground"
        >
          <Clock className="h-3 w-3" />
          {formatDuration(executionTimeMs)}
        </Badge>
      </div>
    </div>
  );
}
