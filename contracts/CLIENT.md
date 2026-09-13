# JOCKY local client contract (API v1)

The Flutter client starts one bundled backend process per workspace. The backend
owns parsing, evidence semantics, collection, SQLite, and reports. No network
account, Node, browser server or external Python is needed in a release bundle.

## Bootstrap and authentication

Start `backend/jocky-backend` (Linux) or `backend/JOCKY-backend.exe` (Windows),
optionally with `--workspace <absolute directory>`. Keep stdin open. Read stdout
as **UTF-8 newline-delimited JSON**, not diagnostic text. stderr is diagnostics;
rotating logs are under the workspace state directory. Never log stdout frames.

Frames have `protocol: 1`, `event`, and `instance_id`. Events:

* `started`: process launched, initialization incomplete; includes `versions`.
* `ready`: includes `host: "127.0.0.1"`, OS-assigned `port`, `token`, `versions`,
  and `storage_mode`. This is a private inherited pipe, not a published file.
* `startup_error`: structured `error` with code/type/message; exit nonzero.
* `stopping`, `stopped`: graceful shutdown acknowledgements.

The parent authenticates the expected child through its inherited pipe and
keeps the random launch credential in memory. Every HTTP request, including
health, needs `Authorization: Bearer <token>` and
`X-Jocky-Instance: <instance_id>`. Missing/wrong credentials or instance: 401.
Browser Origin headers are rejected; no CORS access is enabled. Loopback only.
This protects against unrelated localhost clients, not a compromised same-user
process with debugger access. Protect the workspace using OS account permissions.

Never adopt an arbitrary process simply because port 5000 responds. The port is
chosen by the OS. Wait for ready, then verify GET `/api/v1/health` before enabling
commands. `ready=false` means stopping or a storage failure. Credentials are
rotated on restart. API v1/schema v1 command compatibility must be checked.

Shutdown: POST `/api/v1/shutdown` with authentication returns 202 `state: stopping`.
Alternatively write `{"event":"shutdown","instance_id":"..."}` to child stdin.
EOF on stdin also shuts down after parent exit/crash. Wait for exit; force-kill
only after a bounded grace interval. Unfinished work is interrupted on restart.
A second backend cannot own the same workspace; file locking is required.

## Endpoints

All paths below start `/api/v1` except the compatibility aliases noted.
JSON request bodies must be objects; maximum request body is 1 MiB.
Responses below retain null/unavailable values rather than substituting zero.

* GET `/health`, `/status`: `status`, `engine`, `ready`, `instance_id`, `versions`,
  `storage: {mode,path,free_bytes,error}`. `/health` is also a compatibility alias.
* GET `/capabilities`: published collection/export limits, historical telemetry
  availability, cancellation boundary, versions.
* GET `/commands`: backend command catalog, `schema_version:1`. Alias `/commands`.
* POST `/command`: `{command, investigation_id?}`. Alias **POST `/command`**.
  Synchronous compatibility response contains `status`, `execution_id`,
  `normalized_command`, `result`, `report`, `error`, `error_code`, `error_kind`.
  Failures have durable execution/report records. Client timeout is not cancellation.
* GET `/investigations?search=<text>&status=<state>`: `{items,limit:1000}`;
  newest first; search title/device/ID. At most 1000 visible results, records retained.
* POST `/investigations`: `{title?,examiner?,reference?,notes?}` returns 201 investigation.
* GET `/investigations/{id}`: durable investigation (see model below).
* POST `/investigations/{id}/collect`: `{paths:[]}` returns 202 investigation.
  Up to 20 explicitly selected absolute file/directory paths. A case can collect
  once; duplicate collection returns 409. Create a new case for another snapshot.
* POST `/investigations/{id}/cancel`: `{}` returns 202 cancellation_requested.
  Cancellation is cooperative between bounded steps/process reads. Already
  committed observations remain. No evidence or target process is terminated.
* GET `/investigations/{id}/timeline`, `/evidence`, `/findings`, `/executions`,
  `/reports`: `{items:[...]}`. Reports contain immutable `payload` snapshots.
* POST `/investigations/{id}/report/export`: `{format:"pdf"|"json"}` returns
  binary PDF or JSON attachment from the latest stored report. No recollection.
* GET `/reports/{report_id}`: stored report payload; command schema1 or collection schema2.
* GET `/history`: `{items,limit:1000}` durable execution records, newest first.
* GET `/workstation`: compatibility projection for original Flutter case/history widgets.
* POST `/workstation`: `{investigations,active_case_id}` accepts editable case
  title/notes/examiner/reference/attached-source metadata only. It cannot delete
  investigations or overwrite executions/reports. Attached sources are declared
  references, not collected evidence; collection produces separate evidence rows.
* POST `/storage/backup`: `{}` creates a verified SQLite backup, returns `{path}`.
* POST `/storage/import-ledger`: `{path}` verifies and backs up former JSON hash ledger,
  atomically imports observations. Identical import is idempotent. Source preserved.
* POST `/storage/import-workstation`: `{path}` explicitly imports former Flutter
  workstation_records.json (store_version1), preserving original report payloads,
  with verified original backup and legacy-client provenance. Conflicts fail atomically.
