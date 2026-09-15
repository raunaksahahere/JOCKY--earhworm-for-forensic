# Architecture

## Shape

```
Flutter desktop client  (Linux, Windows-ready)
        |  loopback HTTP, per-process token
        v
Flask API  (backend/api.py)
        |
        +-- Workstation service  (backend/service.py)     collection lifecycle
        +-- Casework             (backend/casework.py)    cases, evidence, audit
        +-- Fleet                (backend/fleet.py)       authorized endpoints
        |
        v
   Store  (backend/storage.py)   SQLite, WAL, explicit forward migrations
```

Off to the side, and deliberately not in that chain:

```
compiler/   language -> AST -> IR -> execution plan
analysis/   collectors, normalization, recognition, correlation, detection,
            briefs, search, case summary
endpoint/   the agent that runs on another authorized machine
scenarios/  synthetic lab data
```

## The layering that matters

**`analysis/` knows nothing about storage, HTTP or cases.** Every module there
takes evidence and returns evidence. That is what makes the synthetic scenarios
honest: they push fabricated data through exactly the same functions a real
collection uses, with no special path.

**`compiler/` knows nothing about collectors.** It produces a plan naming a
source and bounded options. `backend/plan_runner.py` is the only place that maps
a source to a callable, and it does so through a fixed registry.

**`backend/` owns persistence and lifecycle.** It is the only layer that writes.

## The compilation chain

```
program text
   -> parse()       AST, a plain dictionary
   -> validate()    refuses what cannot be collected or correlated
   -> to_ir()       IR_VERSION 1: platform-neutral, versioned, serializable
   -> build_plan()  one platform's answer: named collectors, bounded options
   -> plan_runner   fixed registry: the complete list of what can happen
```

Each stage is a pure function of the previous one, which is what lets the same
IR produce a Linux plan today and a Windows plan later without the program, the
grammar or the IR changing.

A plan carries no command. `plan_runner` checks a task's collector path against
the registry rather than importing it, so a program can never load code JOCKY
did not choose to expose. See `docs/SecurityBoundaries.md`.

## Two collection paths, one pipeline

**Local.** `Workstation._collect` runs the baseline — system, processes,
execution history, and the files that evidence names — then the program's
additional sources. The baseline is not optional: the report is built from it,
so a program can add evidence but never leave the report without its foundation.

**Endpoint.** An agent has no baseline. It receives whatever the plan names,
including the core sources, and returns structured collector output. Cross-host
correlation runs over those results.

Both produce the same collector-shaped dictionaries, so normalization,
correlation, threads, timeline and findings are identical either way.

## Storage

SQLite with WAL, `synchronous=FULL`, and `PRAGMA user_version` driving explicit
forward migrations. Six migrations to date; each has a forward migration, a
regression test, and — for 5 and 6 — a test that migrates a real schema-4
database and asserts every execution event survives.

Nothing is ever destructively rewritten. An evidence source is superseded, not
replaced. A mismatched digest is recorded, not corrected. A failed collection
step is stored as evidence of the failure.

## The path off SQLite

SQLite is the right answer for a workstation examining one machine: no server,
no configuration, and a single file an investigator can hand to someone else.
It becomes the wrong answer when many endpoints write concurrently to one
control plane.

The transition does not require rewriting the application, because the layers
that would have to change are already separate:

| Layer | Where | Changes? |
|-------|-------|----------|
| Domain models | `analysis/`, plain dictionaries and dataclasses | No |
| Repositories | `Casework`, `Fleet`, `Workstation` | No — they hold a `Store` |
| Storage | `backend/storage.py` | Yes — this is the whole change |

Every SQL statement in the product lives in the three service classes and
`storage.py`. They reach the database through `store.rows(...)` and
`store.transaction()`, and nothing else in the codebase opens a connection.

What a move to PostgreSQL would involve:

1. Implement `Store`'s interface — `rows`, `transaction`, migration application
   — against the new driver. The migration list is already a versioned sequence
   of DDL statements.
2. Replace `PRAGMA user_version` with a schema-version table.
3. Replace `INTEGER PRIMARY KEY` rowid columns with an explicit sequence. Every
   other column type is portable as written.
4. Take advantage of real concurrency in `Fleet.claim_tasks`, which is currently
   a transaction precisely because SQLite serializes writers.

What would *not* change: the analysis pipeline, the compiler, the API surface,
the report, the client.

**This is now checked rather than asserted.** `tests/test_storage_abstraction.py`
fails if the analysis layer reaches for JOCKY's store, if a service uses anything
outside the three-method `Store` interface, or if SQL appears in a module that
did not have it before. It also runs the casework and fleet layers against a
substitute store that records every call, which is the proof rather than the
argument.

One documented exception: `analysis/browser.py` opens SQLite to read a browser's
own history database as evidence, having copied it aside first. That is evidence
collection, not storage, and a rule conflating the two would force the collector
to be rewritten during a database migration for no reason.

This is documented rather than built. Rewriting working storage without a
workload that needs it is churn, and the abstraction that makes the rewrite
cheap already exists.

## Versioning

| | |
|--|--|
| Application | 0.8.1 |
| API | 1 |
| Report schema | 5 |
| Database schema | 7 |
| IR | 1 |
| Plan | 1 |
| Detection ruleset | 1 |
| Recognition | 1 |
| Brief format | 1 |
| Evidence package | 1 |

Every report records the versions of everything that produced it, and
`investigation_programs` records the program, IR, plan and versions for each
collection, so a result can be traced to the exact code that produced it.

## Process model

The client supervises the engine as a child process. The engine binds an
OS-assigned loopback port and mints a per-process token and instance id,
announced over an NDJSON bootstrap channel on stdout. Every route, `/health`
included, requires both. A dead session is never adopted by a replacement
process.

Collection runs on a single bounded worker thread with a queue of eight.
Cancellation is checked between steps, never mid-write.
