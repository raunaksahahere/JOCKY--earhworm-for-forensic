# Changelog

All notable changes to JOCKY. Versions follow semantic versioning.

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
