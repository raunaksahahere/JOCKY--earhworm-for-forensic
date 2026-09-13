import { File, Folder } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { IndicatorBadges } from "@/components/forensics/indicator-badges";
import { formatBytes, formatTimestamp } from "@/lib/format";
import type { ListResult } from "@/lib/types";

export function ListResultCard({ result }: { result: ListResult }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>
          <span className="font-mono text-foreground">{result.entry_count}</span> entries in{" "}
          <span className="font-mono text-foreground">{result.target}</span>
        </span>
        {result.truncated && (
          <Badge variant="outline" className="border-warning/30 text-warning">
            List truncated
          </Badge>
        )}
      </div>

      {result.entries.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          This directory is empty.
        </p>
      ) : (
        <div className="max-h-[420px] overflow-y-auto rounded-lg border border-border scrollbar-thin">
          <Table>
            <TableHeader className="sticky top-0 z-10 bg-surface">
              <TableRow className="hover:bg-transparent">
                <TableHead className="font-mono text-[10.5px] uppercase tracking-wider">
                  Name
                </TableHead>
                <TableHead className="font-mono text-[10.5px] uppercase tracking-wider">
                  Type
                </TableHead>
                <TableHead className="text-right font-mono text-[10.5px] uppercase tracking-wider">
                  Size
                </TableHead>
                <TableHead className="font-mono text-[10.5px] uppercase tracking-wider">
                  Modified
                </TableHead>
                <TableHead className="font-mono text-[10.5px] uppercase tracking-wider">
                  Indicators
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {result.entries.map((entry) => (
                <TableRow key={entry.path} className="hover:bg-secondary/40">
                  <TableCell className="max-w-56 font-mono text-[13px] text-foreground">
                    <span className="flex items-center gap-2">
                      {entry.type === "directory" ? (
                        <Folder className="h-3.5 w-3.5 shrink-0 text-primary" />
                      ) : (
                        <File className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      )}
                      <span className="truncate">{entry.name}</span>
                    </span>
                  </TableCell>
                  <TableCell className="font-mono text-[12px] text-muted-foreground">
                    {entry.type}
                  </TableCell>
                  <TableCell className="text-right font-mono text-[13px] tabular-nums text-foreground">
                    {entry.type === "directory" ? "—" : formatBytes(entry.size_bytes)}
                  </TableCell>
                  <TableCell className="font-mono text-[11.5px] text-muted-foreground">
                    {formatTimestamp(entry.modified)}
                  </TableCell>
                  <TableCell>
                    <IndicatorBadges indicators={entry.indicators} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
