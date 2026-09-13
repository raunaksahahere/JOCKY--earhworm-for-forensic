# Changelog

All notable changes to JOCKY. Versions follow semantic versioning.

## 0.6.1 — 2026-09-14

A 24-hour collection produced a 60-page report. The evidence was right;
presenting all of it as though the investigator had to read it was not.

### Added

- **Investigation threads.** Related activity now reads as one story instead of
  as separate records: a tool installed, an environment made for it, the tool
  run three times. Grouping is conservative — two activities link only when they
  share a distinctive term *and* sit near each other in the record, or when one
  installs what the other runs. Common words never link anything, flags are
  excluded (`-fsSL` is not a tool), threads are capped so one shared word cannot
  chain half the history together, and a thread states that records *appear
  related* and never what anyone intended by them.
- **Top investigative leads, deduplicated by pattern.** Five vendor install
  commands are one lead about one behaviour, not five investigations. Every
  command and every evidence identifier stays inside the lead.
- **Significant events**: a short timeline of what actually helps explain the
  investigation, instead of every record. Bounded, and it says so.
- **A written conclusion** on page one that interprets the numbers rather than
  repeating them, and never reaches for a reassuring phrase the evidence does
  not support.
- `Appendix B: full command history` — every command-history record, in full,
  with its evidence identifier.

### Changed

- **The main report is 8 pages instead of 60.** It runs: overview and
  conclusion, investigation result, top leads, threads, significant events,
  routine activity, uncertain activity, collection limitations, evidence
  package. The detail moved into nine appendices. Length is now driven by how
  much there is to investigate, not by how many records were collected.
- The investigator view opens on the same hierarchy: conclusion, leads, threads,
  significant events, then the full evidence list.
- Thread building uses an inverted index over rare terms rather than comparing
  every activity with every other, which took collection from stalling to 10 ms.

### Unchanged, deliberately

Every raw record, command string and evidence identifier remains in SQLite and
the JSON export; the appendices carry what the body summarises. Shell history is
still not execution, a process snapshot is still a current observation, missing
telemetry is still a limitation, and triage is still not a verdict.

## 0.6.0 — 2026-09-13

Signal-to-noise. The report was honest but hard to act on: 820 records sat in
"needs review", most of them ordinary system daemons whose only problem was that
the journal does not record their arguments.

### Added

- **Investigator priority**, separate from classification. Classification says
  what the evidence supports; priority says where attention is worth spending.
  The two are allowed to disagree, which is the whole point: an ordinary system
  service can be honestly uncertain and still not be worth an investigator's
  morning.
  - **Priority 1 — investigate first**: several independent signals combine.
  - **Priority 2 — review**: a concrete reason, with incomplete or
    uncorroborated evidence.
  - **Priority 3 — informational**: routine system and session activity, and
    records whose only gap is a missing command line.
- **Top investigative leads** opens the report: lead id, priority,
  classification, the full command, whether execution was established, the
  named reasons it is ranked there, what remains unknown, a conservative
  suggested next step, and the evidence ids behind it.
- An explainable priority score. Every record carries the named signals that
  produced it — `remote_content_to_interpreter`, `execution_from_writable_location`,
  `corroborated_across_sources`, `system_location`, `installer_shaped_source` —
  with their weights. The report shows the reasons, never a bare number.
- "What is uncertain, and why": the uncertain records grouped by reason, so
  "527 need review" reads as "506 are commands entered in a shell with no
  execution record, and 21 are confirmed executions whose arguments the source
  never captured".
- The application icon, installed at every hicolor size in the Debian package,
  compiled into the Windows runner, and shown in the sidebar.

### Changed

- **Missing command-line arguments are a collection limitation, not a
  suspicion.** They are recorded on the record, shown in the report, and
  contribute nothing to priority. This alone moved several hundred ordinary
  system processes out of the review queue.
