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

`analysis/memory.py` and `backend/memory_workflow.py`, `tests/test_multihost.py`.

The workflow is complete: an image is registered as an evidence source, hashed,
and **re-verified immediately before analysis** — a changed image is refused,
because attributing findings to bytes that are no longer there is the failure
this exists to prevent. The analysis learns the image's platform by trying each
platform's process listing, normalizes processes, loaded modules and memory
mappings, and records per record which plugin produced it and whether the value
was read directly or derived. Results carry the digest of the image and a
provenance statement. Findings are linked to the analysis.

**The gap, unchanged:** no real memory image has been analysed, because none was
available. The Volatility3-driving path is exercised only against fixtures.
`GET /api/v1/memory/capability` reports plainly whether a tool is installed, and
on the development host it is not.

Read-only by construction: `limits` records `memory_written: false` and
`code_executed: false`, and JOCKY does not acquire memory.

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

**IMPLEMENTED · REAL LINUX MULTI-HOST VALIDATED**

`analysis/fleet_correlation.py`, `validation/multihost.py`,
`tests/test_multihost.py`.

The previous pass validated this degenerately — two agents on one machine, where
every observable is trivially shared — and said so. That is now fixed.
`validation/multihost.py` runs two Docker containers and **proves the separation
before it proves anything else**: distinct hostnames, distinct process tables
both beginning at pid 1, and a file planted on one host demonstrably absent on
the other. It then plants one file on both and one on only one, and asserts the
shared SHA-256 correlates naming both endpoints while the unique one does not
correlate at all. Both assertions pass, and it runs in the test suite.

**What this does not establish:** containers share the host kernel, so
kernel-level sources — loaded modules, the kernel log — would report the host's
state on both endpoints. The validation deliberately asserts nothing that
depends on them. Two containers are two Linux environments, not two physical
machines; network path, hardware and firmware evidence are not covered.

Scenario D remains the **synthetic** multi-host scenario and is labelled as such.
The two are not conflated anywhere.

## Q — Investigation thread model

**IMPLEMENTED · LINUX VALIDATED**

`analysis/threads.py`, `analysis/activity.py`. Union-find over rare shared
tokens with an inverted index; `tests/test_performance.py` guards against the
quadratic regression that once stalled collection.

## R — Scalability path

**IMPLEMENTED (documented and tested, deliberately not built)**

`docs/Architecture.md`, "The path off SQLite", plus
`tests/test_storage_abstraction.py` (11 tests).

The documented path rests on a claim that only the storage layer knows it is
SQLite. A claim like that rots silently, so it is now checked: the analysis layer
never reaches for JOCKY's store, the `Store` interface is three methods, only
seven modules contain SQL at all, and the casework and fleet layers are exercised
against a substitute store that records what was asked of it.

One documented exception: `analysis/browser.py` opens SQLite to read a *browser's*
history database as evidence, having copied it aside first. That has nothing to
do with where JOCKY keeps its records, and a second test asserts it still copies
and still opens read-only.

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

`backend/pdf_report.py`, `backend/evidence_package.py`,
`tests/test_report_packaging.py` (23). See `docs/ReviewBriefs.md`.

Three documents, split so each does one job. The **investigator report** is the
narrative alone — nine sections, then it stops — and is 8 pages for a day of
telemetry that previously produced 71. Its length is set by how much there is to
say: a test renders the same narrative over 20 activities and over 700 and fails
if the page count moves by more than two.

The **evidence package** carries everything that left the report, one file per
source, plus both PDFs and a manifest recording the collection period, every
version including each collector's own, the evidence-source IDs and a SHA-256
per file. A test counts activities, command-history records, artifacts,
findings, threads and processes on both sides of the export and compares the
individual evidence references, because "nothing was removed" has to be
checkable.

The **routine activity report** and **review briefs** remain separate and
optional. `render_pdf` keeps its previous behaviour, so existing callers get the
full document unchanged.

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
endpoints, audit trail), the collection source picker, the recognition badge,
the presentation filter, the review brief dialog and the routine export.
158 Flutter tests.

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

Three separate claims, deliberately not blurred. See `docs/WindowsValidation.md`.

| Claim | Status |
|-------|--------|
| Windows application build | **VALIDATED** — `windows.yml` on `windows-latest` |
| Windows packaged runtime | **VALIDATED** — the published artifact starts, serves its API and completes a read-only workflow |
| Windows GitHub release | **PUBLISHED** — portable archive and installer are Release assets |
| Windows forensic host collection | **NOT YET VALIDATED** |

The application builds and the packaged artifact runs, verified against the file
that is actually published: it is downloaded back from the Releases page, checked
byte-for-byte against the build that passed, and run again on a fresh runner.

