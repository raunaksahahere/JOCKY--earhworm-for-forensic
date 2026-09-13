import { SearchCheck } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { DataField, DataGrid } from "@/components/forensics/data-field";
import { IndicatorBadges } from "@/components/forensics/indicator-badges";
import { formatBytes, formatTimestamp } from "@/lib/format";
import type { SearchResult } from "@/lib/types";

export function SearchResultCard({ result }: { result: SearchResult }) {
  return (
    <div className="space-y-5">
      <DataGrid>
        <DataField label="Search Target" value={result.search_target} mono />
        <DataField label="Directory" value={result.search_directory} mono wrap />
        <DataField label="Entries Scanned" value={result.entries_scanned.toLocaleString()} mono />
      </DataGrid>

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <SearchCheck className="h-3.5 w-3.5 text-primary" />
          <span className="font-mono text-foreground">{result.match_count}</span> match
          {result.match_count === 1 ? "" : "es"} found
        </span>
        {result.truncated && (
          <Badge variant="outline" className="border-warning/30 text-warning">
            Results truncated
          </Badge>
        )}
      </div>

      {result.results.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          No files matched &ldquo;{result.search_target}&rdquo;.
        </p>
      ) : (
        <div className="max-h-[420px] overflow-y-auto rounded-lg border border-border scrollbar-thin">
          <Table>
            <TableHeader className="sticky top-0 z-10 bg-surface">
              <TableRow className="hover:bg-transparent">
                <TableHead className="font-mono text-[10.5px] uppercase tracking-wider">
                  Path
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
              {result.results.map((match) => (
                <TableRow key={match.path} className="hover:bg-secondary/40">
                  <TableCell className="max-w-72 truncate font-mono text-[13px] text-foreground">
                    {match.path}
                  </TableCell>
                  <TableCell className="text-right font-mono text-[13px] tabular-nums text-foreground">
                    {formatBytes(match.size_bytes)}
                  </TableCell>
                  <TableCell className="font-mono text-[11.5px] text-muted-foreground">
                    {formatTimestamp(match.modified)}
                  </TableCell>
                  <TableCell>
                    <IndicatorBadges indicators={match.indicators} />
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
