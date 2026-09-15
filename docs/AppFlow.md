# App flow

What happens, in order, from opening the application to holding a report.

## Starting

1. The client launches the engine as a child process.
2. The engine binds an OS-assigned loopback port, mints a per-process token and
   instance id, and announces them as one NDJSON line on stdout.
3. The client reads that line and holds the session. Every request afterwards
   carries the bearer token and `X-Jocky-Instance`.
4. The client polls `/health`. Until the bootstrap line arrives there is no
   session, so the client shows that the engine is starting rather than
   reporting a connection error against a port nothing is listening on.

## Opening a case

**Case File → Cases → New case.** A case holds the collections, evidence sources
and notes belonging to one enquiry. An investigation without a case still works
exactly as before; the case is optional structure, not a gate.

## Registering evidence

**Case File → Evidence sources → Register source.** Give an absolute path. JOCKY
reads the file to compute its SHA-256 and records who registered it, when, and
under what collector version. It does not write to the file, move it or rename
it.

Register the same bytes again and you get a second row naming what it
supersedes. Verify later and a changed file is reported as `MISMATCH` with the
original digest kept.

## Collecting from this machine

**Device → Analyze This Device.**

1. Title, optional investigator, history window.
2. Optionally add file or directory paths — at most 20, files to 128 MiB. There
   is no whole-disk scan.
3. Optionally choose additional sources. The list comes from the engine, so the
   client can never offer a collector the engine does not have.
4. Command-line collection is off by default. Turning it on masks values
   matching common credential patterns before storage — a mitigation, not a
   guarantee, and the form says so.

Behind that button:

```
source selection -> investigation program -> AST -> IR -> execution plan
                 -> baseline collection -> program sources -> analysis
```

The program, IR, plan and every component version are stored, so the collection
can be reproduced.

Collection runs on one bounded worker. Each source is its own step: an
unavailable source becomes a named gap in the report, not a failed collection.
Cancellation is honoured between steps.

## Collecting from another machine

1. **Case File → Endpoints → Authorize endpoint.** Name the machine and record
   the authority — warrant, ticket, written consent. Required.
2. Copy the enrollment token. It is shown once.
3. On the endpoint: `jocky-endpoint --control-plane <url> --name <name>
   --enroll <token>`.
4. The agent heartbeats and polls. Dispatch a program and every endpoint gets
   every task, so they collect in parallel.

The agent is sent source names, never commands. A source it cannot collect comes
back as a stated refusal.

## Reading the result

The report opens on what deserves attention:

1. **Summary** — what was collected, from where, over what window.
2. **Leads** — Priority 1 and 2 activity, with repetitions of one pattern shown
   once. Each cites its evidence identifiers and a next step.
3. **Threads** — activities linked by shared rare tokens and adjacency.
4. **Significant events** — the timeline, condensed.
5. **Findings** — each with the evidence it rests on, how strongly it is
   supported, and what it cannot establish.
6. **Limitations** — what could not be read, and why.

Every record is one click from the summary; nothing is hidden. The appendices
and the database hold everything.

## Exporting

The **Investigation artifacts** panel shows what can be produced and how large
each one is *before* producing it — the page counts come from the engine, which
renders the documents to answer.

| | Question it answers | Typical |
|--|--------------------|---------|
| Investigator report | What do I need to know? | 8 pages |
| Review brief | Tell me about this one thing. | 1–2 pages |
| Evidence package | Show me everything. | everything collected |
| Routine activity report | Optional, for the record | 4 pages |
| Full report | Rarely wanted; grows with the evidence | 71 pages |

The investigator report is the default. The long document with every appendix is
still available and still unchanged — it is offered last, described as what it
is. Encrypted export requires an explicit passphrase.

## Clearing history

**History → Clear.** Every execution row is removed. Evidence, findings,
artifacts and reports survive, with their execution links nulled — clearing the
command log must not destroy the investigation it produced.
