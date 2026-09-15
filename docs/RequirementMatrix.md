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

## A — The JOCKY language

**IMPLEMENTED · LINUX VALIDATED**

| | |
|--|--|
| Source extension | `.x` |
| Grammar | `compiler/investigation.lark` |
| Parser, validator, IR | `compiler/investigation.py` |
| Predicate evaluation | `compiler/predicate.py` |
| Worked programs | `examples/*.x` (5) |
| Tests | `tests/test_investigation_language.py` (56), `tests/test_predicate.py` (28), `tests/test_examples.py` (18 + 4 skipped) |

Statements: `CASE`, `TARGET`, `WINDOW`, `LET`, `DEFINE`, `RUN`, `WHEN`,
`COLLECT`, `FILTER`, `CORRELATE`, `TIMELINE`, `REPORT`.

| Feature | Status |
|---------|--------|
| Core statements | IMPLEMENTED |
| `DEFINE`/`RUN` playbooks, expanded into the IR with cycle and depth detection | IMPLEMENTED |
| `WHEN PLATFORM IS` / `WHEN SOURCE … IS SUPPORTED`, resolved by the adapter | IMPLEMENTED |
| Boolean predicates: `AND`, `OR`, `NOT`, parentheses, correct precedence | IMPLEMENTED |
| List values and `ONEOF` membership | IMPLEMENTED |
| Named reports (`REPORT BOTH AS "…"`) | IMPLEMENTED |
| `FILTER` applied to collected evidence as a selection | IMPLEMENTED |

Validation refuses a program with no case, no collection, a duplicated
collection under the same conditions, a relative `COLLECT FILES` path, a
`CORRELATE` naming a subject the program never collects, an invalid `MATCHES`
pattern anywhere in an expression, `ONEOF` without a list, a single-value
operator given a list, an undefined variable, a `RUN` of an undefined playbook,
a playbook that runs itself, a duplicate `DEFINE`, `COLLECT MEMORY` with no
image, or a window beyond 90 days.

Every statement is read out of the parse tree by node and token type rather than
by position. An earlier revision indexed children positionally; naming the
keywords as terminals changed what the parser keeps in the tree and broke the
entire front end at once.

## B — Platform-neutral IR

**IMPLEMENTED · LINUX VALIDATED**

`IR_VERSION = 2`. `serialize`/`deserialize` round-trip is asserted, including for
predicate trees and conditions. The IR names sources and bounded options; it
contains no platform detail and no command.

Version 2 added playbooks, `WHEN` conditions, predicate trees, list values and
named reports. Filters and reports changed shape, so a version-1 IR is refused
rather than misread — `tests/test_investigation_language.py` asserts that.

A `WHEN` guard is carried in the IR and resolved only when a plan is built, which
is what keeps the IR platform-neutral: the same IR yields a different plan per
platform.

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

## AK — Filter selection over collected evidence

**IMPLEMENTED · LINUX VALIDATED**

| | |
|--|--|
| Evaluator | `compiler/predicate.py` |
| Selection over a report | `analysis/selection.py` |
| Route | `GET /api/v1/investigations/<id>/selection` |
| Tests | `tests/test_predicate.py` (28), `tests/test_selection.py` (11) |

A `FILTER` states what the investigation is interested in, and it is answered
against what was collected. It does **not** reduce evidence: evidence is
registered and hashed whole, and a selection is a view over it. A test deep-
copies the report, runs a selection and asserts the report is unchanged.

The filters come from the stored IR rather than from the request, so a selection
is reproducible from the record. An empty selection means the evidence does not
answer the question — not that the evidence is gone, and the response says so.

## AL — The language in the application

**IMPLEMENTED · LINUX VALIDATED**

| | |
|--|--|
| Editor | `flutter_client/lib/features/language/language_screen.dart` |
| Repository | `flutter_client/lib/repositories/language_repository.dart` |
| Tests | `flutter_client/test/widget/language_screen_test.dart` (9) |

**JOCKY Language** in the client: load or write a `.x` program, compile it, read
the IR and the execution plan, run it, open the resulting investigation.

The client never parses, validates or explains a program itself — every result
comes from `POST /api/v1/programs/compile`, the same compiler a collection runs
through, so the editor cannot report a program valid that a collection would
refuse. A widget test asserts the editor sends exactly the text on screen, that
running is disabled until a program compiles, and that a collection started from
the editor carries `program` and not a source list.

