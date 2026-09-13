import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowLeft, Printer } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { ReportDocument } from "@/components/reports/report-document";
import { useJockyStore } from "@/lib/store";

export const Route = createFileRoute("/reports/$reportId")({
  component: ReportViewer,
  head: () => ({
    meta: [{ title: "Report — JOCKY" }],
  }),
});

function ReportViewer() {
  const { reportId } = Route.useParams();
  const { reports } = useJockyStore();
  const report = reports.find((r) => r.report_id === reportId);

  return (
    <AppShell
      title={reportId}
      description="Digital forensics analysis report"
      actions={
        report ? (
          <div className="hidden items-center gap-2 sm:flex">
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => window.print()}>
              <Printer className="h-3.5 w-3.5" />
              Print Report
            </Button>
            <Button size="sm" className="gap-1.5" onClick={() => window.print()}>
              Save as PDF
            </Button>
          </div>
        ) : undefined
      }
    >
      <div className="mb-5 print:hidden">
        <Link
          to="/reports"
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to Report Archive
        </Link>
      </div>

      {!report ? (
        <div className="rounded-xl border border-dashed border-border px-6 py-16 text-center">
          <p className="text-sm text-foreground">Report not found in this session.</p>
          <p className="mt-1.5 text-xs text-muted-foreground">
            Reports are stored locally in your browser and are not shared between devices.
          </p>
        </div>
      ) : (
        <>
          <div className="mb-4 flex justify-center gap-2 sm:hidden print:hidden">
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => window.print()}>
              <Printer className="h-3.5 w-3.5" />
              Print / Save as PDF
            </Button>
          </div>
          <ReportDocument report={report} />
        </>
      )}
    </AppShell>
  );
}
