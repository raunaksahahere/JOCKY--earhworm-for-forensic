import { formatBytes } from "@/lib/format";
import type { Indicator, Report } from "@/lib/types";

export interface ReportNarrative {
  summary: string;
  evidence: { label: string; value: string }[];
  findings: string[];
  indicators: Indicator[];
  verification: string;
}

export function buildReportNarrative(report: Report): ReportNarrative {
  const result = report.result as Record<string, unknown> | undefined;

  if (report.status === "failed" || !result || !("action" in result)) {
    return {
      summary: `The command "${report.command}" did not complete successfully. See warnings below for details.`,
      evidence: [],
      findings: [],
      indicators: [],
      verification: "Not applicable",
    };
  }

  switch (result["action"]) {
    case "hash": {
      const r = result as {
        filename: string;
        algorithm: string;
        hash: string;
        size_bytes: number;
        indicators: Indicator[];
        integrity_check: { file_type: string; status: string; message: string };
        integrity_history: { status: string; message: string };
        previous_hash: { algorithm: string; hash: string; timestamp: string } | null;
      };
      const findings: string[] = [
        `Integrity check (${r.integrity_check.file_type}): ${r.integrity_check.message}`,
        `Change since last hash: ${r.integrity_history.message}`,
      ];
      if (r.indicators.length > 0) {
        findings.push(...r.indicators.map((i) => `${i.label}: ${i.detail}`));
      } else {
        findings.push("No static filename indicators were flagged for this file.");
      }
      return {
        summary: `A ${r.algorithm} digest was computed for "${r.filename}" (${formatBytes(
          r.size_bytes,
        )}). ${r.integrity_check.message} ${r.integrity_history.message}`,
        evidence: [
          { label: "File", value: r.filename },
          { label: "Size", value: formatBytes(r.size_bytes) },
          { label: `${r.algorithm} Hash`, value: r.hash },
          ...(r.previous_hash
            ? [{ label: `Previous ${r.previous_hash.algorithm} Hash`, value: r.previous_hash.hash }]
            : []),
        ],
        findings,
        indicators: r.indicators,
        verification:
          r.integrity_history.status === "altered"
            ? `WARNING: ${r.integrity_history.message} Re-verify this file's provenance before relying on it as evidence.`
            : `${r.integrity_history.message} Re-run this command at any time to re-verify.`,
      };
    }
    case "system_info": {
      const r = result as {
        hostname: string;
        os: string;
        os_release: string;
        architecture: string;
      };
      return {
        summary: `Read-only host system information was collected from "${r.hostname}" (${r.os} ${r.os_release}, ${r.architecture}) for investigative context.`,
        evidence: [{ label: "Host", value: r.hostname }],
        findings: [
          "System information collection is observational and made no configuration changes.",
        ],
        indicators: [],
        verification: "Not applicable",
      };
    }
    case "processes": {
      const r = result as { process_count: number; returned_count: number };
      return {
        summary: `${r.process_count} running processes were observed; the top ${r.returned_count} by memory usage are recorded below for analyst review.`,
        evidence: [{ label: "Processes Observed", value: String(r.process_count) }],
        findings: [
          "Process observation is read-only; no process was started, stopped, or modified.",
        ],
        indicators: [],
        verification: "Not applicable",
      };
    }
    case "list": {
      const r = result as {
        target: string;
        entry_count: number;
        entries: { indicators: Indicator[] }[];
      };
      const flagged = r.entries.flatMap((e) => e.indicators);
      return {
        summary: `${r.entry_count} filesystem entries were catalogued under "${r.target}".`,
        evidence: [
          { label: "Directory", value: r.target },
          { label: "Entries", value: String(r.entry_count) },
        ],
        findings:
          flagged.length > 0
            ? flagged.map((i) => `${i.label}: ${i.detail}`)
            : ["No static indicators were flagged among listed entries."],
        indicators: flagged,
        verification: "Not applicable",
      };
    }
    case "search": {
      const r = result as {
        search_target: string;
        search_directory: string;
        match_count: number;
        results: { indicators: Indicator[] }[];
      };
      const flagged = r.results.flatMap((m) => m.indicators);
      return {
        summary: `A search for "${r.search_target}" under "${r.search_directory}" returned ${r.match_count} match(es).`,
        evidence: [
          { label: "Search Term", value: r.search_target },
          { label: "Directory", value: r.search_directory },
          { label: "Matches", value: String(r.match_count) },
        ],
        findings:
          flagged.length > 0
            ? flagged.map((i) => `${i.label}: ${i.detail}`)
            : ["No static indicators were flagged among matched files."],
        indicators: flagged,
        verification: "Not applicable",
      };
    }
    case "encrypt":
    case "decrypt": {
      const r = result as { path: string; message: string };
      return {
        summary: r.message,
        evidence: [{ label: "Target", value: r.path }],
        findings: ["Evidence file was processed for at-rest protection."],
        indicators: [],
        verification: "Not applicable",
      };
    }
    default:
      return {
        summary: `Command "${report.command}" completed.`,
        evidence: [],
        findings: [],
        indicators: [],
        verification: "Not applicable",
      };
  }
}
