// JOCKY -> local Flask API connector.
// Base URL is configurable so the same build works when the Flask host/port changes.
// Set VITE_API_BASE_URL in .env to override the default.
import type { CommandReferenceEntry, CommandResponse } from "@/lib/types";

const DEFAULT_BASE_URL = "http://localhost:5000";

export const API_BASE_URL: string = (
  (import.meta.env["VITE_API_BASE_URL"] as string | undefined) ?? DEFAULT_BASE_URL
).replace(/\/+$/, "");

const REQUEST_TIMEOUT_MS = 15_000;

/**
 * A page served over https cannot call http://127.0.0.1 (browser mixed-content block),
 * so detect that up front and report it instead of showing a generic network failure.
 */
export function isMixedContentBlocked(): boolean {
  if (typeof window === "undefined") return false;
  return window.location.protocol === "https:" && API_BASE_URL.startsWith("http://");
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await fetch(`${API_BASE_URL}${path}`, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

export async function checkHealth(): Promise<boolean> {
  if (isMixedContentBlocked()) return false;
  try {
    const response = await request("/health");
    return response.ok;
  } catch {
    return false;
  }
}

export async function fetchCommandReference(): Promise<CommandReferenceEntry[]> {
  try {
    const response = await request("/commands");
    if (!response.ok) return [];
    const data = (await response.json()) as { commands?: CommandReferenceEntry[] };
    return data.commands ?? [];
  } catch {
    return [];
  }
}

export async function sendCommand(command: string): Promise<CommandResponse> {
  if (isMixedContentBlocked()) {
    throw new Error(
      `Blocked: this page is served over HTTPS and cannot reach ${API_BASE_URL}. Run the app locally to use your local Flask API.`,
    );
  }

  let response: Response;
  const startedAt = performance.now();
  try {
    response = await request("/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command }),
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("The Flask API did not respond in time.");
    }
    throw new Error("Could not reach the JOCKY API. Confirm the Flask server is running.");
  }

  let data: CommandResponse | null = null;
  try {
    data = (await response.json()) as CommandResponse;
  } catch {
    data = null;
  }

  const clientElapsedMs = performance.now() - startedAt;

  if (!data) {
    throw new Error("The JOCKY API returned an invalid response.");
  }

  if (!response.ok || data.status === "error") {
    const error = new Error(data.error ?? `API returned status ${response.status}.`) as Error & {
      report?: CommandResponse["report"];
    };
    error.report = data.report;
    throw error;
  }

  // Backfill a client-measured duration if the server didn't report one.
  if (
    data.report &&
    (data.report.execution_time_ms === null || data.report.execution_time_ms === undefined)
  ) {
    data.report.execution_time_ms = Math.round(clientElapsedMs);
  }

  return data;
}
