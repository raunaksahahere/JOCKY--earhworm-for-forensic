// Types mirror the JSON shapes produced by the Flask API
// (communication/server.py, communication/dispatcher.py, analysis/*, reports/report.py).
// Keeping these in one file makes it obvious when the frontend and backend contracts drift.

export type IndicatorLevel = "info" | "warning" | "critical";

export interface Indicator {
  level: IndicatorLevel;
  label: string;
  detail: string;
}

export type IntegrityStatus = "ok" | "warning" | "critical" | "unknown";

export interface IntegrityCheck {
  performed: boolean;
  file_type: string;
  status: IntegrityStatus;
  message: string;
}

export type IntegrityHistoryStatus =
  "first_recorded" | "unchanged" | "altered" | "algorithm_mismatch";

export interface IntegrityHistory {
  has_previous: boolean;
  status: IntegrityHistoryStatus;
  message: string;
}

export interface PreviousHash {
  algorithm: string;
  hash: string;
  size_bytes: number;
  timestamp: string;
}

export interface HashResult {
  action: "hash";
  target: string;
  filename: string;
  algorithm: string;
  hash: string;
  size_bytes: number;
  modified: string;
  created: string | null;
  absolute_path: string;
  verification_state: string;
  integrity_check: IntegrityCheck;
  previous_hash: PreviousHash | null;
  integrity_history: IntegrityHistory;
  indicators: Indicator[];
  status: string;
  message: string;
}

export interface EncryptResult {
  action: "encrypt" | "decrypt";
  path: string;
  status: string;
  message: string;
}

export interface SystemInfoResult {
  action: "system_info";
  hostname: string;
  os: string;
  os_release: string;
  os_version: string;
  architecture: string;
  processor: string;
  cpu_logical_cores: number | null;
  cpu_physical_cores?: number | null;
  cpu_percent?: number;
  python_runtime: string;
  platform_string: string;
  memory_total_gb?: number;
  memory_available_gb?: number;
  memory_used_percent?: number;
  disk_total_gb?: number;
  disk_used_percent?: number;
  boot_time?: string;
  uptime_seconds?: number;
  monitoring_note?: string;
  collected_at: string;
  status: string;
  message: string;
}

export interface ProcessEntry {
  pid: number;
  name: string;
  username: string;
  status: string;
  memory_percent: number | null;
  cpu_percent: number | null;
  created: string | null;
}

export interface ProcessesResult {
  action: "processes";
  process_count: number;
  returned_count: number;
  truncated: boolean;
  processes: ProcessEntry[];
  collected_at: string;
  status: string;
  message: string;
}

export interface FileEntry {
  name: string;
  path: string;
  type: "file" | "directory";
  size_bytes: number;
  modified: string;
  indicators: Indicator[];
}

export interface ListResult {
  action: "list";
  target: string;
  entry_count: number;
  returned_count: number;
  truncated: boolean;
  entries: FileEntry[];
  status: string;
  message: string;
}

export interface SearchMatch {
  name: string;
  path: string;
  size_bytes: number;
  modified: string;
  indicators: Indicator[];
}

export interface SearchResult {
  action: "search";
  search_target: string;
  search_directory: string;
  match_count: number;
  entries_scanned: number;
  truncated: boolean;
  results: SearchMatch[];
  status: string;
  message: string;
}

export type AnalysisResult =
  HashResult | EncryptResult | SystemInfoResult | ProcessesResult | ListResult | SearchResult;

export interface Report {
  report_id: string;
  timestamp: string;
  command: string;
  action: string | null;
  target: string | null;
  status: "completed" | "failed" | string;
  execution_time_ms: number | null;
  result: AnalysisResult | Record<string, never>;
  warnings: string[];
  errors: string[];
}

export interface CommandResponse {
  status: "success" | "error";
  command?: string;
  result?: AnalysisResult;
  report?: Report;
  error?: string | null;
}

export interface CommandReferenceEntry {
  name: string;
  syntax: string;
  example: string;
  description: string;
  category: string;
}

// --- Frontend-only domain types (investigations, history) -----------------
// These are populated from real executed commands/reports, persisted client-side.

export interface HistoryEntry {
  id: string;
  command: string;
  status: "success" | "error";
  timestamp: string;
  executionTimeMs: number | null;
  reportId: string | null;
}

export interface Investigation {
  id: string;
  title: string;
  createdAt: string;
  analystNotes: string;
  commandIds: string[];
  reportIds: string[];
}
