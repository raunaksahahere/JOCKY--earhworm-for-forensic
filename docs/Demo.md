# The JOCKY demonstration

One command runs a complete investigation from a clean checkout:

```bash
cd application
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/demo.py --output demo-output
```

It takes roughly a minute on a laptop and writes an evidence package to
`demo-output/`. Nothing is written anywhere else; the demo's database lives in a
temporary directory that is removed at the end unless you pass `--keep`.

## What it runs

```
case
  -> investigation program (the JOCKY language)
  -> AST
  -> platform-neutral IR
  -> Linux execution plan
  -> authorized endpoints
  -> evidence
  -> normalization
  -> correlation
  -> activity threads
  -> timeline
  -> findings
  -> concise investigator report
  -> detailed evidence package
```

Thirteen steps, each printed as it completes.

| Step | What happens |
|------|--------------|
| 1 | A case is opened, with an examiner and a reference. |
| 2 | An investigation program is written in the JOCKY language. |
| 3 | The program is parsed to an AST. |
| 4 | The AST is compiled to platform-neutral IR. |
| 5 | The IR is compiled to an execution plan for this platform. |
| 6 | Two endpoints are authorized and enrolled. |
| 7 | The plan is dispatched to every endpoint and collected in parallel. |
| 8 | The same program runs against this workstation. |
| 9 | Normalization, correlation, threads, timeline and findings. |
| 10 | Cross-host correlation over the endpoint results. |
| 11 | The six synthetic lab scenarios. |
| 12 | The evidence package is written. |
| 13 | A statement of what the run did and did not establish. |

## Two kinds of evidence, never mixed

The endpoints collect from **this machine**, so steps 7 to 10 are real
observations of the computer you run the demo on. The scenarios in step 11 are
**synthetic**: every record carries `synthetic: true`, every event's source
begins with `SYNTHETIC`, and each scenario result carries a banner saying so.

A demonstration that quietly presented fabricated data as host evidence would
undermine the only thing a forensic tool has to offer. The two are kept apart
in the output directory as well: real evidence at the top level, synthetic
evidence under `synthetic-scenarios/`.

## The demo's own limitation

Both endpoints are agents running on the same machine. Every cross-host
observable is therefore trivially shared, and step 10 says so in its own
output. What step 10 demonstrates is the mechanism. **Scenario D** is the
multi-host case with genuinely separate evidence, and it is the one to read for
what cross-host correlation actually produces.

## What lands in `demo-output/`

| File | Contents |
|------|----------|
| `investigator-report.pdf` | The concise report an investigator reads. |
| `report.json` | The complete report payload, including every appendix. |
| `program.jocky` | The investigation program that drove the collection. |
| `ir.json` | The compiled platform-neutral IR. |
| `execution-plan.json` | The plan built for this platform. |
| `endpoint-tasks.json` | Every endpoint task with its result and result hash. |
| `cross-host-correlation.json` | Observables shared between endpoints. |
| `audit-trail.json` | What JOCKY and the examiner did, separate from evidence. |
| `synthetic-scenarios/scenario-*.json` | The six lab scenarios, fully labelled. |

`report.json` and `endpoint-tasks.json` are large — tens of megabytes on a
machine with real history. That is the detailed evidence package: it holds every
normalized event, not a summary of them. The PDF is the eight-page read.

## The six scenarios

Each is deterministic: fixed timestamps, fixed hashes, the same findings every
run. They can be run on their own:

```bash
.venv/bin/python -c "from scenarios import run_scenario; \
    r = run_scenario('A'); print(r['title'], r['highest_lead_priority'])"
```

| | Scenario | Expected outcome |
|--|----------|------------------|
| A | Suspicious execution from a hidden temporary directory | Priority 1 lead: confirmed execution from a user-writable path, with a hashed artifact at the same path |
| B | Data staged to removable media | Priority 1 finding plus an activity thread linking the archive, the copy and the device window |
| C | Downloaded script executed shortly after download | Cross-source finding linking browser, artifact and execution evidence |
| D | The same binary running on two hosts | Cross-host correlation on the shared file hash and the shared remote address |
| E | Memory image with a process whose parent is absent | Normalized memory evidence plus an orphan-process finding, both labelled as fixture-derived |
| F | A driver matching the known-abused reference is loaded | Explainable driver finding naming the rule that fired |

Scenario F deliberately borrows a real SHA-256 from the known-abused driver
reference so the match path is exercised. The driver itself does not exist.

## Options

| Flag | Effect |
|------|--------|
| `--output DIR` | Where the evidence package is written. Default `demo-output`. |
| `--endpoints N` | How many endpoints to enroll. Default 2. |
| `--keep` | Keep the demo database and print its path. |

## What the demo does not do

It does not touch the system database at `~/.local/share/jocky/`, install
anything, open a network port, or modify the machine it examines. The endpoints
it enrolls exist only for the length of the run.
