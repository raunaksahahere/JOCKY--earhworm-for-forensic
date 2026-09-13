# JOCKY — Product Requirements Document

## 1. Problem

Digital forensic investigators and student security teams need a way to run
repeatable, well-documented analysis steps against evidence — computing
hashes, inspecting a host, listing and searching directories, observing
processes — and to walk away with a defensible, structured report of what was
done, when, and with what result. Ad hoc shell commands and screenshots don't
produce an auditable trail. JOCKY exists to close that gap with a small,
purpose-built command language and an investigation console built around it.

## 2. Users

- **Student / competition forensic teams** (this project's original SIH
  context) who need to demonstrate a credible investigation workflow.
- **Analysts learning digital forensics fundamentals** who want a safe,
  observable environment to practice integrity verification, triage, and
  reporting.
- **Instructors/judges** evaluating whether the tool behaves professionally,
  safely, and produces trustworthy output.

## 3. Goals

- Provide a small, unambiguous command language (JOCKY) for common forensic
  triage actions.
- Execute those commands against a real backend and return real,
  structured results — never mocked data where the engine can produce
  real data.
- Turn every executed command into a timestamped, reproducible **report**
  suitable for an investigation record.
- Present all of this through an interface that reads as a serious,
  professional forensic tool rather than a generic CRUD dashboard.
- Stay strictly defensive: every capability is read-only observation or
  evidence-handling (hashing, at-rest encryption). Nothing offensive,
  evasive, or system-altering is implemented.

## 4. Non-goals

- JOCKY is **not** an EDR, antivirus, or endpoint-protection product, and
  does not attempt to disable, bypass, or interfere with any such product.