**What remains unvalidated is the forensic part.** An executable that launches is
not a validated forensic collector. `analysis/execution_windows.py` is
fixture-tested against documented event formats, not against a host's real
telemetry, and no output has been compared with a Windows machine. Four of the
six selectable sources — `BROWSER`, `USB`, `DRIVERS`, `SERVICES` — have no
Windows adapter entry at all; `GET /api/v1/collection-sources` reports that per
source with the reason, and the client disables them rather than letting an
investigator select one and find no evidence in the report.

`WindowsAdapter.validated` is `False` and `describe_plan` prints `NOT VALIDATED
ON A REAL HOST` on every Windows plan. Nothing in this project should be
described as *forensically* working on Windows.

## Test coverage

| Suite | Count |
|-------|-------|
| Python | 828 |
| Flutter | 169 |

---

## Completion-pass features

## AB — Software recognition

**IMPLEMENTED · LINUX VALIDATED**

`analysis/recognition.py`, `analysis/data/software_reference.json`,
`tests/test_recognition.py` (17). See `docs/Recognition.md`.

Four layers: package ownership (421,000 paths from 2,784 packages on the
development host, nothing hardcoded), snap metadata, 14 vendor layout
descriptors each requiring a marker file, and location — which is reported as a
location and never as an identity. Every result states its basis, names its
source, cites the evidence it annotates and states its limits. No safety score;
a test asserts the words "safe", "clean", "benign" and "trusted" appear nowhere
in a result.

Nothing is executed: a test reads the module's source and fails on any execution
path. Recognition is context and cannot cancel a concern signal — a recognized
interpreter running from `/tmp` with remote content piped into it still scores
POTENTIALLY HARMFUL.

## AC — Routine / recognized classification

**IMPLEMENTED · LINUX VALIDATED**

A presentation category kept apart from the triage category. On the development
host it splits 709 activities into 405 routine, 299 for review and 5 needing
attention, with every triage category unchanged. A recognized interpreter whose
arguments were not recorded deliberately stays for review.

## AD — Review briefs

**IMPLEMENTED · LINUX VALIDATED**

`analysis/briefs.py`, `backend/brief_pdf.py`, `tests/test_briefs.py` (31).
See `docs/ReviewBriefs.md`.

Briefs for artifacts, findings, activities, leads and threads; 1–2 page PDF,
JSON, and an on-screen dialog with the same sections in the same order. Every
statement traces to a stored record: a browser link requires a download record
naming that path, a network link requires a socket record owned by that process,
and proximity in a timeline never produces either. Generated briefs are stored
with their evidence identifiers and audited.

## AE — Routine activity report

**IMPLEMENTED · LINUX VALIDATED**

A separate optional document, never the primary report. 404 routine activities
collapse to nine groups with their evidence identifiers attached. Called
Routine / Recognized, never Safe, and every copy carries the sentence saying it
is not a guarantee.

## AF — Investigator search

**IMPLEMENTED · LINUX VALIDATED**

`analysis/search.py`. Artifacts, hashes, executables, full commands, URLs,
domains, endpoints, users, threads, leads, findings, recognized names,
classification, priority and evidence sources. Each hit names the field that
matched, so a term found in a URL is distinguishable from the same term in a
filename. Searching a recognized name finds records whose command line never
contains it.

## AG — Investigator assessments

**IMPLEMENTED · LINUX VALIDATED**

`investigator_assessments`, `tests/test_assessments.py` (10). Stored beside the
machine's classification, never over it, with the machine's conclusion copied in
as it stood. A test asserts the machine's stored triage is byte-identical after
an assessment that disagrees with it.

## AH — Case summary and narrative traceability

**IMPLEMENTED · LINUX VALIDATED**

`analysis/case_summary.py`, `report_narrative`. Every generated sentence is
emitted with the evidence identifiers behind it and stored per statement. A test
asserts the summary never asserts a reassuring claim without negating it.

## AI — Evidence package integrity

**IMPLEMENTED · LINUX VALIDATED**

`backend/evidence_package.py`. A manifest naming the case, investigation, every
version, the endpoints, the registered sources with digests and integrity
history, the collectors and their status, the programs, and the SHA-256 of every
file as written. `verify_package` re-hashes them; a test alters one file and
asserts verification fails naming it.

## AJ — File and disk evidence

**IMPLEMENTED · LINUX VALIDATED (identification only)**

Containers are identified from their own header — EWF, EWF2, AFF, QCOW, VMDK,
VHD, raw — and the record says what JOCKY can and cannot do with each.

**Deliberately not implemented:** JOCKY does not parse forensic containers.
Writing another image parser would be the wrong kind of work when mature
read-only tooling exists. A container is named, hashed and preserved, and the
record says what would expose its contents (`ewfmount`, `qemu-nbd`). No
container has been extracted or validated beyond identification.
