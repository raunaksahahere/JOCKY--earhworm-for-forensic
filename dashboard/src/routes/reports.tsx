import { createFileRoute, Link } from "@tanstack/react-router";
import { FileText } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { EmptyState } from "@/components/layout/empty-state";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDuration, formatTimestamp } from "@/lib/format";
import { useJockyStore } from "@/lib/store";

export const Route = createFileRoute("/reports")({
  component: ReportsArchive,
  head: () => ({
    meta: [
      { title: "Reports — JOCKY" },
      { name: "description", content: "Archive of structured forensic analysis reports." },
    ],
  }),
});

function ReportsArchive() {
  const { reports, investigations } = useJockyStore();

  const investigationOf = (reportId: string) =>
    investigations.find((inv) => inv.reportIds.includes(reportId))?.id ?? "—";

  return (
    <AppShell title="Reports" description="Forensic report archive">
      {reports.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No reports generated yet"
          description="Every completed command produces a structured, timestamped report. Run a command to populate the archive."
          action={
            <Link to="/command-center">
              <Button size="sm">Open Command Center</Button>
            </Link>
          }
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="font-mono text-[10.5px] uppercase tracking-wider">
                  Report ID
                </TableHead>
                <TableHead className="font-mono text-[10.5px] uppercase tracking-wider">
                  Investigation
                </TableHead>
                <TableHead className="font-mono text-[10.5px] uppercase tracking-wider">
                  Command
                </TableHead>
                <TableHead className="font-mono text-[10.5px] uppercase tracking-wider">
                  Action
                </TableHead>
                <TableHead className="font-mono text-[10.5px] uppercase tracking-wider">
                  Target
                </TableHead>
                <TableHead className="font-mono text-[10.5px] uppercase tracking-wider">
                  Status
                </TableHead>
                <TableHead className="font-mono text-[10.5px] uppercase tracking-wider">
                  Date
                </TableHead>
                <TableHead className="text-right font-mono text-[10.5px] uppercase tracking-wider">
                  Runtime
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {reports.map((report) => (
                <TableRow key={report.report_id} className="hover:bg-secondary/40">
                  <TableCell>
                    <Link
                      to="/reports/$reportId"
                      params={{ reportId: report.report_id }}
                      className="font-mono text-[12.5px] text-primary hover:underline"
                    >
                      {report.report_id}
                    </Link>
                  </TableCell>
                  <TableCell className="font-mono text-[12px] text-muted-foreground">
                    {investigationOf(report.report_id)}
                  </TableCell>
                  <TableCell className="max-w-52 truncate font-mono text-[12.5px] text-foreground">
                    {report.command}
                  </TableCell>
                  <TableCell className="font-mono text-[11.5px] text-muted-foreground">
                    {report.action ?? "—"}
                  </TableCell>
                  <TableCell className="max-w-40 truncate font-mono text-[11.5px] text-muted-foreground">
                    {report.target ?? "—"}
                  </TableCell>
                  <TableCell>
                    <span
                      className={
                        "font-mono text-[11px] uppercase " +
                        (report.status === "completed" ? "text-success" : "text-critical")
                      }
                    >
                      {report.status}
                    </span>
                  </TableCell>
                  <TableCell className="font-mono text-[11.5px] text-muted-foreground">
                    {formatTimestamp(report.timestamp)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-[12px] tabular-nums text-muted-foreground">
                    {formatDuration(report.execution_time_ms)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </AppShell>
  );
}
