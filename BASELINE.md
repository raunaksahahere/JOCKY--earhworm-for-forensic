# Backend foundation baseline

Base branch: `main`.
Base commit: `8f77a1c3a29206b82088da0433779505461834c6`.
Working branch: `backend-foundation`.

This is a record of the repository as it stood at that commit, kept for
provenance. Paths it names are historical: the React dashboard, the Electron
shell and the native prototypes it describes were removed after v0.9.0.

This local application checkout preserves the complete audited source history
and directory layout. It has no configured remote. The separate reference
checkout is unchanged. No project-wide reuse license was found: this document
does not grant or invent a license. Existing source notices remain intact;
permission to redistribute derived application code remains unresolved.

## Planned change scope (recorded before engine edits)

Modified existing files:
- `compiler/grammar.lark`
- `compiler/parser.py`
- `compiler/Transformer.py`
- `compiler/Language_meta.py`
- `compiler/Language.md`
- `communication/server.py`
- `analysis/hashing.py`
- `analysis/ledger.py`
- `analysis/files.py`
- `analysis/processes.py`
- `analysis/system.py`
- `analysis/integrity.py`
- `reports/report.py`
- `tests/test_crypto.py`

Scope adjustment after the first full test run: truthful nullable measurements
would crash the legacy process table's unconditional `.toFixed()` calls. Two
minimal compatibility edits are therefore included (no UI migration):
- `dashboard/src/lib/types.ts`
- `dashboard/src/components/forensics/processes-table.tsx`

New files:
- `.gitignore`, `requirements-dev.txt`, `pytest.ini`, `BASELINE.md`
- `compiler/commands.py`, `COMMAND_CONTRACT.md`
- `tests/conftest.py`, `tests/test_parser.py`, `tests/test_api.py`
- `tests/test_hashing.py`, `tests/test_files.py`, `tests/test_observation.py`
- `tests/test_indicators.py`, `tests/test_integrity.py`
- `tests/test_reports.py`, `tests/test_ledger.py`, `tests/test_dispatcher.py`

Workspace planning updates: `../docs/Tracker.md`, `../docs/ImplementationPlan.md`.
Legacy presentation, native agent, packaging, dispatcher routing, and encryption
implementation are retained. This slice introduces no Flutter, database, server
runtime migration, new language actions, or new forensic collectors.

## Development

Use Python 3.10+ in an isolated virtual environment. Install
`requirements-dev.txt`, then run `python -m pytest`. Tests isolate ledger writes
and all evidence in temporary directories. Platform collectors use deterministic
fixtures; they do not assert facts about the developer's host.

## Completed validation

Executed on Linux with Python 3.12 and the pinned direct requirements in
`.venv`. The installed psutil and cryptography versions are the repository's
6.0.0 and 42.0.5 pins. No system Python packages were changed.

From this application directory:

```text
.venv/bin/python -m pytest -q
244 passed, 0 failed, 0 skipped

.venv/bin/python -m pytest tests/test_parser.py -q
82 passed, 0 failed, 0 skipped

.venv/bin/python -m pytest tests/test_hashing.py tests/test_files.py tests/test_observation.py tests/test_indicators.py tests/test_integrity.py tests/test_ledger.py -q
122 passed, 0 failed, 0 skipped

.venv/bin/python -m compileall -q compiler communication analysis crypto reports tests desktop
Passed

.venv/bin/python -m pip check
No broken requirements found

git diff --check
Passed
```

The focused test counts overlap the full suite; they are not additional tests.
The API tests use Flask's real test client and execute real parser/dispatcher
paths. Host/process observations and permission failures use deterministic
fixtures. Crypto round trips exercise the unchanged implementation on temporary
copies. Ledger concurrency tests cover threads in one process, not multiple
backend processes.

From `dashboard/`, after installing the existing lockfile with
`npm ci --ignore-scripts --no-audit --no-fund --cache /tmp/jocky-npm-cache --fetch-retries=0 --fetch-timeout=10000`:

- `./node_modules/.bin/tsc --noEmit`: passed.
- `./node_modules/.bin/eslint src/lib/types.ts src/components/forensics/processes-table.tsx`: passed.
- `npm run build`: passed (Vite production bundle).
- `npm run lint`: failed with one pre-existing Prettier formatting error in
  `src/routes/__root.tsx:18` and seven pre-existing Fast Refresh warnings.
  The formatting failure was reproduced by passing the exact HEAD version of
  that file to ESLint via stdin. Those unrelated files were not changed.

The Vite router generator rewrote two route files during the build; those
build-induced edits were restored to HEAD after verification. The only final
dashboard source edits are the two documented null-compatibility changes.
The package lock is unchanged. No UI interaction, Windows runtime, native
installer, frozen backend, or Linux package tests were performed in this slice.
Initial sandbox dependency downloads failed DNS resolution; approved network
retries installed the dependencies and the checks above actually ran.

## Handoff

The next task is backend-owned transactional persistence with explicit user-data
locations. Preserve command contract v1 while moving hash observations and
reports out of source-relative JSON/browser storage. Include migration and
crash/concurrency tests before changing the production runtime.

Known remaining boundaries: the development Flask server and permissive CORS
remain; crypto still overwrites files using its legacy fixed key; the JSON ledger
has only process-local locking and no protection against external deletion;
structural checks have byte/member limits, not cancellation or wall-clock limits.
The new nullable process values and creation timestamps are intentional contract
corrections; the legacy process renderer has been adapted accordingly.
