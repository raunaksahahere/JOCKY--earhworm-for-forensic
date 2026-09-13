import * as React from "react";
import type { CommandResponse, HistoryEntry, Investigation, Report } from "@/lib/types";

const STORAGE_KEY = "jocky:v1";

interface PersistedState {
  history: HistoryEntry[];
  reports: Report[];
  investigations: Investigation[];
}

function emptyState(): PersistedState {
  return { history: [], reports: [], investigations: [] };
}

function seedInvestigation(): Investigation {
  return {
    id: "INV-0001",
    title: "Untitled Investigation",
    createdAt: new Date().toISOString(),
    analystNotes: "",
    commandIds: [],
    reportIds: [],
  };
}

function loadState(): PersistedState {
  if (typeof window === "undefined") return emptyState();
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return emptyState();
    const parsed = JSON.parse(raw) as Partial<PersistedState>;
    return {
      history: parsed.history ?? [],
      reports: parsed.reports ?? [],
      investigations: parsed.investigations ?? [],
    };
  } catch {
    return emptyState();
  }
}

function saveState(state: PersistedState) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Storage may be unavailable (private browsing, quota) -- fail silently,
    // the session still works, it just won't persist across reloads.
  }
}

interface JockyStoreValue extends PersistedState {
  hydrated: boolean;
  apiConnected: boolean | null;
  setApiConnected: (connected: boolean) => void;
  recordExecution: (
    command: string,
    response: CommandResponse,
    activeInvestigationId?: string,
  ) => HistoryEntry;
  recordFailure: (
    command: string,
    error: Error & { report?: Report },
    activeInvestigationId?: string,
  ) => HistoryEntry;
  clearHistory: () => void;
  resetAllData: () => void;
  addInvestigation: (title: string) => Investigation;
  updateInvestigationNotes: (id: string, notes: string) => void;
  activeInvestigationId: string;
  setActiveInvestigationId: (id: string) => void;
}

const JockyStoreContext = React.createContext<JockyStoreValue | null>(null);

export function JockyStoreProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = React.useState<PersistedState>(emptyState);
  const [hydrated, setHydrated] = React.useState(false);
  const [apiConnected, setApiConnectedState] = React.useState<boolean | null>(null);
  const [activeInvestigationId, setActiveInvestigationId] = React.useState<string>("INV-0001");

  React.useEffect(() => {
    const loaded = loadState();
    if (loaded.investigations.length === 0) {
      loaded.investigations = [seedInvestigation()];
    }
    setState(loaded);
    setHydrated(true);
  }, []);

  React.useEffect(() => {
    if (hydrated) saveState(state);
  }, [state, hydrated]);

  const setApiConnected = React.useCallback((connected: boolean) => {
    setApiConnectedState(connected);
  }, []);

  const recordExecution = React.useCallback(
    (command: string, response: CommandResponse, invId?: string): HistoryEntry => {
      const entry: HistoryEntry = {
        id: `H-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
        command,
        status: "success",
        timestamp: new Date().toISOString(),
        executionTimeMs: response.report?.execution_time_ms ?? null,
        reportId: response.report?.report_id ?? null,
      };
      setState((prev) => {
        const targetInvId = invId ?? "INV-0001";
        const investigations = prev.investigations.map((inv) =>
          inv.id === targetInvId
            ? {
                ...inv,
                commandIds: [entry.id, ...inv.commandIds],
                reportIds: response.report
                  ? [response.report.report_id, ...inv.reportIds]
                  : inv.reportIds,
              }
            : inv,
        );
        return {
          history: [entry, ...prev.history].slice(0, 200),
          reports: response.report
            ? [response.report, ...prev.reports].slice(0, 200)
            : prev.reports,
          investigations,
        };
      });
      return entry;
    },
    [],
  );

  const recordFailure = React.useCallback(
    (command: string, error: Error & { report?: Report }, invId?: string): HistoryEntry => {
      const entry: HistoryEntry = {
        id: `H-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
        command,
        status: "error",
        timestamp: new Date().toISOString(),
        executionTimeMs: error.report?.execution_time_ms ?? null,
        reportId: error.report?.report_id ?? null,
      };
      setState((prev) => {
        const targetInvId = invId ?? "INV-0001";
        const investigations = prev.investigations.map((inv) =>
          inv.id === targetInvId
            ? {
                ...inv,
                commandIds: [entry.id, ...inv.commandIds],
                reportIds: error.report
                  ? [error.report.report_id, ...inv.reportIds]
                  : inv.reportIds,
              }
            : inv,
        );
        return {
          history: [entry, ...prev.history].slice(0, 200),
          reports: error.report ? [error.report, ...prev.reports].slice(0, 200) : prev.reports,
          investigations,
        };
      });
      return entry;
    },
    [],
  );

  const clearHistory = React.useCallback(() => {
    setState((prev) => ({ ...prev, history: [] }));
  }, []);

  const resetAllData = React.useCallback(() => {
    const fresh = emptyState();
    fresh.investigations = [seedInvestigation()];
    setState(fresh);
    setActiveInvestigationId("INV-0001");
  }, []);

  const addInvestigation = React.useCallback((title: string): Investigation => {
    const inv: Investigation = {
      id: `INV-${Math.random().toString(36).slice(2, 6).toUpperCase()}`,
      title: title.trim() || "Untitled Investigation",
      createdAt: new Date().toISOString(),
      analystNotes: "",
      commandIds: [],
      reportIds: [],
    };
    setState((prev) => ({ ...prev, investigations: [inv, ...prev.investigations] }));
    return inv;
  }, []);

  const updateInvestigationNotes = React.useCallback((id: string, notes: string) => {
    setState((prev) => ({
      ...prev,
      investigations: prev.investigations.map((inv) =>
        inv.id === id ? { ...inv, analystNotes: notes } : inv,
      ),
    }));
  }, []);

  const value: JockyStoreValue = {
    ...state,
    hydrated,
    apiConnected,
    setApiConnected,
    recordExecution,
    recordFailure,
    clearHistory,
    resetAllData,
    addInvestigation,
    updateInvestigationNotes,
    activeInvestigationId,
    setActiveInvestigationId,
  };

  return <JockyStoreContext.Provider value={value}>{children}</JockyStoreContext.Provider>;
}

export function useJockyStore(): JockyStoreValue {
  const ctx = React.useContext(JockyStoreContext);
  if (!ctx) throw new Error("useJockyStore must be used within JockyStoreProvider");
  return ctx;
}
