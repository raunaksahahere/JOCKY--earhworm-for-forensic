# Product requirements

The current statement of what JOCKY is for and what it must do. The original
command-language PRD is at `../PRD.md` and remains accurate for that layer; this
supersedes it in scope.

## Problem

An investigator asked "what happened on this machine" has to gather evidence
from a dozen places, normalize it by hand, decide what matters, and write it up
in a form someone else can check. The gathering is tedious, the normalization is
where mistakes enter, and the write-up is where a tired person overstates what
the evidence supports.

Existing tools solve one of those. The ones that gather well tend to hand back a
pile of data. The ones that analyse well tend to state conclusions without
showing their working.

## What JOCKY does

Collects documented operating-system telemetry and artefacts, normalizes it into
one evidence vocabulary, correlates across sources and across hosts, ranks what
deserves attention, and produces a report that states its own limits as plainly
as its findings.

## Users

- **Investigators** examining a workstation, on their own or someone else's
  machine with authorization.
- **Student and competition teams** who need a credible, defensible workflow.
- **Reviewers** who need to check whether a conclusion is supported.

The third user is the one that shapes the design. Everything the tool asserts
must be traceable to the record it rests on.

## Goals

1. **Collect what the OS already recorded**, without changing the machine.
2. **Normalize into one vocabulary** that distinguishes historical evidence from
   present observation from inference from absence.
3. **Correlate** across sources on one host and across hosts in one case.
4. **Rank**, so the first page is worth reading on a machine with 1,700 events.
5. **Explain**, so every finding names its evidence, its rule and its confidence.
6. **State the gaps** with the same prominence as the findings.
7. **Be reproducible** — the program, IR, plan and every version are stored.
8. **Stay strictly defensive.**

## Non-goals

- Not an EDR, antivirus or endpoint-protection product.
- Not a remote administration tool. There is no remote shell, and an endpoint
  cannot be sent a command.
- Not a malware verdict engine. Indicators are reasons to look, never verdicts.
- No offensive or evasive technique, for any stated purpose including
  "detection" or "simulation". See `docs/SecurityBoundaries.md`.
- No live memory acquisition. JOCKY analyses an image you supply.
- No packet capture.
- No credential collection.

## Functional requirements

| # | Requirement | Status |
|---|-------------|--------|
| R1 | Investigation language: parse, validate, compile to versioned IR | Implemented |
| R2 | Execution plan per platform; unsupported sources named, not silently skipped | Implemented (Linux); Windows not validated |
| R3 | Collect system, processes, execution telemetry and named files | Implemented |
| R4 | Collect network metadata, browser history, removable media, drivers, services | Implemented |
| R5 | Analyse an investigator-supplied memory image, read-only | Implemented; fixture-validated only |
| R6 | Normalize all of it into one evidence vocabulary with per-field provenance | Implemented |
| R7 | Correlate execution with artefacts, downloads with execution, media with activity | Implemented |
| R8 | Group into activities, link into threads, build a timeline | Implemented |
| R9 | Rank by deterministic weighted signal score into three priority tiers | Implemented |
| R10 | Explainable detections citing the rule that fired | Implemented |
| R11 | Register, hash and verify evidence sources without ever overwriting one | Implemented |
| R12 | Audit trail of what JOCKY and the investigator did, separate from evidence | Implemented |
| R13 | Cases holding investigations, evidence sources and notes | Implemented |
| R14 | Authorized multi-endpoint collection with enrollment, retry and revocation | Implemented |
| R15 | Cross-host correlation over endpoint results | Implemented; validated only degenerately |
| R16 | Store the program, IR, plan and versions for every collection | Implemented |
| R17 | Concise investigator report plus a complete evidence package | Implemented |
| R18 | Deterministic synthetic scenarios, labelled throughout | Implemented |
| R19 | Reproducible end-to-end demo from a clean checkout | Implemented |
| R20 | Self-contained Linux package | Implemented |
| R21 | Windows package | Configured; never built on Windows |

## Non-functional requirements

| | |
|--|--|
| **Local-first** | Loopback only, per-process token; no cloud, no telemetry |
| **Bounded** | Every collector declares a ceiling; every window is capped |
| **Degrading** | One failing collector produces a partial collection, never a failed one |
| **Durable** | WAL, `synchronous=FULL`, explicit forward migrations, nothing destructively rewritten |
| **Reproducible** | Same program, same platform, same versions, same result |
| **Honest** | Nothing is described as validated that has not been run |

## Success

An investigator can open a case, collect from one or several authorized
machines, read an eight-page report that opens on what deserves attention, trace
any statement in it to the record it rests on, and hand the whole thing to
someone who will check it.