- Routine system context is recognised structurally rather than by an
  allowlist: an image in a directory the OS packaging owns, run as a managed
  systemd unit, with no concern signal. `/usr/local` and `/opt` are deliberately
  excluded, because locally installed software is exactly what stays visible.
  An interpreter is never automatically routine — what `python3` ran is the
  question, and the record usually cannot answer it.
- Fetch-and-run commands whose URL is shaped like a vendor install script are
  ranked review rather than investigate-first. The pattern is still reported in
  full, the classification is unchanged, and any corroborating signal lifts it
  straight back up.
- Corroboration raises priority: the same executable named by two independent
  sources, or matched to an artifact on disk, outranks a single weak
  observation.
- The main report now runs executive summary, priority summary, top leads,
  findings, then priority 1, 2 and 3, then what is uncertain and why. Routine
  activity is summarised with a count and examples instead of listed.
- The investigator view opens on priority 1 and 2. "All evidence" is one click
  away, and nothing is hidden: the appendices and the database hold every record.
- Schema 4 stores the priority and its score alongside the classification, so
  the deterministic machine judgement is preserved separately and is never
  overwritten.

### Unchanged, deliberately

Shell history is still not execution. A process snapshot is still a current
observation. Missing telemetry is still not evidence of innocence. A filename is
still not malware. "Not harmful based on available evidence" still means nothing
in what was collected stood out, not that the activity was safe. Every raw
record, evidence id and command string remains in SQLite and the JSON export.

## 0.5.1 — 2026-09-13

### Changed

- **Clear history now clears the whole list.** It previously kept every
  execution belonging to an investigation, so on a workstation whose history was
  all collection steps the button appeared to do nothing at all. It now deletes
  every row the History screen shows — commands submitted directly and the
  collection steps investigations ran — along with the reports issued for them.

  The evidence is not touched. Observations, findings, artifacts, execution
  events, the merged timeline and each investigation's own report all survive;
  their link to the deleted execution is cleared rather than the rows being
  removed, so an investigation still holds what was observed and its report
  still exports. The hash ledger survives for the same reason: it spans
  investigations and is what tells an investigator whether a file changed
  between sightings.

  What is lost is the job log — when each step ran, its state, and which
  evidence row came from which step. The dialog says so, the result reports how
  many evidence records were kept, and the clearance is recorded in the
  workspace.

## 0.5.0 — 2026-09-13

Investigator usability. The evidence was already being collected correctly; it
was being presented in a way that hid the most useful part of it.

### Fixed

- **Reports showed `git`, `python3`, `wget` where the source had recorded the
  whole command.** Shell history stores the command verbatim, and it was in the
  database all along — the report and the timeline rendered `process_name` and
  dropped `command_line`. The full command is now what an investigator sees:
  `curl -fsSL https://example.com/install.sh | sudo bash`, quoting, pipes,
  redirections and all.
- **Shell history was labelled EXECUTION_EVENT.** A typed command is not proof
  that anything ran. Records now carry an evidence kind — EXECUTION_EVIDENCE,
  COMMAND_HISTORY, SESSION_EVENT — and command history is never promoted to
  execution evidence however complete its text is.
- **"1721 historical execution records"** blurred three different kinds of
  evidence into one number. Counts are now named for what they are:
  execution-source records, command-history records and session records.

### Added

- Command reconstruction on every record: `full_command_line`,
  `command_source`, `command_reconstruction_status` (EXACT, PARTIAL,
  EXECUTABLE_ONLY, NOT_AVAILABLE) and `command_evidence_strength` (STRONG,
  MODERATE, WEAK). When a source recorded only an image name, the report says
  "not available from collected evidence" rather than inventing arguments. A
  separate normalized form exists for searching and never replaces the raw
  command.
