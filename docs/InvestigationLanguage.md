# The JOCKY language

A domain-specific language for saying what a forensic investigation needs. It
describes evidence to collect, not steps to perform — there is no way to express
"run this", and that is the point.

JOCKY programs are `.x` files. Five worked examples live in [`examples/`](../examples),
and every one of them is compiled by the test suite, so an example that stops
working is a failing build rather than stale documentation.

## Why the language exists

A forensic tool that is only a GUI records what an investigator clicked. A
program records what they *asked*, in a form that can be reviewed before it
runs, stored beside the evidence, quoted in a report and executed again later
against a different host. The language is the artefact that makes an
investigation reproducible.

It is deliberately not general-purpose. It answers "what investigation do I want
to perform?", never "which command should I execute?". There is no statement
that names a path to execute, and nothing a platform adapter can turn into a
shell.

## A complete program

```
CASE "IR-2024-005" {
    TITLE "Portable triage across a mixed estate"
    EXAMINER "R. Saha"
}

TARGET "workstation-07"
WINDOW LAST 48 HOURS

LET download_tools = ["/usr/bin/curl", "/usr/bin/wget"]

DEFINE core_triage {
    COLLECT SYSTEM
    COLLECT PROCESSES
    COLLECT EXECUTION
}

RUN core_triage

WHEN PLATFORM IS linux {
    COLLECT USB
    CORRELATE EXECUTION WITH USB
}

COLLECT NETWORK

FILTER PATH ONEOF $download_tools AND NOT USER EQUALS "root"

TIMELINE SIGNIFICANT LIMIT 250
REPORT BOTH AS "IR-2024-005-portable"
```

One statement per line. Statements are newline-terminated, which is not
cosmetic: an earlier grammar ignored whitespace globally and names swallowed the
keyword that followed, so eighteen statements parsed as five.

Comments run from `#` to end of line.

## Statements

### CASE — required, first

```
CASE "identifier"
CASE "identifier" { TITLE "..." EXAMINER "..." REFERENCE "..." NOTES "..." }
```

### TARGET

```
TARGET "name"
TARGET "name" PLATFORM linux
```

A platform constraint is enforced when the plan is built: building a Windows
plan from a program whose target requires Linux is refused rather than silently
producing something that cannot run.

Targets are the dispatch dimension, not a loop. Naming three targets does not
run the program three times in the IR; it says which authorized endpoints the
one plan is dispatched to.

### WINDOW

```
WINDOW LAST 48 HOURS
WINDOW LAST 7 DAYS
```

Bounded at 90 days. Defaults to the collector's own default when absent.

### LET

```
LET threshold = 5
LET staging_dir = "/tmp"
LET download_tools = ["/usr/bin/curl", "/usr/bin/wget", "/usr/bin/scp"]
```

A binding is referenced as `$name`. Referencing an undefined variable is a
program error, not an empty string. Lists are used with `ONEOF`.

### DEFINE and RUN — reusable playbooks

```
DEFINE host_triage {
    COLLECT SYSTEM
    COLLECT PROCESSES
    COLLECT EXECUTION
}

RUN host_triage
```

A playbook is a named, reusable investigation step: one program says "run the
standard triage here" rather than repeating six collections, and a team can keep
a playbook under version control and cite it by name in a report. A playbook may
contain `COLLECT`, `FILTER`, `CORRELATE`, `WHEN` and `RUN`.

`RUN` expands the playbook where it appears, so its collections are real
collections in the IR — not a reference resolved later. A playbook must be
defined before it is run, may not be defined twice, and may not run itself
directly or transitively: a cycle is a named error rather than a hang. Nesting
is bounded at 8 deep.

### WHEN — conditional composition

```
WHEN PLATFORM IS linux {
    COLLECT USB
}

WHEN SOURCE BROWSER IS SUPPORTED {
    COLLECT BROWSER
}
```

A guard is **never resolved while parsing**. It travels into the IR and is
resolved by the platform adapter when a plan is built, which is what keeps the
IR platform-neutral: one program produces a different plan on each platform, and
each plan says which parts it left out and why.

A guarded step that does not apply becomes a `SKIPPED_CONDITION` task. That is
deliberately distinct from `UNSUPPORTED`: this build *could* have collected it,
and the program chose not to here. Guards nest, and a nested guard requires
every enclosing condition to hold.

The same `COLLECT` under two different guards is not a duplicate — that is how
one program serves two platforms.

### COLLECT — at least one required

```
COLLECT SYSTEM | PROCESSES | EXECUTION | NETWORK | BROWSER
      | USB | DRIVERS | FILES | MEMORY | SERVICES | LOGS
```

| Source | What it reads |
|--------|---------------|
| `SYSTEM` | Host identity and configuration |
| `PROCESSES` | Processes running at collection time |
| `EXECUTION` | Documented OS execution telemetry |
| `FILES` | Named files, and files the evidence references |
| `NETWORK` | Interfaces, routes, resolver, socket table |
| `BROWSER` | History and download records |
| `USB` | Removable device identity, attach events, mounts |
| `DRIVERS` | Loaded drivers, checked against a known-abused reference |
| `MEMORY` | A memory image the investigator supplies |
| `SERVICES` | Service units and scheduled jobs |
| `LOGS` | System journal |

Options: `LIMIT n`, `FROM "path"`, `DEPTH n`.

