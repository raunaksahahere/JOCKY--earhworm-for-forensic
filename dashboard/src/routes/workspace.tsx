import * as React from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { Clock3, FolderPlus, Terminal } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { formatTimestamp } from "@/lib/format";
import { useJockyStore } from "@/lib/store";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/workspace")({
  component: Workspace,
  head: () => ({
    meta: [
      { title: "Investigation Workspace — JOCKY" },
      {
        name: "description",
        content: "Case-oriented workspace: evidence, findings, and activity timeline.",
      },
    ],
  }),
});

function Workspace() {
  const {
    investigations,
    history,
    reports,
    addInvestigation,
    updateInvestigationNotes,
    activeInvestigationId,
    setActiveInvestigationId,
  } = useJockyStore();

  const active =
    investigations.find((inv) => inv.id === activeInvestigationId) ?? investigations[0];
  const [notesDraft, setNotesDraft] = React.useState(active?.analystNotes ?? "");

  React.useEffect(() => {
    setNotesDraft(active?.analystNotes ?? "");
  }, [active?.id, active?.analystNotes]);

  const timeline = React.useMemo(() => {
    if (!active) return [];
    return history.filter((h) => active.commandIds.includes(h.id)).slice(0, 50);
  }, [active, history]);

  const investigationReports = React.useMemo(() => {
    if (!active) return [];
    return reports.filter((r) => active.reportIds.includes(r.report_id));
  }, [active, reports]);

  const allIndicators = investigationReports.flatMap((r) => {
    const result = r.result as {
      indicators?: unknown[];
      entries?: { indicators: unknown[] }[];
      results?: { indicators: unknown[] }[];
    };
    if (Array.isArray(result?.indicators)) return result.indicators;
    if (Array.isArray(result?.entries)) return result.entries.flatMap((e) => e.indicators ?? []);
    if (Array.isArray(result?.results)) return result.results.flatMap((e) => e.indicators ?? []);
    return [];
  }) as { label: string; level: string }[];

  return (
    <AppShell title="Investigation Workspace" description="Cases, evidence, and findings">
      <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
        <div className="space-y-3">
          <Button
            variant="outline"
            size="sm"
            className="w-full justify-start gap-2"
            onClick={() => {
              const inv = addInvestigation(`Investigation ${investigations.length + 1}`);
              setActiveInvestigationId(inv.id);
            }}
          >
            <FolderPlus className="h-3.5 w-3.5" />
            New Investigation
          </Button>
          <div className="space-y-1.5">
            {investigations.map((inv) => (
              <button
                key={inv.id}
                onClick={() => setActiveInvestigationId(inv.id)}
                className={cn(
                  "w-full rounded-lg border px-3 py-2.5 text-left transition-colors",
                  inv.id === active?.id
                    ? "border-primary/40 bg-primary/10"
                    : "border-border bg-card hover:border-border-strong",
                )}
              >
                <p className="truncate text-[12.5px] font-medium text-foreground">{inv.title}</p>
                <p className="mt-0.5 font-mono text-[10.5px] text-muted-foreground">
                  {inv.id} · {inv.commandIds.length} commands
                </p>
              </button>
            ))}
          </div>
        </div>

        {active && (
          <div className="space-y-6">
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h2 className="text-sm font-semibold text-foreground">{active.title}</h2>
                  <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                    {active.id} · Created {formatTimestamp(active.createdAt)}
                  </p>
                </div>
                <div className="flex gap-4 text-center">
                  <div>
                    <p className="font-mono text-lg font-semibold text-foreground">
                      {active.commandIds.length}
                    </p>
                    <p className="text-[10px] uppercase text-muted-foreground">Commands</p>
                  </div>
                  <div>
                    <p className="font-mono text-lg font-semibold text-foreground">
                      {active.reportIds.length}
                    </p>
                    <p className="text-[10px] uppercase text-muted-foreground">Reports</p>
                  </div>
                  <div>
                    <p className="font-mono text-lg font-semibold text-foreground">
                      {allIndicators.length}
                    </p>
                    <p className="text-[10px] uppercase text-muted-foreground">Indicators</p>
                  </div>
                </div>
              </div>

              <div className="mt-4">
                <p className="mb-1.5 text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">
                  Analyst Notes
                </p>
                <Textarea
                  value={notesDraft}
                  onChange={(e) => setNotesDraft(e.target.value)}
                  onBlur={() => updateInvestigationNotes(active.id, notesDraft)}
                  placeholder="Record observations, working theories, and next steps for this investigation..."
                  rows={3}
                  className="text-sm"
                />
              </div>
            </div>

            {allIndicators.length > 0 && (
              <div className="rounded-xl border border-border bg-card p-5">
                <p className="mb-3 text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">
                  Indicators Collected
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {allIndicators.map((ind, i) => (
                    <Badge key={i} variant="outline" className="border-warning/30 text-warning">
                      {ind.label}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            <div className="rounded-xl border border-border bg-card p-5">
              <p className="mb-4 flex items-center gap-2 text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">
                <Clock3 className="h-3.5 w-3.5" />
                Activity Timeline
              </p>
              {timeline.length === 0 ? (
                <p className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-xs text-muted-foreground">
                  No commands attributed to this investigation yet. Commands run from the Command
                  Center are attached to the active investigation automatically.
                </p>
              ) : (
                <ol className="relative space-y-5 border-l border-border pl-5">
                  {timeline.map((entry) => (
                    <li key={entry.id} className="relative">
                      <span
                        className={cn(
                          "absolute -left-[25px] top-1 h-2.5 w-2.5 rounded-full border-2 border-card",
                          entry.status === "success" ? "bg-success" : "bg-critical",
                        )}
                      />
                      <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                        <Terminal className="h-3 w-3" />
                        {formatTimestamp(entry.timestamp)}
                      </div>
                      <code className="mt-0.5 block font-mono text-[12.5px] text-foreground">
                        {entry.command}
                      </code>
                      {entry.reportId && (
                        <Link
                          to="/reports/$reportId"
                          params={{ reportId: entry.reportId }}
                          className="mt-0.5 inline-block font-mono text-[11px] text-primary hover:underline"
                        >
                          View {entry.reportId}
                        </Link>
                      )}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