- Three-way triage (`analysis/triage.py`): POTENTIALLY HARMFUL, NOT HARMFUL ON
  AVAILABLE EVIDENCE, NOT SURE / NEEDS REVIEW — with a one-line reason for each.
  These are triage categories, not verdicts, and "not harmful" is worded as
  "nothing in the collected evidence stood out", never as proven safe. No single
  keyword classifies anything: `curl`, `python3`, `sudo`, `nc` and `ssh` on
  their own land in NEEDS_REVIEW. Concern requires a combination, such as a
  remote fetch piped into an interpreter or an image running from a writable
  temporary directory.
- Activity grouping (`analysis/activity.py`): repeated identical commands are
  shown once with an occurrence count, while every individual record keeps its
  timestamp, source and evidence identifier. Commands that differ — two `wget`
  calls to different URLs — never merge.
- Stable evidence identifiers: EXEC-0001, CMD-0001, SESS-0001, ART-0001,
  F-0001. Findings cite them, the PDF prints them, and the database stores them.
- Command search over the whole record — command text, URLs, paths, users,
  sources, evidence identifiers — not the executable alone. Searching
  "github.com" or "holehe" finds the records that contain them.
- Schema 3: evidence kind, full command line, normalized command,
  reconstruction status, evidence strength, execution-confirmed flag and
  reference on execution events; triage, reason and reference on findings; and
  a `collection_limitations` table.

### Changed

- **The main report is 11 pages instead of 42.** It opens with collection
  coverage and a triage table, leads with activity that needs attention, then
  separates confirmed execution evidence from user-entered command history from
  session activity. Detail moved into eight appendices. No evidence was
  deleted: SQLite and the JSON export are unchanged, and the appendices carry
  the records the body summarises.
- Findings and collection limitations are separate. A telemetry source that was
  switched off is a limit on the investigation, not a harmful-activity finding,
  and it no longer pads the finding list.
- The findings section leads with what needs attention; corroboration and
  routine observations are counted and listed in Appendix C.
- The investigation workspace gained an activity view with triage filtering,
  search, the full command per record, and raw evidence behind a details
  toggle.

### Not verified in this release

Windows telemetry parsing remains fixture-tested only; no Windows collector has
been run against a real Windows host.

## 0.4.1 — 2026-09-13

### Fixed

- **"Clear history" did nothing.** The button committed a record with an empty
  execution list, but `ApiRecordStore.save` sends case metadata only — the
  engine owns the execution record and deliberately ignores client-supplied
  execution data — so nothing was deleted, and the refresh that followed
  reloaded every execution from SQLite. The list blanked for an instant and
  refilled.

  Clearing is now a request to the engine, which performs the deletion and
  reports what it did. `RecordStore` gained an explicit `clearExecutionHistory`
  because "save a record without executions" cannot express deletion against an
  authoritative engine; the file-backed and in-memory stores clear their own
  data directly.

- The confirmation dialog claimed "the engine keeps no copy, so they cannot be
  recovered". The engine kept every copy and was authoritative. It now states
  what is actually removed and what is kept.

### Added

- `POST /api/v1/history/clear` removes Command Center history — executions
  belonging to no investigation, and the reports issued for them. Executions
  that belong to an investigation, and any execution referenced by collected
  evidence, are forensic records and are retained unconditionally: a
  convenience button must not be able to delete evidence. Hash observations
  survive with their execution link cleared, so the integrity ledger keeps
  answering whether a file changed between sightings.
- The clearance is recorded in the workspace. Unrecorded destruction has no
  place in a forensic workstation.
- The result is shown to the operator, so "nothing was deleted because it is
  all evidence" reads as a result rather than another silent no-op.

## 0.4.0 — 2026-09-13

Historical execution evidence. An investigation can now answer "what execution
activity and related artifacts can the evidence on this device support?" rather
than only "what is running right now?".

### Added

