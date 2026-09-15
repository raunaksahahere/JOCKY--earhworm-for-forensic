# Tracker

State of the work as of application version 0.9.0, database schema 7, IR 2, plan 2.

## Done

| Area | Status |
|------|--------|
| JOCKY `.x` language: grammar, parser, semantics, IR, plan | Done, Linux validated |
| Playbooks (`DEFINE`/`RUN`) with cycle and depth detection | Done, Linux validated |
| Conditional composition (`WHEN`), resolved by the platform adapter | Done, Linux validated |
| Boolean predicates: `AND`/`OR`/`NOT`/parentheses, list values, `ONEOF` | Done, Linux validated |
| Named reports | Done, Linux validated |
| `FILTER` answered against collected evidence as a selection | Done, Linux validated |
| Five worked `.x` examples, all compiled by the test suite | Done |
| JOCKY `.x` editor in the client, using the engine's compiler | Done, Linux validated |
| Network, browser, USB, driver, services collectors | Done, Linux validated |
| Memory analysis | Done, fixture-validated only |
| Explainable detections (6 rules) | Done |
| Cases, evidence sources, audit trail, notes | Done, Linux validated |
| Schema migrations 5 and 6 | Done, verified against the real database |
| Authorized multi-endpoint control plane | Done, Linux validated |
| Endpoint agent | Done, Linux validated |
| Cross-source correlation | Done |
| Cross-host correlation | Done, **real multi-host validated** on two containers |
| Reproducibility record | Done |
| Synthetic scenarios A–F | Done |
| End-to-end demo | Done |
| Case file screen, source picker | Done |
| Software recognition | Done, Linux validated |
| Routine / recognized presentation | Done, Linux validated |
| Review briefs (artifact, finding, activity, lead, thread) | Done |
| Routine activity report | Done |
| Investigator search across every surface | Done |
| Investigator assessments | Done |
| Case summary with narrative traceability | Done |
| Self-describing evidence package | Done |
| Memory workflow: register, hash, verify, analyse, link | Done; analysis fixture-only |
| Forensic container identification | Done (identification only) |
| Storage abstraction proof | Done, 11 tests |
| Investigator report split from its evidence | Done — 71 pages to 8, nothing removed |
| Selective thread reporting with a full tally | Done |
| Evidence package laid out by source, both PDFs included | Done |
| Windows application build and packaged runtime | Done, validated on Windows Server 2025 |
| Windows release published | Done for **0.8.1** — portable archive and installer, digest verified after download. 0.9.0 has not been built or run on Windows. |
| Test suites | 969 Python (4 skipped), 181 Flutter, analyzer clean |
| Documentation set | Done |
| Linux `.deb` release | Done |

## Open

| Item | Why it is open | What it needs |
|------|----------------|---------------|
| **Windows forensic collection** | The build and packaged runtime are validated on a Windows runner; the collectors are fixture-tested only | A real investigated Windows host with Sysmon and 4688 auditing, compared against Event Viewer |
| **Windows adapter coverage** | Four of six selectable sources have no Windows collector: BROWSER, USB, DRIVERS, SERVICES | Collectors written and validated per source |
| **Windows recognition** | Recognition reads a package database and a snap directory, neither of which exists on Windows, so it accounts for nothing there and the routine category does almost no work | Reading the installed-programs registry, validated against a host |
| **Python suite on Windows** | 17 tests assume POSIX paths, permissions or `/proc`; they predate this pass and fail on `windows-latest` | Per-test platform handling, once there is a Windows host to validate against |
| **Real memory image** | None was available; the workflow around it is complete, the analysis path is fixture-only | A lab image and Volatility3 installed |
| **Forensic container extraction** | Deliberately out of scope; containers are identified, hashed and preserved | An integration with ewfmount or equivalent, if it turns out to be wanted |
| **Two physical machines** | Multi-host is validated on two containers, which share the host kernel | Two separate kernels, for kernel-level evidence |
| **Move off SQLite** | Not needed yet | A workload with concurrent endpoint writes. Path documented in `docs/Architecture.md`. |
| **Wider detection ruleset** | Deliberately six, all explainable | More rules that can each state their evidence and confidence |

