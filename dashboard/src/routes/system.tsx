import * as React from "react";
import { createFileRoute } from "@tanstack/react-router";
import { AlertCircle, Cpu, Loader2, RefreshCcw } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { ProcessesTable } from "@/components/forensics/processes-table";
import { DataField, DataGrid } from "@/components/forensics/data-field";
import { sendCommand } from "@/services/api";
import { formatTimestamp, formatUptime } from "@/lib/format";
import { useJockyStore } from "@/lib/store";
import type { ProcessesResult, SystemInfoResult } from "@/lib/types";

export const Route = createFileRoute("/system")({
  component: SystemStatus,
  head: () => ({
    meta: [
      { title: "System Status — JOCKY" },
      {
        name: "description",
        content: "Read-only host and engine monitoring for authorized forensic observation.",
      },
    ],
  }),
});

function SystemStatus() {
  const { apiConnected } = useJockyStore();
  const [systemInfo, setSystemInfo] = React.useState<SystemInfoResult | null>(null);
  const [processes, setProcesses] = React.useState<ProcessesResult | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [sysRes, procRes] = await Promise.all([
        sendCommand("SYSTEM INFO"),
        sendCommand("PROCESSES"),
      ]);
      if (sysRes.result?.action === "system_info") setSystemInfo(sysRes.result);
      if (procRes.result?.action === "processes") setProcesses(procRes.result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reach the JOCKY API.");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    if (apiConnected) void refresh();
  }, [apiConnected, refresh]);

  return (
    <AppShell
      title="System Status"
      description="Read-only host & engine monitoring"
      actions={
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5"
          onClick={() => void refresh()}
          disabled={loading}
        >
          {loading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCcw className="h-3.5 w-3.5" />
          )}
          Refresh
        </Button>
      }
    >
      <p className="mb-6 max-w-2xl text-xs text-muted-foreground">
        This view is for authorized, read-only forensic observation only. JOCKY does not disable,
        bypass, or otherwise act on security products or monitoring controls.
      </p>

      {apiConnected === false ? (
        <div className="flex items-center gap-2 rounded-lg border border-critical/30 bg-critical/10 px-4 py-3 text-sm text-critical">
          <AlertCircle className="h-4 w-4 shrink-0" />
          The JOCKY API is unreachable, so live host metrics cannot be collected right now.
        </div>
      ) : error ? (
        <div className="flex items-center gap-2 rounded-lg border border-critical/30 bg-critical/10 px-4 py-3 text-sm text-critical">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      ) : null}

      {!systemInfo && loading && (
        <div className="flex items-center gap-2 rounded-lg border border-border bg-card px-4 py-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
          Collecting host telemetry...
        </div>
      )}

      {systemInfo && (
        <div className="space-y-6">
          <div className="rounded-xl border border-border bg-card p-5">
            <p className="mb-4 text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">
              Host Information
            </p>
            <DataGrid>
              <DataField label="Hostname" value={systemInfo.hostname} mono />
              <DataField
                label="Operating System"
                value={`${systemInfo.os} ${systemInfo.os_release}`}
                mono
              />
              <DataField label="Architecture" value={systemInfo.architecture} mono />
              <DataField label="Logical Cores" value={systemInfo.cpu_logical_cores ?? "—"} mono />
              <DataField label="Uptime" value={formatUptime(systemInfo.uptime_seconds)} mono />
              <DataField
                label="Last Collected"
                value={formatTimestamp(systemInfo.collected_at)}
                mono
              />
            </DataGrid>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="mb-2 flex items-center justify-between text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <Cpu className="h-3.5 w-3.5" /> CPU
                </span>
                <span className="font-mono text-foreground">
                  {systemInfo.cpu_percent?.toFixed(1) ?? "—"}%
                </span>
              </div>
              <Progress value={systemInfo.cpu_percent ?? 0} />
            </div>
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="mb-2 flex items-center justify-between text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">
                <span>Memory</span>
                <span className="font-mono text-foreground">
                  {systemInfo.memory_used_percent?.toFixed(1) ?? "—"}%
                </span>
              </div>
              <Progress value={systemInfo.memory_used_percent ?? 0} />
              <p className="mt-1.5 text-[10.5px] text-muted-foreground">
                {systemInfo.memory_available_gb?.toFixed(1) ?? "—"} /{" "}
                {systemInfo.memory_total_gb?.toFixed(1) ?? "—"} GB free
              </p>
            </div>
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="mb-2 flex items-center justify-between text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">
                <span>Disk</span>
                <span className="font-mono text-foreground">
                  {systemInfo.disk_used_percent?.toFixed(1) ?? "—"}%
                </span>
              </div>
              <Progress value={systemInfo.disk_used_percent ?? 0} />
              <p className="mt-1.5 text-[10.5px] text-muted-foreground">
                {systemInfo.disk_total_gb?.toFixed(1) ?? "—"} GB total
              </p>
            </div>
          </div>

          {processes && (
            <div className="rounded-xl border border-border bg-card p-5">
              <p className="mb-4 text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">
                Process Observation
              </p>
              <ProcessesTable result={processes} />
            </div>
          )}

          <div className="rounded-xl border border-border bg-card p-5">
            <p className="mb-2 text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">
              Network Metadata
            </p>
            <p className="text-xs text-muted-foreground">
              Network interface metadata is not currently exposed by the analysis engine. Extend
              <code className="mx-1 rounded bg-secondary px-1 py-0.5 font-mono text-[11px]">
                analysis/system.py
              </code>
              to surface it here if your investigation requires it.
            </p>
          </div>
        </div>
      )}
    </AppShell>
  );
}