`COLLECT FILES` takes absolute paths. `COLLECT MEMORY` requires `FROM "<image>"`
— JOCKY analyses an image you supply; it does not acquire memory.

### FILTER — boolean predicates

```
FILTER COMMAND CONTAINS "curl"
FILTER PATH ONEOF $download_tools AND NOT USER EQUALS "root"
FILTER (PATH STARTS "/tmp" OR PATH ENDS ".sh") AND NOT USER EQUALS "root"
```

| | |
|---|---|
| Fields | `PATH` `COMMAND` `USER` `HOST` `SOURCE` `HASH` `PROCESS` `URL` `ADDRESS` `ENDPOINT` |
| Operators | `CONTAINS` `EQUALS` `MATCHES` `STARTS` `ENDS` `ONEOF` |
| Combinators | `AND` `OR` `NOT`, and parentheses |

`AND` binds tighter than `OR`, so `a OR b AND c` means `a OR (b AND c)`.

Investigations ask compound questions — "a download tool, run by someone other
than root, reaching a staging directory" — and a language that cannot say `AND`
forces that into three separate statements whose relationship to each other is
lost.

`ONEOF` takes a list; every other operator takes a single value, and mixing them
up is a program error rather than a filter that silently matches nothing. A
`MATCHES` pattern is compiled at validation time, anywhere in the expression, so
an invalid expression is a program error rather than a collection failure.

**A FILTER selects; it does not reduce evidence.** Evidence is registered and
hashed whole. Filters are answered against what was collected, after the fact,
by `GET /api/v1/investigations/<id>/selection` — no record is removed, rewritten
or re-hashed to produce a selection, and an empty selection means the evidence
does not answer the question, not that the evidence is gone.

Several `FILTER` statements narrow together: each is a further condition on the
same question.

### CORRELATE

```
CORRELATE EXECUTION WITH USB
CORRELATE PROCESSES WITH NETWORK
```

Subjects: `ARTIFACTS`, `EXECUTION`, `BROWSER`, `USB`, `NETWORK`, `MEMORY`,
`DRIVERS`, `PROCESSES`. Naming a subject the program never collects is refused —
a correlation that could not possibly run is a mistake, not a request.

### TIMELINE

```
TIMELINE SIGNIFICANT
TIMELINE FULL LIMIT 250
```

### REPORT

```
REPORT SUMMARY | EVIDENCE | BOTH
REPORT BOTH AS "IR-2024-005-portable"
```

Defaults to `REPORT SUMMARY` when absent.

## What a program is refused for

| Program | Refusal |
|---------|---------|
| No `CASE` | A program must open with a CASE statement |
| No `COLLECT` | A program must request at least one collection |
| The same collection twice under the same conditions | requested more than once |
| `COLLECT FILES "relative/path"` | must be absolute |
| `CORRELATE` naming an uncollected subject | which this program does not request |
| `FILTER ... MATCHES "["` | not a valid expression |
| `FILTER PATH ONEOF "single"` | needs a list of values |
| `FILTER PATH EQUALS ["a","b"]` | takes a single value; use ONEOF |
| `$undefined` | Undefined variable |
| `RUN` of an undefined playbook | which this program does not DEFINE |
| A playbook that runs itself | runs itself, directly or through … |
| `DEFINE` of the same name twice | is defined more than once |
| `COLLECT MEMORY` with no `FROM` | requires FROM &lt;image path&gt; |
| `WINDOW LAST 9000 DAYS` | beyond the maximum window |

Bounds: 64 targets, 32 collections, 32 filters, 90 days, 8 levels of playbook
nesting.

## Compilation

```
.x text -> AST -> semantic validation -> IR (version 2) -> plan (version 2)
        -> forensic execution -> evidence -> analysis -> report
```

The IR is platform-neutral, versioned and round-trip serializable: the same
program always emits the same bytes. It names *what* the investigation needs,
never how an operating system provides it. Deciding how to collect processes on
a given OS belongs to the adapter in `compiler/plan.py`.

IR version 2 added playbooks, conditions, predicate trees, list values and named
reports. Filters and reports changed shape, so a version-1 IR is refused rather
than misread.

The plan is one platform's answer: named collectors and bounded options, never a
command. `backend/plan_runner.py` holds the complete registry of what a plan can
cause to happen, and a plan task's collector path is *checked against* that
registry rather than imported from it — resolving it dynamically would turn the
language into an arbitrary-code loader.

A source the platform cannot provide becomes a named `UNSUPPORTED` task rather
than an error — an investigator is better served by a plan that runs what it can
and says plainly what it could not.

## Checking a program without collecting

```
POST /api/v1/programs/compile
{"program": "...", "platform": "windows"}
```

Returns the IR, the plan, and a prose description of both. Building a Windows
plan is how you see what would and would not be collected there; the description
says `NOT VALIDATED ON A REAL HOST`, because it has not been.

## In the application

**JOCKY Language** in the client is the `.x` editor: write a program, compile
it, read the IR and the execution plan the compiler produced, then run it. The
client never parses or validates a program itself — every result comes back from
the engine's compiler, which is the same one a collection runs through, so the
editor cannot tell an investigator that a program is valid when a collection
would refuse it.

Selecting sources in the rest of the client is compiled into a program too, and
stored in `investigation_programs` with its IR, plan and every component
version. A collection driven from the UI is exactly as reproducible as one
driven from the language, because it is the same pipeline.
