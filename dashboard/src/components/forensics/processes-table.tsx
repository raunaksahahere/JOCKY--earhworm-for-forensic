import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { formatTimestamp } from "@/lib/format";
import type { ProcessesResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<string, string> = {
  running: "border-success/30 bg-success/10 text-success",
  sleeping: "border-info/30 bg-info/10 text-info",
  "disk-sleep": "border-warning/30 bg-warning/10 text-warning",
  stopped: "border-critical/30 bg-critical/10 text-critical",
  zombie: "border-critical/30 bg-critical/10 text-critical",
};

export function ProcessesTable({ result }: { result: ProcessesResult }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>
          Showing <span className="font-mono text-foreground">{result.returned_count}</span> of{" "}
          <span className="font-mono text-foreground">{result.process_count}</span> observed
          processes, sorted by memory use
        </span>
        {result.truncated && (
          <Badge variant="outline" className="border-warning/30 text-warning">
            List truncated
          </Badge>
        )}
      </div>

      <div className="max-h-[420px] overflow-y-auto rounded-lg border border-border scrollbar-thin">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-surface">
            <TableRow className="hover:bg-transparent">
              <TableHead className="font-mono text-[10.5px] uppercase tracking-wider">
                PID
              </TableHead>
              <TableHead className="font-mono text-[10.5px] uppercase tracking-wider">
                Name
              </TableHead>
              <TableHead className="font-mono text-[10.5px] uppercase tracking-wider">
                User
              </TableHead>
              <TableHead className="font-mono text-[10.5px] uppercase tracking-wider">
                Status
              </TableHead>
              <TableHead className="text-right font-mono text-[10.5px] uppercase tracking-wider">
                Mem %
              </TableHead>
              <TableHead className="text-right font-mono text-[10.5px] uppercase tracking-wider">
                CPU %
              </TableHead>
              <TableHead className="font-mono text-[10.5px] uppercase tracking-wider">
                Started
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {result.processes.map((proc) => (
              <TableRow key={proc.pid} className="hover:bg-secondary/40">
                <TableCell className="font-mono text-[13px] text-muted-foreground">
                  {proc.pid}
                </TableCell>
                <TableCell className="max-w-40 truncate font-mono text-[13px] text-foreground">
                  {proc.name}
                </TableCell>
                <TableCell className="max-w-28 truncate font-mono text-[12px] text-muted-foreground">
                  {proc.username}
                </TableCell>
                <TableCell>
                  <span
                    className={cn(
                      "inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[11px]",
                      STATUS_TONE[proc.status] ?? "border-border text-muted-foreground",
                    )}
                  >
                    {proc.status}
                  </span>
                </TableCell>
                <TableCell className="text-right font-mono text-[13px] tabular-nums text-foreground">
                  {proc.memory_percent?.toFixed(2) ?? "—"}
                </TableCell>
                <TableCell className="text-right font-mono text-[13px] tabular-nums text-foreground">
                  {proc.cpu_percent?.toFixed(1) ?? "—"}
                </TableCell>
                <TableCell className="font-mono text-[11.5px] text-muted-foreground">
                  {formatTimestamp(proc.created)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
