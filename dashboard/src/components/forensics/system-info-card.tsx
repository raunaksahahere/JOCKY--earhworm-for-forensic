import { DataField, DataGrid } from "@/components/forensics/data-field";
import { Progress } from "@/components/ui/progress";
import { formatTimestamp, formatUptime } from "@/lib/format";
import type { SystemInfoResult } from "@/lib/types";

export function SystemInfoCard({ result }: { result: SystemInfoResult }) {
  return (
    <div className="space-y-5">
      <DataGrid>
        <DataField label="Hostname" value={result.hostname} mono />
        <DataField label="Operating System" value={`${result.os} ${result.os_release}`} mono />
        <DataField label="Architecture" value={result.architecture} mono />
        <DataField label="Processor" value={result.processor} mono wrap />
        <DataField label="Logical Cores" value={result.cpu_logical_cores ?? "—"} mono />
        <DataField label="Python Runtime" value={result.python_runtime} mono />
        <DataField label="Boot Time" value={formatTimestamp(result.boot_time)} mono />
        <DataField label="Uptime" value={formatUptime(result.uptime_seconds)} mono />
        <DataField label="Collected At" value={formatTimestamp(result.collected_at)} mono />
      </DataGrid>

      {(result.memory_used_percent !== undefined || result.disk_used_percent !== undefined) && (
        <div className="grid gap-4 sm:grid-cols-2">
          {result.memory_used_percent !== undefined && (
            <div className="rounded-lg border border-border bg-void/60 p-4">
              <div className="mb-2 flex items-center justify-between text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">
                <span>Memory</span>
                <span className="font-mono text-foreground">
                  {result.memory_available_gb?.toFixed(1)} / {result.memory_total_gb?.toFixed(1)} GB
                  free
                </span>
              </div>
              <Progress value={result.memory_used_percent} />
              <p className="mt-1.5 text-right font-mono text-[11px] text-muted-foreground">
                {result.memory_used_percent.toFixed(1)}% used
              </p>
            </div>
          )}
          {result.disk_used_percent !== undefined && (
            <div className="rounded-lg border border-border bg-void/60 p-4">
              <div className="mb-2 flex items-center justify-between text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">
                <span>Disk</span>
                <span className="font-mono text-foreground">
                  {result.disk_total_gb?.toFixed(1)} GB total
                </span>
              </div>
              <Progress value={result.disk_used_percent} />
              <p className="mt-1.5 text-right font-mono text-[11px] text-muted-foreground">
                {result.disk_used_percent.toFixed(1)}% used
              </p>
            </div>
          )}
        </div>
      )}

      {result.monitoring_note && (
        <p className="text-xs text-muted-foreground">{result.monitoring_note}</p>
      )}
    </div>
  );
}
