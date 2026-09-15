# Tech stack

| Layer | Choice | Why |
|-------|--------|-----|
| Client | Flutter desktop (Linux, Windows-ready) | One codebase, native desktop, no browser and no web server |
| State | Riverpod | Explicit injection seams; every service is overridable in tests |
| Routing | go_router | Declarative routes, deep links into an investigation |
| Engine | Python 3 + Flask | Loopback only; the forensic libraries live here |
| Grammar | Lark | EBNF close enough to read as documentation |
| Process/host | psutil | Cross-platform, no shelling out to parse text |
| Storage | SQLite (WAL, `synchronous=FULL`) | One file an investigator can hand over; no server to run |
| PDF | reportlab | Offline; no network at report time |
| Freeze | PyInstaller, one-directory | The packaged app carries its own engine |
| Linux package | `.deb` | Installs the client and the engine together |
| Windows package | Inno Setup | Configured; never built on Windows |
| CI | GitHub Actions, native runners | Cross-compiling a desktop app is how you ship a broken one |

## Dependencies and their boundaries

**psutil** — process and network enumeration. Read-only.

**Lark** — parses the investigation language. Produces a tree; JOCKY converts it
to a plain dictionary immediately, so no parser object reaches the IR or the
plan.

**Flask** — the loopback API. Authentication is a `before_request` hook: bearer
token, instance header, loopback peer, no browser `Origin`. Endpoint-agent
routes are the single exception and carry their own credential.

**reportlab** — the report. Chosen because it needs nothing at render time; a
report must be producible on a machine with no network.

**Volatility3** — optional, located by `shutil.which`, never bundled. Absent
means memory analysis reports `UNAVAILABLE`, which is a stated gap rather than a
failure.

## What is deliberately not used

**A web frontend.** A browser origin is an attack surface a forensic workstation
does not need, and the engine refuses any request carrying one.

**An ORM.** Every SQL statement is visible in three service classes and
`storage.py`. For code whose correctness is the product, generated queries are a
liability, and having them all in one place is what makes the move off SQLite
cheap (see `docs/Architecture.md`).

**A task queue or broker.** One bounded worker with a queue of eight. A forensic
workstation examines one machine at a time; a broker would be infrastructure
with nothing to do.

**A packet capture library.** Deliberate. See `docs/SecurityBoundaries.md`.

## Versions recorded with every result

```
application 0.8.1   API 1            report schema 5
database 6          IR 1             plan 1          ruleset 1
```

## Layout

```
application/
  analysis/     collectors, normalization, correlation, detection
  backend/      API, services, storage
  compiler/     language, IR, execution plan
  endpoint/     the agent for another authorized machine
  scenarios/    synthetic lab data
  reports/      report construction
  crypto/       explicit-passphrase export
  tests/        708 tests
  scripts/      build, smoke test, demo
  flutter_client/
    lib/features/   one directory per screen
    lib/state/      providers and controllers
    lib/services/   API client, supervisor, stores
    test/           151 tests
  docs/
```
