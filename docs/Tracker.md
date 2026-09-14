# Tracker

State of the work as of application version 0.7.0, database schema 6.

## Done

| Area | Status |
|------|--------|
| Investigation language, IR, execution plan | Done, Linux validated |
| Network, browser, USB, driver, services collectors | Done, Linux validated |
| Memory analysis | Done, fixture-validated only |
| Explainable detections (6 rules) | Done |
| Cases, evidence sources, audit trail, notes | Done, Linux validated |
| Schema migrations 5 and 6 | Done, verified against the real database |
| Authorized multi-endpoint control plane | Done, Linux validated |
| Endpoint agent | Done, Linux validated |
| Cross-source correlation | Done |
| Cross-host correlation | Done, validated only degenerately |
| Reproducibility record | Done |
| Synthetic scenarios A–F | Done |
| End-to-end demo | Done |
| Case file screen, source picker | Done |
| Test suites | 708 Python, 151 Flutter |
| Documentation set | Done |
| Linux `.deb` release | Done |

## Open

| Item | Why it is open | What it needs |
|------|----------------|---------------|
| **Windows validation** | No Windows host has run any of it | A Windows machine. No amount of code closes this. |
| **Real memory image** | None was available | A lab image and Volatility3 |
| **Genuine multi-host fleet** | Both demo endpoints are one machine | Two separate machines |
| **Move off SQLite** | Not needed yet | A workload with concurrent endpoint writes. Path documented in `docs/Architecture.md`. |
| **Wider detection ruleset** | Deliberately six, all explainable | More rules that can each state their evidence and confidence |

## Bugs found and fixed in this pass

| Bug | Where | How it was found |
|-----|-------|------------------|
| Driver detections read `result`, collector writes `risk_status` | `analysis/detections.py` | Writing the tests |
| Same key wrong in cross-host comparison | `analysis/fleet_correlation.py` | Writing the tests |
| Memory detections read raw tool columns, not normalized keys | `analysis/detections.py` | Writing the tests |
| `ImageFileName` unrecognised — every Windows-image process nameless | `analysis/memory.py` | Writing the tests |
| Parent pid 0 turned into `None`, losing kernel roots | `analysis/memory.py` | Writing the tests |
| Endpoints could not collect the core sources | `backend/plan_runner.py` | Running the demo |
| Agent claimed one batch and stopped | `endpoint/agent.py` | Running the demo |
| USB root hubs paired by PCI address | `analysis/fleet_correlation.py` | Running the demo |
| Downloads paired by bare filename | `analysis/fleet_correlation.py` | Running the demo |
| Grammar: names swallowed the following keyword | `compiler/investigation.lark` | Writing the parser |

## Known limitations that are not bugs

- **Cross-host correlation on two endpoints is degenerate.** With two hosts,
  every shared observable is "on all of them". The suppression rule that hides
  fleet-wide drivers only earns its keep on a real fleet.
- **Command-line redaction is a mitigation, not a guarantee.** It masks values
  matching common credential patterns. Collection is off by default for that
  reason.
- **A filename match against the driver reference is weak evidence** and is
  reported as such. Only a hash match is high confidence.
- **`stale` means JOCKY has not heard from an endpoint**, not that the machine
  is off. The API and the UI both say so.
