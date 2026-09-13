import * as React from "react";
import { createFileRoute } from "@tanstack/react-router";
import { CheckCircle2, Loader2, Trash2, XCircle } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/layout/status-pill";
import { API_BASE_URL, checkHealth } from "@/services/api";
import { useJockyStore } from "@/lib/store";

export const Route = createFileRoute("/settings")({
  component: Settings,
  head: () => ({
    meta: [{ title: "Settings — JOCKY" }],
  }),
});

function Settings() {
  const { apiConnected, setApiConnected, history, reports, investigations, resetAllData } =
    useJockyStore();
  const [testing, setTesting] = React.useState(false);
  const [confirmingReset, setConfirmingReset] = React.useState(false);

  const testConnection = async () => {
    setTesting(true);
    const healthy = await checkHealth();
    setApiConnected(healthy);
    setTesting(false);
  };

  return (
    <AppShell title="Settings" description="API connection & local data">
      <div className="max-w-2xl space-y-6">
        <section className="rounded-xl border border-border bg-card p-5">
          <h2 className="text-sm font-medium text-foreground">API Connection</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            JOCKY talks to a local Flask API. Set{" "}
            <code className="rounded bg-secondary px-1 py-0.5 font-mono text-[11px]">
              VITE_API_BASE_URL
            </code>{" "}
            in your
            <code className="mx-1 rounded bg-secondary px-1 py-0.5 font-mono text-[11px]">
              .env
            </code>
            file to point the frontend at a different host or port, then rebuild.
          </p>

          <div className="mt-4 flex items-center justify-between rounded-lg border border-border bg-void/60 px-4 py-3">
            <div>
              <p className="text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">
                Base URL
              </p>
              <p className="mt-1 font-mono text-sm text-foreground">{API_BASE_URL}</p>
            </div>
            <StatusPill
              tone={apiConnected === null ? "muted" : apiConnected ? "success" : "critical"}
              label={apiConnected === null ? "UNKNOWN" : apiConnected ? "CONNECTED" : "UNREACHABLE"}
            />
          </div>

          <Button
            variant="outline"
            size="sm"
            className="mt-4 gap-1.5"
            onClick={() => void testConnection()}
            disabled={testing}
          >
            {testing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : apiConnected ? (
              <CheckCircle2 className="h-3.5 w-3.5 text-success" />
            ) : (
              <XCircle className="h-3.5 w-3.5 text-critical" />
            )}
            Test Connection
          </Button>
        </section>

        <section className="rounded-xl border border-border bg-card p-5">
          <h2 className="text-sm font-medium text-foreground">Local Session Data</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Command history, reports, and investigations are stored only in this browser
            (localStorage). Nothing is sent anywhere except your JOCKY API.
          </p>

          <div className="mt-4 grid grid-cols-3 gap-3 text-center">
            <div className="rounded-lg border border-border bg-void/60 py-3">
              <p className="font-mono text-lg font-semibold text-foreground">{history.length}</p>
              <p className="text-[10px] uppercase text-muted-foreground">History</p>
            </div>
            <div className="rounded-lg border border-border bg-void/60 py-3">
              <p className="font-mono text-lg font-semibold text-foreground">{reports.length}</p>
              <p className="text-[10px] uppercase text-muted-foreground">Reports</p>
            </div>
            <div className="rounded-lg border border-border bg-void/60 py-3">
              <p className="font-mono text-lg font-semibold text-foreground">
                {investigations.length}
              </p>
              <p className="text-[10px] uppercase text-muted-foreground">Investigations</p>
            </div>
          </div>

          <div className="mt-4">
            {!confirmingReset ? (
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5 border-critical/30 text-critical hover:bg-critical/10 hover:text-critical"
                onClick={() => setConfirmingReset(true)}
              >
                <Trash2 className="h-3.5 w-3.5" />
                Reset Local Data
              </Button>
            ) : (
              <div className="flex items-center gap-2">
                <p className="text-xs text-critical">
                  This clears all local history, reports, and investigations. Continue?
                </p>
                <Button
                  size="sm"
                  variant="outline"
                  className="border-critical/30 text-critical"
                  onClick={() => {
                    resetAllData();
                    setConfirmingReset(false);
                  }}
                >
                  Confirm
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirmingReset(false)}>
                  Cancel
                </Button>
              </div>
            )}
          </div>
        </section>

        <section className="rounded-xl border border-border bg-card p-5">
          <h2 className="text-sm font-medium text-foreground">About</h2>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            JOCKY is a defensive digital forensics and security analysis platform. It performs
            read-only observation and evidence-handling utilities only — it does not implement
            offensive, evasive, or system-altering capabilities of any kind.
          </p>
        </section>
      </div>
    </AppShell>
  );
}
