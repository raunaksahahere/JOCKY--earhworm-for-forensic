import { AlertOctagon } from "lucide-react";
import { ResultHeader } from "@/components/forensics/result-header";
import { HashResultCard } from "@/components/forensics/hash-result-card";
import { SystemInfoCard } from "@/components/forensics/system-info-card";
import { ProcessesTable } from "@/components/forensics/processes-table";
import { ListResultCard } from "@/components/forensics/list-result-card";
import { SearchResultCard } from "@/components/forensics/search-result-card";
import { EncryptResultCard } from "@/components/forensics/encrypt-result-card";
import type { Report } from "@/lib/types";

export function ResultView({ report }: { report: Report }) {
  return (
    <div className="space-y-5">
      <ResultHeader
        command={report.command}
        action={report.action}
        status={report.status}
        executionTimeMs={report.execution_time_ms}
      />

      {report.status === "failed" ? (
        <div className="flex items-start gap-2.5 rounded-lg border border-critical/30 bg-critical/10 p-4 text-sm text-critical">
          <AlertOctagon className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="space-y-1">
            {report.errors.length > 0 ? (
              report.errors.map((err, i) => <p key={i}>{err}</p>)
            ) : (
              <p>The command could not be completed.</p>
            )}
          </div>
        </div>
      ) : (
        <ResultBody report={report} />
      )}
    </div>
  );
}

function ResultBody({ report }: { report: Report }) {
  const result = report.result;
  if (!result || !("action" in result)) {
    return <p className="text-sm text-muted-foreground">No structured result was returned.</p>;
  }

  switch (result.action) {
    case "hash":
      return <HashResultCard result={result} />;
    case "system_info":
      return <SystemInfoCard result={result} />;
    case "processes":
      return <ProcessesTable result={result} />;
    case "list":
      return <ListResultCard result={result} />;
    case "search":
      return <SearchResultCard result={result} />;
    case "encrypt":
    case "decrypt":
      return <EncryptResultCard result={result} />;
    default:
      return (
        <pre className="scrollbar-thin overflow-x-auto rounded-lg border border-border bg-void/60 p-4 font-mono text-xs text-muted-foreground">
          {JSON.stringify(result, null, 2)}
        </pre>
      );
  }
}
