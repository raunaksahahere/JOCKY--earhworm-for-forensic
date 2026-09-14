# Requirement matrix

Every requirement from the completion pass, what implements it, what tests it,
and how far it has actually been validated.

## Status vocabulary

| Status | Meaning |
|--------|---------|
| **IMPLEMENTED** | Built, tested, and exercised against a real Linux host. |
| **PARTIALLY IMPLEMENTED** | Built and tested, but a named part is missing. The gap is stated. |
| **FIXTURE/SYNTHETIC** | The code path is exercised only against fabricated data. |
| **LINUX VALIDATED** | Run against a real Linux machine, not only fixtures. |
| **WINDOWS READY / NOT VALIDATED** | The interface and mapping exist; no Windows host has run it. |
| **NOT IMPLEMENTED** | Absent. |

A thing is not complete because it compiles. Everything below marked LINUX
VALIDATED was run against the machine this was developed on; everything marked
WINDOWS READY / NOT VALIDATED has not been run on Windows at all, and no claim
about Windows behaviour should be read into it.

---

## A — Investigation language

**IMPLEMENTED · LINUX VALIDATED**

| | |
|--|--|
| Grammar | `compiler/investigation.lark` |
| Parser, validator, IR | `compiler/investigation.py` |
| Tests | `tests/test_investigation_language.py` (22) |

Statements: `CASE`, `TARGET`, `WINDOW`, `LET`, `COLLECT`, `FILTER`, `CORRELATE`,
`TIMELINE`, `REPORT`. Validation refuses a program with no case, no collection,
a duplicated collection, a relative `COLLECT FILES` path, a `CORRELATE` naming a
subject the program never collects, an invalid `MATCHES` pattern, `COLLECT
MEMORY` with no image, or a window beyond 90 days.

## B — Platform-neutral IR

**IMPLEMENTED · LINUX VALIDATED**

`IR_VERSION = 1`. `serialize`/`deserialize` round-trip is asserted. The IR names
sources and bounded options; it contains no platform detail and no command.

## C — Execution plan and platform adapter

**IMPLEMENTED (Linux) · WINDOWS READY / NOT VALIDATED**

`compiler/plan.py`. `LinuxAdapter` maps eleven sources; `WindowsAdapter` maps
six and carries `validated = False`, which `describe_plan` prints as
`NOT VALIDATED ON A REAL HOST`. A source the platform cannot provide becomes a
named `UNSUPPORTED` task rather than an error.

## D — Evidence acquisition workflow

**IMPLEMENTED · LINUX VALIDATED**

`backend/casework.py`, schema migration 5, `tests/test_casework.py` (19).

Register, hash, verify, associate with a case, preserve provenance. A source is
never overwritten: re-registering the same bytes creates a new row naming what
it supersedes. A digest that no longer matches is recorded as `MISMATCH` and the
original digest is kept. A failed acquisition is stored, not discarded.

## E — Audit trail

**IMPLEMENTED · LINUX VALIDATED**

`audit_events` table; `Casework.audit`. Each record holds timestamp, actor,
action, object type and id, case and investigation, outcome and detail. The
investigation lifecycle (`investigation.created`, `collection.requested`,
`collection.finished`, `collection.dispatched`, `collection.task_abandoned`) and
every casework and endpoint action are audited. A test asserts evidence content
never reaches the trail.

## F — Broader Linux coverage

**IMPLEMENTED · LINUX VALIDATED**

`analysis/system_services.py` (systemd units, cron), plus the existing journal,
shell history, audit log, process accounting and wtmp collectors.

## G — Browser forensics

**IMPLEMENTED · LINUX VALIDATED**

`analysis/browser.py`. Firefox `places.sqlite` and Chromium/Brave/Edge
`History`. The database is copied aside and opened read-only, so a live browser
is never disturbed and the original is never written — asserted byte-for-byte in
`tests/test_collectors_extended.py`. History and downloads only; `limits` names
each secret class it does not read.

## H — USB / removable media

**IMPLEMENTED · LINUX VALIDATED**

`analysis/usb.py`. sysfs device identity, kernel attach/detach events, removable
mounts. `limits.media_contents_read` is `false`; JOCKY does not read what is on
a device.

## I — Network metadata

**IMPLEMENTED · LINUX VALIDATED**

`analysis/network.py`. Interfaces, addresses, resolver, routes, sockets with the
owning process. `limits.packet_capture` is `false`. No traffic is intercepted.

## J — Memory forensics

**PARTIALLY IMPLEMENTED · FIXTURE/SYNTHETIC**

`analysis/memory.py` drives Volatility3 when it is present and normalizes its
process rows. Provenance is always one of `REAL`, `FIXTURE` or `UNAVAILABLE`.

**The gap:** no real memory image has been analysed during development, because
none was available. The tool-driving path is exercised only against fixtures. It
is read-only by construction — `limits` records `memory_written: false` and
`code_executed: false` — and JOCKY does not acquire memory; it analyses an image
the investigator supplies.

## K — File and disk evidence