- JOCKY does **not** implement malware, exploits, persistence, privilege
  escalation, credential theft, process injection, or any other offensive or
  evasive technique — including for "detection" or "simulation" purposes.
  Where the original SIH problem statement describes such techniques, that
  language is treated strictly as **threat-modeling context** (i.e.,
  "here is what a real attacker might do, which is why forensic tooling
  needs to detect its traces") — not as a specification to implement.
- JOCKY does not claim to make malware verdicts. Its "indicators" are static,
  string-based, informational heuristics (e.g., extension mismatches) for a
  human analyst to weigh — never an automated detection or removal system.
- Multi-user auth, role-based access control, and cloud sync are out of
  scope for this version; investigations/reports/history persist locally
  in the analyst's browser.

## 5. Functional requirements

| # | Requirement | Status |
| - | --- | --- |
| F1 | Parse and execute `HASH FILE <path>` and return algorithm, digest, size, timestamps | Implemented |
| F1a | Run a structural integrity pre-check (corruption detection) before/alongside hashing | Implemented |
| F1b | Compare each hash against JOCKY's local ledger and report whether the file changed since it was last hashed | Implemented |
| F2 | Parse and execute `ENCRYPT FILE <path>` for evidence-at-rest protection | Implemented |
| F3 | Parse and execute `SYSTEM INFO` (OS, CPU, memory, uptime, hostname) | Implemented |
| F4 | Parse and execute `PROCESSES` (read-only process table) | Implemented |
| F5 | Parse and execute `LIST FILES <path>` | Implemented |
| F6 | Parse and execute `SEARCH FILE <name> IN <path>` | Implemented |
| F7 | Every execution (success or failure) produces a structured `Report` with a unique ID and timestamp | Implemented |
| F8 | Frontend renders structured results per action type, not raw JSON | Implemented |
| F9 | Frontend maintains a session command history and a report archive | Implemented (client-side, localStorage) |
| F10 | Frontend groups commands/reports into investigations with analyst notes and a timeline | Implemented |
| F11 | Reports are viewable as an A4-style printable document and exportable via the browser's Print/Save-as-PDF | Implemented |
| F12 | Live API/engine health is surfaced in the UI at all times | Implemented |
| F13 | Command reference is served by the backend (`GET /commands`) so the UI cannot drift from the grammar | Implemented |

## 6. UI requirements

- Dark graphite/void visual identity with a restrained cyan/electric-blue
  accent; green/amber/red reserved strictly for success/warning/critical
  state — never decorative.
- IBM Plex Sans for interface text, IBM Plex Mono for anything that is
  machine-produced evidence (hashes, paths, timestamps, PIDs, syntax).
- Eight sections: Overview, Command Center, Investigation Workspace,
  Reports, History, Tools, System Status, Settings — reachable from a
  persistent sidebar (collapses to a sheet drawer on mobile) and a top bar
  showing live connection status.
- The Command Center is the visual and functional centerpiece: command
  editor, syntax hints drawn from the live command reference, Ctrl+Enter to
  execute, and loading/success/error states that render structured result
  cards (never a raw JSON dump as the primary view).
- Every list/table view (Reports, History, Processes, Search, List Files)
  has a designed empty state — no blank pages.
- Responsive from mobile through desktop; the sidebar becomes a drawer,
  data tables scroll horizontally within a bounded card rather than
  breaking layout.

## 7. Architecture

See `README.md` → Architecture for the full diagram. In short: React/Vite
(TanStack Start) frontend → Flask API → JOCKY compiler/parser (Lark grammar)
→ dispatcher → analysis modules → structured report, with the frontend
consuming `/health`, `/commands`, and `/command` only.

## 8. Forensic workflow

1. Analyst opens an **Investigation** (or uses the default one) in the
   Investigation Workspace.
2. Analyst runs commands from the **Command Center** (or the Overview
   launcher, or a **Tools** card, which pre-fills a command).
3. Each execution is sent to the real Flask API, parsed by the JOCKY
   grammar, dispatched to the matching analysis module, and returned as a
   structured result plus a full report.
4. The result renders as a purpose-built forensic card (hash digest table,
   system info panel, process table, file listing, search results) with any
   static indicators called out.
5. The command and its report are attached to the active investigation's
   timeline automatically.

## 9. Reporting workflow

1. Every completed (or failed) command produces a `Report`: `report_id`,
   `timestamp`, `command`, `action`, `target`, `status`,
   `execution_time_ms`, `result`, `warnings`, `errors`.
2. Reports accumulate in the **Reports** archive (sortable table: ID,
   investigation, command, action, target, status, date, runtime).
3. Opening a report renders it as an **A4-style document** — header,
   report metadata, executive summary (derived from the structured result),
   evidence, findings, verification state, and warnings/errors — styled to
   look correct both on screen and when printed or saved as PDF via the
   browser's print dialog.

## 10. Future roadmap

- Serve a static production frontend build directly from Flask (instead of
  shelling out to the Vite dev server) so the desktop build in `desktop/`
  no longer requires Node.js on the end-user's machine — turning the
  PyInstaller executable into a truly standalone `.exe`.
- Server-side persistence for reports/investigations (currently
  browser-local) so a case can be resumed from another device.
- Optional file upload for hashing/analysis instead of server-local paths
  only, for browser-based evidence submission.
- Expanded static indicator set (e.g., MIME/magic-byte mismatch detection,
  still read-only and non-executing).
- Role-based access if JOCKY is ever deployed for a multi-analyst team.
- Network interface metadata in System Status (currently a stated gap; see
  `analysis/system.py`).

## 11. Security / safety boundaries

- **What JOCKY implements:** file hashing (SHA-256/SHA-1/MD5/SHA-512),
  at-rest file encryption for evidence handling, read-only system
  information collection, read-only process observation, directory listing,
  recursive filename search, and static/string-based filename indicators.
  All of the above are read-only with respect to the target system, aside
  from the explicit, analyst-invoked `ENCRYPT` action on a specific file the
  analyst names.
- **What JOCKY explicitly does not implement, under any framing:**
  malware or exploit code, antivirus/EDR bypass or disabling, privilege
  escalation, persistence mechanisms, credential theft, process injection,
  vulnerable-driver exploitation, stealth/evasive execution, domain
  fronting, or any other offensive or evasive technique.
- **How the original SIH threat-landscape language is treated:** where the
  original problem statement describes attacker techniques, that text
  describes the *threat model* JOCKY is meant to help investigate — it is
  research/context, not a feature list. No offensive capability was built
  from it, and none should be added later without re-scoping this document.
- **Indicators are advisory, not verdicts:** JOCKY's static indicators
  (e.g., "notable extension", "possible double-extension spoofing") are
  informational labels for a human analyst. They never trigger automated
  action against a file or process.
