# JOCKY Forensic Workstation — Flutter desktop client

Desktop presentation layer for the existing JOCKY defensive digital-forensics
engine. Targets Windows and Linux.

This client renders what the engine returns. It does not parse commands,
validate them, collect evidence, or generate reports — all of that belongs to
the Python backend in `../compiler`, `../analysis`, `../communication` and
`../reports`, and duplicating any of it here would create a second, divergent
authority over forensic behaviour.

This client is the only user-facing application. The React/Vite dashboard and
the Electron shell it once coexisted with have been removed.

## Backend contract consumed

The engine (`../communication/server.py`) exposes exactly three endpoints, and
this client calls exactly those three:

| Endpoint | Used for |
| --- | --- |
| `GET /health` | readiness probe, startup wait, System Status |
| `GET /commands` | the command reference and which guided tools to offer |
| `POST /command` | every observation, from both the Command Center and Tools |

Bootstrap follows the contract the repository established in the Electron shell
that preceded this client: spawn the packaged engine with `JOCKY_HOST` and
`JOCKY_PORT`, then poll `/health` until it answers. The engine emits no
machine-readable startup document, so its stdout/stderr are captured for
diagnostics only and are never parsed as a readiness protocol.

## What the backend does not provide

These gaps are visible in the UI rather than filled in with invented data:

* **No authentication or session.** The engine serves plain HTTP with permissive
  CORS. Settings warns when the endpoint is not loopback.
* **No version fields.** `/health` returns `{status, engine}` only. System
  Status and Settings show backend version, API version, storage readiness and
  permission inventory as "not reported by backend".
* **No case, evidence, execution, history or report endpoints.** Cases, evidence
  lists, notes, execution history and the report archive are held in this
  client's own local record store and are labelled as client-side provenance
  throughout.
* **No cancellation.** The dispatcher is synchronous. Stopping a command
  abandons this client's wait; the UI says "abandoned", never "cancelled".
* **No PDF.** PDF is rendered locally and every page says so.

## Architecture

```text
Widget → Controller (Riverpod) → Repository → JockyApiClient → local engine
```

```text
lib/
  app/          shell, routing, sidebar, palette, keyboard intents
  core/         config, failure taxonomy, transport seam, theme tokens, utils
  models/       typed commands, results, reports, executions, cases, settings
  services/     API client, backend supervisor, record + settings stores,
                file selection, report export
  repositories/ command, backend, records
  state/        Riverpod providers and feature controllers
  features/     overview, command_center, investigations, reports, history,
                tools, system_status, settings
  widgets/      panels, dense data grid, status chips, result renderers
```

Every model keeps the raw JSON it was decoded from, so fields a newer engine
adds survive into detail views and exports instead of being dropped.

Nullability is contractual: `memory_percent`, `cpu_percent`, `created` and
`execution_time_ms` are rendered as an explicit unavailable marker with the
reason in a tooltip. They are never shown as zero.

## Keyboard

| Shortcut | Action |
| --- | --- |
| `Ctrl+Enter` | Execute the command in the editor |
| `Ctrl+K` | Command / navigation palette (loads commands, never runs them) |
| `Ctrl+O` | Select an evidence file |
| `Ctrl+F` | Focus search in Reports and History |
| `Ctrl+1`…`Ctrl+8` | Jump to a primary destination |

## Development

```bash
flutter pub get
flutter analyze
flutter test
flutter run -d linux      # expects an engine on 127.0.0.1:5000
```

Test fixtures in `test/fixtures/` were captured from a live Flask backend, not
hand-written, so a change in the engine's response shape fails these tests.

Packaging: see `packaging/README.md`.