The five examples the editor offers are generated from `examples/*.x` by
`scripts/generate_language_examples.py`; `tests/test_examples.py` fails if the
two copies drift.

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
| Windows application build | **VALIDATED** — `windows.yml` on Windows Server 2025, run `34971374632` |
| Windows packaged runtime | **VALIDATED** — the published artifact starts, serves its API and completes a read-only workflow |
| Windows GitHub release | **PUBLISHED** — portable archive (41.7 MB) and installer (32.0 MB) attached to v0.8.1 alongside the Linux `.deb` |
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

Software recognition has no Windows source either: package ownership and snap
metadata are Linux, so every Windows artifact comes back unaccounted for. The
report names which recognition sources it could read, so "recognized nothing" is
distinguishable from "had nothing to recognize with".

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

---

# The problem statement, mapped

The Smart India Hackathon problem statement asks for a proprietary programming
language and a set of capabilities, some of which are offensive. This is what
this repository does and does not implement, stated so a reviewer can tell the
difference without reading the code.

## Implemented

| Requirement | Status |
|-------------|--------|
| A proprietary domain-specific language, with its own grammar | IMPLEMENTED · LINUX VALIDATED |
| Lexer, parser, AST, semantic validation | IMPLEMENTED · LINUX VALIDATED |
| Variables, expressions, predicates, list values | IMPLEMENTED · LINUX VALIDATED |
| Reusable functions / playbooks (`DEFINE`/`RUN`) | IMPLEMENTED · LINUX VALIDATED |
| Conditional compilation (`WHEN`), resolved per platform | IMPLEMENTED · LINUX VALIDATED |
| Compiler to a platform-neutral IR, versioned and serializable | IMPLEMENTED · LINUX VALIDATED |
| IR → platform execution plan, via pluggable adapters | IMPLEMENTED (Linux) · WINDOWS READY / NOT VALIDATED |
| Deterministic, reproducible compilation | IMPLEMENTED · LINUX VALIDATED |
| Platform adaptation that is traceable and auditable | IMPLEMENTED · LINUX VALIDATED |
| Authorized forensic acquisition driven by the language | IMPLEMENTED · LINUX VALIDATED |
| Evidence model, hashing, chain of custody, audit trail | IMPLEMENTED · LINUX VALIDATED |
| Multi-endpoint architecture, enrollment, dispatch, retry | IMPLEMENTED · LINUX VALIDATED |
| Cross-source and cross-host correlation | IMPLEMENTED · LINUX VALIDATED |
| Reporting and evidence packaging | IMPLEMENTED · LINUX VALIDATED |
| Central investigator application | IMPLEMENTED · LINUX VALIDATED |

## Partial, or validated only in part

| Requirement | Status |
|-------------|--------|
| Windows forensic collection | WINDOWS READY / NOT VALIDATED — six sources mapped, fixture-tested, no real Windows host has run a plan |
| Windows application build and packaged runtime | LINUX VALIDATED equivalent exists; the Windows build and packaged runtime are checked on a CI runner |
| Real memory-image analysis | FIXTURE/SYNTHETIC — the workflow, registration, hashing and provenance are real; no genuine memory image has been analysed |
| Forensic container contents | PARTIALLY IMPLEMENTED — identified from header, hashed, registered and preserved; contents are not extracted |
| Physical multi-host validation | PARTIALLY IMPLEMENTED — the endpoint architecture is exercised, but the demo's endpoints are agents on one machine |

## Intentionally not implemented

These are in the problem statement. They are absent by decision, not by
omission, because this is a defensive tool for authorized investigation. No part
of the repository approximates them, and no claim in any document should be read
as implying otherwise.

| Capability | Status |
|------------|--------|
| Polymorphic payload generation | NOT IMPLEMENTED |
| Obfuscation for evasion | NOT IMPLEMENTED |
| In-memory execution, reflective loading | NOT IMPLEMENTED |
| Process injection | NOT IMPLEMENTED |
| API unhooking, direct syscalls | NOT IMPLEMENTED |
| BYOVD, driver loading or exploitation | NOT IMPLEMENTED |
| EDR/AV bypass or security-control disabling | NOT IMPLEMENTED |
| Persistence | NOT IMPLEMENTED |
| Credential theft | NOT IMPLEMENTED |
| Covert C2, domain fronting, stealth networking | NOT IMPLEMENTED |
| Remote shell or arbitrary remote command execution | NOT IMPLEMENTED |

Where the problem statement's *compiler* requirements are demonstrated, they are
demonstrated benignly: platform-neutral compilation, IR transformation, guard
resolution per platform, reproducible builds and deterministic output. An
enrolled endpoint receives a named forensic source request and nothing else;
there is no path in the language, the IR or the plan from a program to an
arbitrary execution. See [SecurityBoundaries.md](SecurityBoundaries.md) for
where each boundary is enforced.
