# The JOCKY investigation language

A small declarative language for saying what an investigation needs. It
describes evidence to collect, not steps to perform — there is no way to express
"run this", and that is the point.

## A complete program

```
CASE "Suspected data staging on the lab workstation"
TARGET "workstation-1" PLATFORM linux
WINDOW LAST 48 HOURS

COLLECT PROCESSES
COLLECT EXECUTION
COLLECT NETWORK
COLLECT USB
COLLECT BROWSER
COLLECT FILES "/etc/passwd"
COLLECT MEMORY FROM "/evidence/image.raw"

FILTER COMMAND CONTAINS "curl"
CORRELATE EXECUTION WITH USB
TIMELINE FULL
REPORT SUMMARY
```

One statement per line. Statements are newline-terminated, which is not
cosmetic: an earlier grammar ignored whitespace globally and names swallowed the
keyword that followed, so eighteen statements parsed as five.

## Statements

### CASE — required, first

```
CASE "title"
```

### TARGET

```
TARGET "name"
TARGET "name" PLATFORM linux
```

A platform constraint is enforced when the plan is built: building a Windows
plan from a program whose target requires Linux is refused rather than silently
producing something that cannot run.

### WINDOW

```
WINDOW LAST 48 HOURS
WINDOW LAST 7 DAYS
```

Bounded at 90 days. Defaults to the collector's own default when absent.

### LET

```
LET threshold = 5
```

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

`COLLECT FILES` takes absolute paths. `COLLECT MEMORY` requires `FROM "<image>"`
— JOCKY analyses an image you supply; it does not acquire memory.

### FILTER

```
FILTER PATH | COMMAND | USER | HOST | SOURCE | HASH
       CONTAINS | EQUALS | MATCHES | STARTS  "value"
```

A `MATCHES` pattern is compiled at validation time, so an invalid expression is
a program error rather than a collection failure.

### CORRELATE

```
CORRELATE EXECUTION WITH USB
```

Subjects: `ARTIFACTS`, `EXECUTION`, `BROWSER`, `USB`, `NETWORK`. Naming a
subject the program never collects is refused — a correlation that could not
possibly run is a mistake, not a request.

### TIMELINE

```
TIMELINE SIGNIFICANT
TIMELINE FULL
```

### REPORT

```
REPORT SUMMARY | EVIDENCE | BOTH
```

## What a program is refused for

| Program | Refusal |
|---------|---------|
| No `CASE` | A program must open with a CASE statement |
| No `COLLECT` | A program must request at least one collection |
| The same collection twice | requested more than once |
| `COLLECT FILES "relative/path"` | must be absolute |
| `CORRELATE` naming an uncollected subject | which this program does not request |
| `FILTER ... MATCHES "["` | not a valid expression |
| `COLLECT MEMORY` with no `FROM` | requires FROM &lt;image path&gt; |
| `WINDOW LAST 9000 DAYS` | beyond the maximum window |

Bounds: 64 targets, 32 collections, 32 filters, 90 days.

## Compilation

```
text -> AST -> validation -> IR (version 1) -> plan (version 1)
```

The IR is platform-neutral, versioned and round-trip serializable. The plan is
one platform's answer: named collectors and bounded options, never a command.

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

## The UI writes programs too

Selecting sources in the client is compiled into a program, stored in
`investigation_programs` with its IR, plan and every component version, and
executed the same way. A collection driven from the UI is exactly as
reproducible as one driven from the language.
