import { Lock } from "lucide-react";
import { DataField, DataGrid } from "@/components/forensics/data-field";
import type { EncryptResult } from "@/lib/types";

export function EncryptResultCard({ result }: { result: EncryptResult }) {
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2 rounded-lg border border-success/30 bg-success/10 p-3 text-sm text-success">
        <Lock className="h-4 w-4 shrink-0" />
        {result.message}
      </div>
      <DataGrid>
        <DataField label="Action" value={result.action} mono />
        <DataField label="Target" value={result.path} mono wrap />
        <DataField label="Status" value={result.status} mono />
      </DataGrid>
    </div>
  );
}