- **Historical execution collection**, behind one interface with per-platform
  implementations (`analysis/execution_history.py`). Linux reads the systemd
  journal, shell history, the kernel audit log, BSD process accounting and wtmp
  login records. Windows reads Security 4688, Sysmon event 1, the PowerShell
  operational log, Prefetch file metadata and UserAssist. Every source is
  read-only and already present: JOCKY never enables auditing, installs a
  sensor, or changes a security setting. A source that is off is reported
  NOT_ENABLED, not switched on.
- **A normalized execution event** (`analysis/execution_model.py`) carrying
  timestamp, process name, executable, parent, PIDs, user, interpreter, source,
  source record id, hash and raw source metadata — with per-field provenance
  (OBSERVED, DERIVED, UNAVAILABLE) and, on every event, a plain statement of
  what its source actually proves. A journal record says the image was running
  when it logged, not when it started. A shell history line says a command was
  typed, not that it ran.
- **A bounded collection window**, defaulting to 7 days and capped at 90. There
  is no unbounded mode. The window is shown in the UI and the report.
- **Artifact collection** (`analysis/artifacts.py`) driven by evidence:
  investigator-selected paths plus executables named by execution records. One
  directory level, never recursive, bounded at 200 artifacts and 128 MiB per
  digest. A file the evidence names but which is absent is recorded as MISSING
  rather than omitted.
- **Correlation and findings** (`analysis/correlation.py`): missing executable,
  execution from a writable or temporary location, artifact corroborating an
  execution record, hash changed since the last observation, structural
  integrity anomaly, suspicious filename, unavailable telemetry, permission
  gaps and truncated collection. Every finding carries severity, confidence,
  classification and the evidence it rests on. None of them call anything
  malware.
- **A merged timeline** (`analysis/timeline.py`) over execution events, file
  metadata, current process observations, findings and investigation state,
  ordered by the timestamp each source recorded. Records whose source has no
  timestamp are listed separately rather than placed at an invented time.
- Schema 2: `execution_events`, `artifact_observations`, `timeline_events` and
  `finding_evidence`, plus `confidence` and `detail` on findings. Existing
  databases migrate in place; only metadata and digests are stored, never file
  contents.
- Report schema 3 with collection window, historical execution, timeline,
  artifacts, hashes, indicators, integrity, findings, evidence references,
  limitations, unavailable telemetry, provenance and versions.
- Deterministic telemetry fixtures (`tests/fixtures/telemetry.py`) covering
  known events, a missing executable, a matching artifact, permission denied,
  unavailable telemetry, truncation, duplicates, malformed records and
  timestamp ordering.

### Changed

- The current process snapshot is no longer capped at 256. The bound is
  configurable (default 4096), truncation is deterministic — processes are
  sorted by identifier, and the omitted range is stated — and the result
  carries collection statistics with permission failures preserved.
- Command-line arguments remain off by default and are now opt-in per
  investigation. When enabled, values matching common credential patterns are
  masked before storage. That is a mitigation, not a guarantee, and the report
  says so.
- The raw per-process listing moved out of the report body into a clearly
  labelled appendix. Nothing was dropped.
- `/api/v1/capabilities` reports the platform's telemetry sources and the
  collection bounds instead of a hardcoded `historical_execution_telemetry:
  false`.
- The investigation workspace shows a collection summary — telemetry available
  or not, the window, and counts of events, artifacts, findings and limitations
  — read from the engine's report rather than recomputed in the client.

### Forensic honesty

Unchanged and extended: JOCKY still distinguishes CURRENT OBSERVATION from
HISTORICAL EVIDENCE, INFERRED from OBSERVED, and marks what is UNAVAILABLE. It
does not claim a program executed unless a source that records execution says
so, does not fabricate timestamps, and does not label a file as malware because
of its name.

### Not verified in this release

Windows telemetry parsing is covered by fixtures only. No Windows collector has
been run against a real Windows host. Windows artifacts and the release
workflow's Windows job remain unexecuted.

## 0.3.0 — 2026-09-13

