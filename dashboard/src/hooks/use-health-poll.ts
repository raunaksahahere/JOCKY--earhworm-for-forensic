import * as React from "react";
import { checkHealth } from "@/services/api";
import { useJockyStore } from "@/lib/store";

const POLL_INTERVAL_MS = 15_000;

export function useHealthPoll() {
  const { apiConnected, setApiConnected } = useJockyStore();

  React.useEffect(() => {
    let cancelled = false;
    const run = () => {
      checkHealth().then((healthy) => {
        if (!cancelled) setApiConnected(healthy);
      });
    };
    run();
    const interval = setInterval(run, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [setApiConnected]);

  return apiConnected;
}
