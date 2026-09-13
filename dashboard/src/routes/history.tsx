import { createFileRoute, Link } from "@tanstack/react-router";
import { History as HistoryIcon, Trash2 } from "lucide-react";
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

export const Route = createFileRoute("/history")({
  component: HistoryPage,
  head: () => ({
    meta: [
      { title: "History — JOCKY" },
      { name: "description", content: "Full log of JOCKY commands executed this session." },
    ],
  }),
});

function HistoryPage() {
  const { history, clearHistory } = useJockyStore();

  return (
    <AppShell
      title="History"
      description="Command execution log"
      actions={
        history.length > 0 ? (
          <Button
            variant="ghost"
            size="sm"
            className="gap-1.5 text-xs text-muted-foreground"
            onClick={clearHistory}
          >
            <Trash2 className="h-3.5 w-3.5" />
            Clear
          </Button>
        ) : undefined
      }
    >
      {history.length === 0 ? (
        <EmptyState
          icon={HistoryIcon}
          title="No commands executed yet"
          description="Every command you run in the Command Center is logged here, in order, for the duration of your session."
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
                  Command
                </TableHead>
                <TableHead className="font-mono text-[10.5px] uppercase tracking-wider">
                  Status
                </TableHead>
                <TableHead className="text-right font-mono text-[10.5px] uppercase tracking-wider">
                  Duration
                </TableHead>
                <TableHead className="font-mono text-[10.5px] uppercase tracking-wider">
                  Timestamp
                </TableHead>
                <TableHead className="font-mono text-[10.5px] uppercase tracking-wider">
                  Report
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {history.map((entry) => (
                <TableRow key={entry.id} className="hover:bg-secondary/40">
                  <TableCell className="max-w-72 truncate font-mono text-[13px] text-foreground">
                    {entry.command}
                  </TableCell>
                  <TableCell>
                    <span
                      className={
                        "font-mono text-[11px] uppercase " +
                        (entry.status === "success" ? "text-success" : "text-critical")
                      }
                    >
                      {entry.status}
                    </span>
                  </TableCell>
                  <TableCell className="text-right font-mono text-[12.5px] tabular-nums text-muted-foreground">
                    {formatDuration(entry.executionTimeMs)}
                  </TableCell>
                  <TableCell className="font-mono text-[11.5px] text-muted-foreground">
                    {formatTimestamp(entry.timestamp)}
                  </TableCell>
                  <TableCell>
                    {entry.reportId ? (
                      <Link
                        to="/reports/$reportId"
                        params={{ reportId: entry.reportId }}
                        className="font-mono text-[11.5px] text-primary hover:underline"
                      >
                        {entry.reportId}
                      </Link>
                    ) : (
                      <span className="text-[11.5px] text-muted-foreground">—</span>
                    )}
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