* POST `/evidence/export-encrypted`: `{path,destination,passphrase}` creates a new
  authenticated copy, returns artifact/metadata. Never overwrites source or destination.
* POST `/shutdown`: `{}` returns 202 acknowledgement.

Non-command error envelope: `{error:{code,message},api_version:1}`. Codes include
`validation_error` (400), `authentication_error` (401/403), `not_found` (404),
`conflict` (409), `unavailable` (503), `storage_unavailable` (503),
`request_error` (HTTP routing/body errors), `internal_error` (500).
The legacy command error fields remain v1-compatible. Never treat a caught
exception, null result or failed evidence row as success.

## Domain and report models

Investigation: `id,title,created_at,started_at?,completed_at?,status,device,
metadata,evidence_count,finding_count`. Metadata holds examiner, reference,
notes and investigator workstation context. Device holds collected host facts
and collection timestamp; optional values can be absent or null.

Collection states: `created -> collecting -> analyzing -> finalizing ->
completed | partially_completed | failed | cancelled`. Queued collection uses
`collecting` plus a persisted queued timeline entry. After abnormal termination,
unfinished collections become `interrupted`. A created case remains created.
No fabricated percentages. Partial completion means some bounded sources failed,
were skipped or truncated; warnings and unavailable fields remain in payloads.
A completed snapshot is not a claim of whole-device coverage.

Execution: `id,investigation_id?,command,normalized_command?,state,created_at,
started_at?,completed_at?,result?,error?,versions`. States: running/completed/
failed/cancelled/interrupted (queued reserved in storage). Collection actions
SYSTEM INFO, PROCESSES and FILES are workflow actions, not a language redesign.

Evidence: `id,investigation_id,execution_id,type,source,collected_at,status,payload`.
Hashes and filesystem timestamps appear inside file payloads. Large source files
are never copied into SQLite. Collected metadata/results are bounded JSON.
Finding: `id,investigation_id,evidence_id,category,severity,title,explanation,
classification:INFERRED`. Filename heuristics warrant review, not a malware verdict.

Report schema2: `report_id,investigation_id,schema_version:2,created_at,status,
investigation,device,versions,summary,evidence,executions,findings,timeline,
limitations,provenance`. Report contents are immutable after creation. API v1
may return command report schema1 and investigation report schema2. Clients must
preserve unknown fields and reject unsupported future major versions gracefully.
See `api.json`, `report.schema.json`, and `fixtures/` for machine-readable examples.

## Storage and portable behavior

Installed Windows uses `%LOCALAPPDATA%/JOCKY`; Linux uses
`$XDG_DATA_HOME/jocky`, `$XDG_STATE_HOME/jocky`, `$XDG_CONFIG_HOME/jocky` with
standard `~/.local/share`, `~/.local/state`, `~/.config` defaults. Installed
resources are read-only. Portable mode is explicitly selected in Settings
(restart required), via `JOCKY_WORKSPACE` in the launcher, or backend `--workspace`.
Portable storage contains `workstation.sqlite3`, `artifacts/`, `backups/`,
`state/logs/`, `config/`. UI preferences remain in system application support;
the launcher workspace override avoids relying on another host's preferences.

SQLite uses WAL, FULL synchronization, foreign keys, busy timeout, transactions,
startup quick_check and versioned migrations. Locking/safe writes must be
supported by the filesystem; do not use network shares. Do not eject a workspace
while JOCKY runs. Back up via the API, not by copying a live .sqlite3 without its
WAL. Disk-full errors do not cause automatic reset/deletion. Committed records
remain; a terminal failure that cannot be written is surfaced in readiness and
marked interrupted at restart. Corruption fails startup; original files remain.
Restore a verified backup manually while the backend is stopped, preserving the
damaged database/WAL for recovery. There is no destructive automatic repair.

## Evidence export and recovery

ENCRYPT FILE keeps parser contract v1 but now fails safely without explicit export
options; the destructive fixed-key operation has been removed. Use export API.
AES-256-GCM streams in 1 MiB chunks. A fresh random 16-byte salt and 12-byte nonce
are generated per artifact. Scrypt N=32768,r=8,p=1 derives the key from a supplied
UTF-8 passphrase. The authenticated envelope holds source name/size/mtime,
algorithm/KDF/version/salt/nonce; final 16 bytes are GCM tag. No recovery secret
is written to logs, source or database. The operator must retain the passphrase
separately. `crypto.crypto.decrypt_file(artifact, new_destination,
passphrase=...)` verifies authentication before publishing plaintext. Legacy
fixed-key CBC artifacts are not accepted by this recovery path.

Historical script execution remains UNAVAILABLE: there is no historical OS log
collector in this release. Current processes include available executable path,
parent PID, process start time and interpreter classification. Arguments are
skipped because they can contain credentials. Files are only explicitly selected
sources; directory listing is bounded and nonrecursive. HASH includes existing
filename indicators and structural integrity checks; SEARCH remains available in
the Command Center. No native agent, stealth monitor or security bypass is needed.

PDF export bundles Noto Sans, Devanagari and Bengali fonts, with offline shaping.
Other unsupported glyphs are displayed as explicit Unicode codepoint labels and
listed in a font-coverage note; exact original strings remain in JSON.
