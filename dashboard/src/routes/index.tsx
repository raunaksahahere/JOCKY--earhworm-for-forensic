import { createFileRoute, Link } from "@tanstack/react-router";
import {
  Activity,
  ArrowRight,
  FileText,
  FolderSearch,
  Gauge,
  ScanSearch,
  ServerCog,
  ShieldCheck,
} from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { MetricCard } from "@/components/layout/metric-card";
import { StatusPill } from "@/components/layout/status-pill";
import { CommandConsole } from "@/components/forensics/command-console";
import { Button } from "@/components/ui/button";
import { formatRelativeTime } from "@/lib/format";
import { useJockyStore } from "@/lib/store";

export const Route = createFileRoute("/")({
  component: Overview,
  head: () => ({
    meta: [
      { title: "Overview — JOCKY" },
      {
        name: "description",
        content:
          "Forensic operations dashboard: engine status, analysis counters, and the command launcher.",
      },
    ],
  }),
});

const FILE_ACTIONS = new Set(["hash", "search", "list"]);

function Overview() {
  const { history, reports, investigations, apiConnected } = useJockyStore();

  const filesAnalyzed = reports.filter((r) => r.action && FILE_ACTIONS.has(r.action)).length;
  const recentHistory = history.slice(0, 6);

  return (
    <AppShell title="Overview" description="Forensic operations dashboard">
      <div className="space-y-8">
        <section>
          <div className="mb-4 flex items-baseline justify-between">
            <h2 className="text-sm font-medium text-muted-foreground">Operations Status</h2>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            <div className="col-span-2 flex items-center justify-between rounded-xl border border-border bg-card p-4 sm:col-span-1">
              <div>
                <p className="text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">
                  System Status
                </p>
                <div className="mt-2.5">
                  <StatusPill
                    tone={apiConnected === null ? "muted" : apiConnected ? "success" : "critical"}
                    label={
                      apiConnected === null ? "CHECKING" : apiConnected ? "OPERATIONAL" : "DEGRADED"
                    }
                    pulse={apiConnected === true}
                  />
                </div>
              </div>
              <ShieldCheck
                className={
                  "h-8 w-8 " + (apiConnected ? "text-success/70" : "text-muted-foreground/40")
                }
                strokeWidth={1.5}
              />
            </div>
            <MetricCard
              label="API Status"
              value={apiConnected === null ? "…" : apiConnected ? "Online" : "Offline"}
              icon={ServerCog}
              tone={apiConnected ? "success" : "critical"}
            />
            <MetricCard
              label="JOCKY Engine"
              value={apiConnected ? "Online" : "Standby"}
              icon={Gauge}
              tone={apiConnected ? "success" : "warning"}
            />
            <MetricCard
              label="Active Investigations"
              value={investigations.length}
              icon={FolderSearch}
            />
            <MetricCard label="Analysis Count" value={history.length} icon={Activity} />
            <MetricCard label="Report Count" value={reports.length} icon={FileText} />
            <MetricCard label="Files Analyzed" value={filesAnalyzed} icon={ScanSearch} />
          </div>
        </section>

        <section>
          <div className="mb-4 flex items-baseline justify-between">
            <h2 className="text-sm font-medium text-muted-foreground">Command Launcher</h2>
            <Link
              to="/command-center"
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              Open Command Center
              <ArrowRight className="h-3 w-3" />
            </Link>
          </div>
          <CommandConsole variant="compact" />
        </section>

        <section>
          <div className="mb-4 flex items-baseline justify-between">
            <h2 className="text-sm font-medium text-muted-foreground">Recent Activity</h2>
            <Link to="/history">
              <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs text-muted-foreground">
                View all
                <ArrowRight className="h-3 w-3" />
              </Button>
            </Link>
          </div>
          {recentHistory.length === 0 ? (
            <p className="rounded-xl border border-dashed border-border px-4 py-8 text-center text-xs text-muted-foreground">
              No commands executed yet. Run one from the launcher above to see activity here.
            </p>
          ) : (
            <div className="divide-y divide-border rounded-xl border border-border bg-card">
              {recentHistory.map((entry) => (
                <div key={entry.id} className="flex items-center justify-between gap-3 px-4 py-3">
                  <code className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-foreground">
                    {entry.command}
                  </code>
                  <div className="flex shrink-0 items-center gap-3">
                    <span
                      className={
                        "font-mono text-[10.5px] uppercase " +
                        (entry.status === "success" ? "text-success" : "text-critical")
                      }
                    >
                      {entry.status}
                    </span>
                    <span className="w-16 text-right font-mono text-[11px] text-muted-foreground">
                      {formatRelativeTime(entry.timestamp)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </AppShell>
  );
}