**IMPLEMENTED · LINUX VALIDATED**

Existing artifact hashing and integrity ledger, joined to the evidence-source
workflow in D.

## L — Driver-risk verification

**IMPLEMENTED · LINUX VALIDATED**

`analysis/drivers.py` with a 687-entry reference derived from LOLDrivers (831
names, 2,266 SHA-256 hashes). Verification only: `limits.drivers_loaded_or_modified`
is `false`. A hash match is high confidence; a filename match is low and is only
attempted for Windows-style records, because matching the Linux `msr` module
against `msr.sys` produced a false positive on every Linux host.

## M — Memory and driver detections

**IMPLEMENTED · FIXTURE/SYNTHETIC for the memory rules**

`analysis/detections.py`, six named rules, `DETECTION_RULESET_VERSION = 1`. Each
finding cites the rule that fired. A driver match says the driver is present,
never that it was abused here. A memory finding from a fixture is classified
`INFERRED` so it cannot be read as evidence about a host.

## N — Case management

**IMPLEMENTED · LINUX VALIDATED**

Cases, notes and the investigation-to-case link. Investigator notes are stored
apart from machine evidence, because an interpretation must never end up looking
like an observation.

## O — Authorized multi-endpoint architecture

**IMPLEMENTED · LINUX VALIDATED**

`backend/fleet.py`, `endpoint/agent.py`, schema migration 6,
`tests/test_fleet.py` (22) and `tests/test_casework_api.py` (16).

Enrollment, identity, authentication, heartbeat, capability report, task queue,
result ingestion, retry with backoff, and parallel collection across endpoints.
See `docs/EndpointProtocol.md` for why an endpoint cannot be sent a command.

## P — Multi-endpoint correlation

**IMPLEMENTED · LINUX VALIDATED (degenerate) · see limitation**

`analysis/fleet_correlation.py`. Shared file hashes, remote addresses, drivers,
downloads and removable devices.

**The limitation:** the only multi-host run performed was two agents on one
machine, where every observable is trivially shared. The demo says so in its own
output. Scenario D is the multi-host case with genuinely separate evidence, and
it is synthetic.

## Q — Investigation thread model

**IMPLEMENTED · LINUX VALIDATED**

`analysis/threads.py`, `analysis/activity.py`. Union-find over rare shared
tokens with an inverted index; `tests/test_performance.py` guards against the
quadratic regression that once stalled collection.

## R — Scalability path

**IMPLEMENTED (documented, not built)**

`docs/Architecture.md`, "The path off SQLite". Domain models, repositories and
storage are already separate; the transition is described rather than performed,
because rewriting working storage without a workload that needs it would be
churn.

## S — Performance and reliability

**IMPLEMENTED · LINUX VALIDATED**

`tests/test_performance.py` (12): grouping stays roughly linear, threading does
not go quadratic, every collector has a ceiling, and one failing collector
degrades a collection to `partially_completed` rather than failing it.

## T — Reproducibility

**IMPLEMENTED · LINUX VALIDATED**

`investigation_programs` stores the program text, the IR, the plan, the platform
and every component version. A collection driven from the UI is as reproducible
as one driven from the language, because the UI's source selection is compiled
into a program first.

## U — Report and evidence package

**IMPLEMENTED · LINUX VALIDATED**

Eight-page investigator PDF with appendices A–I; the full payload, endpoint
results, cross-host correlation and audit trail as JSON. `scripts/demo.py`
writes the complete package.

## V — CI/CD

**IMPLEMENTED**

`.github/workflows/ci.yml` runs the Python suite, the Flutter suite and the
analyzer. `release.yml` builds and publishes the Linux `.deb`.

## W — Synthetic scenarios

**IMPLEMENTED · FIXTURE/SYNTHETIC by definition**

`scenarios/library.py`, scenarios A–F, deterministic. Every record carries
`synthetic: true` and a source beginning with `SYNTHETIC`.

## X — End-to-end demo

**IMPLEMENTED · LINUX VALIDATED**

`scripts/demo.py`, documented in `docs/Demo.md`. Thirteen steps from a clean
checkout.

## Y — Investigator UX

**IMPLEMENTED · LINUX VALIDATED**

`lib/features/casefile/case_file_screen.dart` (cases, evidence sources,
endpoints, audit trail) and the collection source picker in the device screen.
151 Flutter tests.

## Z — Documentation

**IMPLEMENTED**

This file and the rest of `docs/`.

## AA — Reference project learning

**IMPLEMENTED**

See `docs/ReferenceRepos.md`. No reference repository is vendored into the
product; only the derived LOLDrivers reference data is, with its source recorded
in the file.

---

## Windows

**WINDOWS READY / NOT VALIDATED**, without exception.

The Windows collectors exist and are fixture-tested. The Windows adapter maps
six sources. The packaging configuration exists. No Windows host has run any of
it. Nothing in this project should be described as working on Windows.

## Test coverage

| Suite | Count |
|-------|-------|
| Python | 708 |
| Flutter | 151 |
