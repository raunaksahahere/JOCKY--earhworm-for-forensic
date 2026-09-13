import { createFileRoute } from "@tanstack/react-router";
import { BookOpenText, History as HistoryIcon } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { CommandConsole } from "@/components/forensics/command-console";
import { Badge } from "@/components/ui/badge";
import { useCommandReference } from "@/lib/command-reference";
import { formatRelativeTime } from "@/lib/format";
import { useJockyStore } from "@/lib/store";

interface CommandCenterSearch {
  cmd?: string | undefined;
}

export const Route = createFileRoute("/command-center")({
  component: CommandCenter,
  validateSearch: (search: Record<string, unknown>): CommandCenterSearch => ({
    cmd: typeof search["cmd"] === "string" ? search["cmd"] : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Command Center — JOCKY" },
      {
        name: "description",
        content: "Execute JOCKY forensic commands against the live analysis engine.",
      },
    ],
  }),
});

function CommandCenter() {
  const reference = useCommandReference();
  const { history } = useJockyStore();
  const { cmd } = Route.useSearch();

  return (
    <AppShell title="Command Center" description="The JOCKY forensic command console">
      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div>
          <CommandConsole variant="full" initialCommand={cmd} />
        </div>

        <div className="space-y-6">
          <div className="rounded-xl border border-border bg-card p-4">
            <div className="mb-3 flex items-center gap-2 text-xs font-medium text-muted-foreground">
              <BookOpenText className="h-3.5 w-3.5 text-primary" />
              SUPPORTED COMMANDS
            </div>
            <div className="space-y-3">
              {reference.map((entry) => (
                <div key={entry.name} className="rounded-lg border border-border bg-void/50 p-3">
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="font-mono text-[12.5px] font-medium text-foreground">
                      {entry.name}
                    </span>
                    <Badge
                      variant="outline"
                      className="border-border-strong text-[9.5px] text-muted-foreground"
                    >
                      {entry.category}
                    </Badge>
                  </div>
                  <code className="block truncate text-[11px] text-primary">{entry.syntax}</code>
                  <p className="mt-1.5 text-[11.5px] leading-relaxed text-muted-foreground">
                    {entry.description}
                  </p>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-border bg-card p-4">
            <div className="mb-3 flex items-center gap-2 text-xs font-medium text-muted-foreground">
              <HistoryIcon className="h-3.5 w-3.5 text-primary" />
              SESSION HISTORY
            </div>
            {history.length === 0 ? (
              <p className="py-4 text-center text-[11.5px] text-muted-foreground">
                No commands run yet this session.
              </p>
            ) : (
              <ul className="scrollbar-thin max-h-80 space-y-1.5 overflow-y-auto">
                {history.slice(0, 25).map((entry) => (
                  <li
                    key={entry.id}
                    className="flex items-center justify-between gap-2 text-[11.5px]"
                  >
                    <code className="min-w-0 flex-1 truncate text-foreground">{entry.command}</code>
                    <span
                      className={
                        "shrink-0 font-mono text-[10px] uppercase " +
                        (entry.status === "success" ? "text-success" : "text-critical")
                      }
                    >
                      {formatRelativeTime(entry.timestamp)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