## Bugs the Windows runner found

Running the suite on a real Windows runner found four defects that were wrong
everywhere and only visible there.

| Bug | Where | Consequence |
|-----|-------|-------------|
| An `fstat` result compared against a `stat` result | `analysis/hashing.py` | Every file looked as though it had changed under the reader; no digest could be recorded on Windows at all |
| Evidence paths normalized with the analysing host's path rules | `analysis/correlation.py` | `os.path.abspath("/usr/bin/curl")` on Windows invents a drive; every execution-to-artifact join from a Linux endpoint was silently lost |
| An artifact recorded the locally-resolved path, not the evidence's | `analysis/artifacts.py` | Same join, one layer down |
| The missing-engine diagnostic probed paths unguarded | `backend_supervisor.dart` | An unreachable share made the explanation itself throw, replacing "here is where I looked" with a filesystem error |
| A native path embedded in a generated CMake script | `flutter_client/windows/CMakeLists.txt` | Backslashes are escapes there; the install step failed and took the whole Windows build with it |

## Bugs the Windows runner found

All five were invisible on Linux, and three were real product defects rather
than test problems.

| Bug | Where | Effect on Windows |
|-----|-------|-------------------|
| The identity check compared an `os.fstat` result against an `os.stat` one; Windows reports the same file differently through a handle and a path | `analysis/hashing.py` | **Every** file refused with "File changed during hashing" — no digest could be recorded at all |
| Evidence paths normalized with the analysing host's rules: `os.path.abspath("/usr/bin/curl")` becomes `D:\usr\bin\curl` | `analysis/correlation.py`, `analysis/artifacts.py` | Correlation lost every join, so no artifact-to-execution finding was produced |
| The ancestor walk joined a filesystem root to a segment, producing `C:\\backend-dist\...` — a UNC path | `backend_supervisor.dart` | The engine search went to the network, timed out and threw, abandoning the candidates after it |
| `flutter --version --machine` parsed with its first-run progress output | `windows.yml` | The workflow failed before installing anything |
| MSBuild reports a failing install step as its batch wrapper and Flutter swallows CMake's message | `packaging/windows/build.ps1` | A build failure with no stated cause |

## Bugs found and fixed in the 0.8.1 pass

| Bug | Where | How it was found |
|-----|-------|------------------|
| PDF assertions searched the raw file, so four tests claiming "the report says X" passed against a report that said no such thing (subset CID fonts over ASCII85-then-Flate streams) | `tests/` | Writing the packaging tests |
| A package test altered `findings.json`, which had moved to `evidence/`, so it asserted that an *unaltered* package fails verification | `tests/test_multihost.py` | Running the suite after the package layout changed |
| The smoke test imported `backend` while deliberately running outside the source tree | `scripts/smoke_backend.py` | Running it against the frozen engine |
| `recognition_version` and the collection-period fields were null in the manifest | `backend/service.py`, `backend/evidence_package.py` | Reading the generated manifest |

## Bugs found and fixed in the 0.8.0 pass

| Bug | Where | How it was found |
|-----|-------|------------------|
| A configurable snap root that matching ignored, so the option silently did nothing | `analysis/recognition.py` | Writing the tests |
| Investigations never stored their `case_id` — migration 5 added the column and nothing wrote it, so every collection looked unattached | `backend/service.py` | Building the evidence package manifest |
| Findings in the report payload carried no evidence references; the rows were stored separately and never joined back | `backend/service.py` | Building finding briefs |
| The Linux adapter offered a `LOGS` source with no collector behind it | `compiler/plan.py` | The CI boundary check |
| Widget assertions matched the screen's raw-JSON debug dump rather than the list an investigator reads | Flutter tests | Writing the recognition tests |

## Bugs found and fixed in the 0.7.0 pass

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

## Release policy

A `v*` tag builds and publishes the **Linux** package only. The Windows job is
run deliberately from the Actions tab, because publishing an installer no
Windows host has ever run would contradict every claim in
`docs/RequirementMatrix.md`.