Engine startup and release packaging. The application is now self-contained on
Linux: it locates and launches its own engine with no Python, no manually
started Flask, and no environment variable on the target machine.

### Fixed

- **The packaged Linux application could not reach its engine.** The release
  bundle contained no `backend/` directory at all, so `BackendSupervisor`
  resolved no executable and never launched anything. The engine is now
  installed into the bundle by `linux/CMakeLists.txt` and
  `windows/CMakeLists.txt`, so a plain `flutter build` produces a complete,
  runnable application. Previously the copy lived only in
  `packaging/linux/build.sh`, and the Flutter install step deletes the whole
  bundle directory on every build — so any copy made by a script was discarded
  by the next `flutter build linux`.
- **The reported cause was wrong.** The 15-second health poll ran without a
  bootstrap session, reported `No engine is listening on http://127.0.0.1:5000`
  against a port the engine never uses, and overwrote the real failure. The
  engine binds an OS-assigned port and mints a per-process token, both announced
  over the bootstrap channel, and every route including `/health` requires that
  token — so a probe without a session cannot succeed and no longer runs.
- **The developer fallback path pointed at a directory that never existed**
  (`<bundle>/../../../../desktop/backend-dist/`). Discovery now walks up from
  the executable to find `backend-dist/`, instead of counting `../` segments
  that differ between Linux and Windows.
- **System Status showed `127.0.0.1:5000` while the engine ran on another
  port.** The endpoint is now published from the bootstrap record when the
  engine reports ready, and reads "not assigned yet" before that.
- `waitForReady` replaced a precise exit reason with a generic timeout when the
  engine exited during startup. The recorded exit code and reason now survive.
- A stale bootstrap token was presented to a replacement engine after a restart.
  The session is cleared when the process it belongs to exits.

### Added

- Engine startup diagnostics name the actual cause: the engine's own
  `startup_error` message, its last stderr lines on an early exit, and a
  per-candidate verdict for discovery (`missing`, `is a directory`,
  `not executable`) instead of only "not found".
- A file present but without an execute bit is rejected during discovery rather
  than failing later with a less obvious error.
- `flutter_client/test/integration/packaged_engine_test.dart`: starts the real
  bundled engine through the real locator over real authenticated HTTP, and
  fails if the endpoint is still the placeholder port. Skips itself when no
  release bundle is present.
- `packaging/windows/build_portable.ps1` produces a portable Windows ZIP.
- `.github/workflows/ci.yml` runs the backend, smoke and client suites on every
  push. `.github/workflows/release.yml` builds the Debian package on
  `ubuntu-latest` and the installer and portable ZIP on `windows-latest`, on
  manual dispatch or a `v*` tag. Building never publishes by itself.

### Changed

- `packaging/linux/build.sh` and `packaging/windows/build.ps1` verify that the
  bundle they produced contains a runnable engine and its `_internal` runtime,
  and fail instead of shipping an incomplete bundle.
- `packaging/linux/build_deb.sh` verifies the built `.deb` actually carries the
  client, the engine and its runtime. It also clears the set-group-ID bit the
  build tree inherits, which `dpkg-deb` rejects on the control directory.
- The Inno Setup script takes its version from `JOCKY_VERSION`, writes to
  `build/windows/installer/`, names the engine as a required source so an
  installer cannot be built without it, and removes the application directory
  on uninstall while preserving operator data in `%LOCALAPPDATA%\JOCKY`.
- The `/health` fixture carries `instance_id`, which the real backend has always
  returned. Widget tests now start from a bootstrapped session, matching the
  only state in which the running application can reach the engine.

### Not verified in this release

Windows artifacts and both GitHub Actions workflows are configured but have not
been executed: this work was done on Linux, and Windows builds require a Windows
host. 1.0.0 is deferred until a Windows installer and the release workflow have
both been run and verified.

## 0.2.0

Flutter desktop client, backend service, SQLite-backed investigations, offline
PDF reporting and the initial packaging scripts.
