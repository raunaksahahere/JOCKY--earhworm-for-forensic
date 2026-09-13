import {
  AlertTriangle,
  CheckCircle2,
  FileDigit,
  HelpCircle,
  History,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { DataField, DataGrid } from "@/components/forensics/data-field";
import { CopyButton } from "@/components/forensics/copy-button";
import { IndicatorBadges } from "@/components/forensics/indicator-badges";
import { formatBytes, formatTimestamp } from "@/lib/format";
import type { HashResult, IntegrityHistoryStatus, IntegrityStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const INTEGRITY_STYLE: Record<IntegrityStatus, { icon: typeof ShieldCheck; classes: string }> = {
  ok: { icon: ShieldCheck, classes: "border-success/30 bg-success/10 text-success" },
  warning: { icon: AlertTriangle, classes: "border-warning/30 bg-warning/10 text-warning" },
  critical: { icon: ShieldAlert, classes: "border-critical/30 bg-critical/10 text-critical" },
  unknown: {
    icon: HelpCircle,
    classes: "border-border-strong bg-secondary/40 text-muted-foreground",
  },
};

const HISTORY_STYLE: Record<IntegrityHistoryStatus, { icon: typeof History; classes: string }> = {
  first_recorded: { icon: History, classes: "border-info/30 bg-info/10 text-info" },
  unchanged: { icon: CheckCircle2, classes: "border-success/30 bg-success/10 text-success" },
  altered: { icon: ShieldAlert, classes: "border-critical/30 bg-critical/10 text-critical" },
  algorithm_mismatch: {
    icon: AlertTriangle,
    classes: "border-warning/30 bg-warning/10 text-warning",
  },
};

export function HashResultCard({ result }: { result: HashResult }) {
  const integrity = INTEGRITY_STYLE[result.integrity_check.status];
  const IntegrityIcon = integrity.icon;
  const history = HISTORY_STYLE[result.integrity_history.status];
  const HistoryIcon = history.icon;

  return (
    <div className="space-y-5">
      <DataGrid>
        <DataField label="Target" value={result.filename} mono wrap />
        <DataField label="Algorithm" value={result.algorithm} mono />
        <DataField label="File Size" value={formatBytes(result.size_bytes)} mono />
        <DataField label="Modified" value={formatTimestamp(result.modified)} mono />
        <DataField label="Verification State" value={result.verification_state} mono />
        <DataField label="Absolute Path" value={result.absolute_path} mono wrap />
      </DataGrid>

      <div className="rounded-lg border border-border bg-void/60 p-4">
        <div className="mb-2 flex items-center gap-2 text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">
          <FileDigit className="h-3.5 w-3.5" />
          {result.algorithm} Digest
        </div>
        <div className="flex items-start gap-2">
          <p className="min-w-0 flex-1 break-all font-mono text-[13px] leading-relaxed text-primary">
            {result.hash}
          </p>
          <CopyButton value={result.hash} />
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className={cn("flex items-start gap-2.5 rounded-lg border p-3.5", integrity.classes)}>
          <IntegrityIcon className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0">
            <p className="text-[10.5px] font-semibold uppercase tracking-wider">
              Integrity Check · {result.integrity_check.file_type}
            </p>
            <p className="mt-0.5 text-[12.5px] leading-relaxed">{result.integrity_check.message}</p>
          </div>
        </div>

        <div className={cn("flex items-start gap-2.5 rounded-lg border p-3.5", history.classes)}>
          <HistoryIcon className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0">
            <p className="text-[10.5px] font-semibold uppercase tracking-wider">
              Change Since Last Hash
            </p>
            <p className="mt-0.5 text-[12.5px] leading-relaxed">
              {result.integrity_history.message}
            </p>
            {result.previous_hash && (
              <p className="mt-1.5 break-all font-mono text-[10.5px] opacity-80">
                Previous {result.previous_hash.algorithm}: {result.previous_hash.hash}
              </p>
            )}
          </div>
        </div>
      </div>

      {result.indicators.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">
            Static Indicators
          </p>
          <IndicatorBadges indicators={result.indicators} />
        </div>
      )}
    </div>
  );
}
