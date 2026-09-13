import * as React from "react";
import { CornerDownLeft, Loader2, Play, Terminal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ResultView } from "@/components/forensics/result-view";
import { useCommandReference } from "@/lib/command-reference";
import { sendCommand } from "@/services/api";
import { useJockyStore } from "@/lib/store";
import type { Report } from "@/lib/types";
import { cn } from "@/lib/utils";

type ExecState = "idle" | "loading" | "success" | "error";

export function CommandConsole({
  variant = "full",
  className,
  initialCommand,
}: {
  variant?: "full" | "compact";
  className?: string;
  initialCommand?: string | undefined;
}) {
  const [command, setCommand] = React.useState(initialCommand ?? "");
  const [state, setState] = React.useState<ExecState>("idle");
  const [report, setReport] = React.useState<Report | null>(null);
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);
  const reference = useCommandReference();
  const { recordExecution, recordFailure, activeInvestigationId, apiConnected } = useJockyStore();
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  React.useEffect(() => {
    if (initialCommand) {
      setCommand(initialCommand);
      textareaRef.current?.focus();
    }
  }, [initialCommand]);

  const execute = React.useCallback(async () => {
    const trimmed = command.trim();
    if (!trimmed || state === "loading") return;

    setState("loading");
    setErrorMessage(null);

    try {
      const response = await sendCommand(trimmed);
      recordExecution(trimmed, response, activeInvestigationId);
      if (response.report) setReport(response.report);
      setState("success");
    } catch (err) {
      const error = err as Error & { report?: Report };
      recordFailure(trimmed, error, activeInvestigationId);
      if (error.report) setReport(error.report);
      setErrorMessage(error.message);
      setState("error");
    }
  }, [command, state, recordExecution, recordFailure, activeInvestigationId]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      void execute();
    }
  };

  const applyExample = (example: string) => {
    setCommand(example);
    textareaRef.current?.focus();
  };

  return (
    <div className={cn("space-y-4", className)}>
      <div className="overflow-hidden rounded-xl border border-border-strong bg-card shadow-[0_0_0_1px_rgba(0,0,0,0.2)]">
        <div className="flex items-center justify-between border-b border-border bg-surface/60 px-4 py-2.5">
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
            <Terminal className="h-3.5 w-3.5 text-primary" />
            JOCKY COMMAND EDITOR
          </div>
          <div className="hidden items-center gap-1.5 text-[10.5px] text-muted-foreground sm:flex">
            <kbd className="rounded border border-border-strong bg-secondary px-1.5 py-0.5 font-mono">
              Ctrl
            </kbd>
            <span>+</span>
            <kbd className="rounded border border-border-strong bg-secondary px-1.5 py-0.5 font-mono">
              Enter
            </kbd>
            <span>to execute</span>
          </div>
        </div>

        <Textarea
          ref={textareaRef}
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="HASH FILE evidence.bin"
          rows={variant === "full" ? 3 : 2}
          className="scrollbar-thin resize-none rounded-none border-0 bg-transparent px-4 py-3.5 font-mono text-[13.5px] leading-relaxed shadow-none focus-visible:ring-0"
        />

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border bg-surface/40 px-4 py-3">
          <div className="flex flex-wrap gap-1.5">
            {reference.slice(0, variant === "full" ? 6 : 3).map((entry) => (
              <button
                key={entry.name}
                type="button"
                onClick={() => applyExample(entry.example)}
                className="rounded border border-border bg-secondary/50 px-2 py-1 font-mono text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
              >
                {entry.example}
              </button>
            ))}
          </div>

          <Button
            onClick={() => void execute()}
            disabled={state === "loading" || !command.trim() || apiConnected === false}
            className="gap-1.5"
          >
            {state === "loading" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
            {state === "loading" ? "Executing" : "Execute"}
            <CornerDownLeft className="h-3.5 w-3.5 opacity-60" />
          </Button>
        </div>
      </div>

      {apiConnected === false && (
        <p className="text-xs text-critical">
          The JOCKY API is unreachable. Start the Flask server, then commands will execute for real.
        </p>
      )}

      {state === "loading" && (
        <div className="flex items-center gap-2 rounded-lg border border-border bg-card px-4 py-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
          Running analysis engine...
        </div>
      )}

      {state !== "loading" && report && (
        <div className="rounded-xl border border-border bg-card p-5">
          <ResultView report={report} />
        </div>
      )}

      {state === "error" && !report && errorMessage && (
        <p className="rounded-lg border border-critical/30 bg-critical/10 px-4 py-3 text-sm text-critical">
          {errorMessage}
        </p>
      )}
    </div>
  );
}
