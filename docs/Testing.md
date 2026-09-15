# Testing

```bash
cd application
.venv/bin/python -m pytest -q                # 804 tests
cd flutter_client && flutter test            # 158 tests
flutter analyze
```

## What the suites are for

The point of these tests is not coverage. It is that a forensic tool's claims
have to be checkable, so the tests assert the claims: that an evidence source is
never overwritten, that an endpoint cannot be sent a command, that a browser
profile is byte-identical after a collection, that a fixture-derived finding is
labelled as one.

## Python suites

| File | What it holds |
|------|---------------|
| `test_investigation_language.py` | Grammar, validation, IR round-trip, plan building |
| `test_plan_execution.py` | The registry boundary, the agent, detections, scenarios |
| `test_collectors_extended.py` | The six collectors and the limits they declare |
| `test_casework.py` | Cases, evidence sources, audit, notes |
| `test_casework_api.py` | The HTTP surface and its authentication boundaries |
| `test_fleet.py` | Authorization, credentials, task queue, retry, health |
| `test_cross_source.py` | Cross-source and cross-host correlation |
| `test_schema_migration.py` | Every migration, including a real v4 database |
| `test_performance.py` | Scaling, ceilings, and degradation under failure |
| `test_recognition.py` | Each recognition layer, and the negative cases that matter most |
| `test_briefs.py` | Briefs, routine grouping, search and the case summary |
| `test_multihost.py` | Real two-container validation, memory workflow, evidence package |
| `test_assessments.py` | Investigator judgement stored beside the machine's, never over it |
| `test_storage_abstraction.py` | The boundary the scale-out path depends on |
| `test_report_packaging.py` | That the report stays short and the evidence stays complete |
| `test_correlation.py`, `test_triage.py`, `test_threads.py`, `test_timeline.py` | The analysis pipeline |
| `test_execution_history.py`, `test_execution_windows.py` | Telemetry collection |
| `test_reports.py`, `test_report_presentation.py` | Report construction and rendering |

## Determinism

`tests/conftest.py` replaces historical-execution collection with a fixture for
every test that does not explicitly opt in with `@pytest.mark.real_telemetry`.
Reading the live journal would make assertions depend on the machine and would
make each collection test as slow as a real forensic collection.

The synthetic scenarios use fixed timestamps and fixed hashes, so the same
scenario produces the same findings every run and a test can assert on them
exactly.

## Guards worth knowing about

**Quadratic threading.** `test_thread_building_does_not_go_quadratic` builds
threads for 500 and 2000 activities and asserts the time did not scale with the
square. This once stalled collection past the smoke-test timeout; the fix was an
inverted index over rare tokens.

**Collector ceilings.** Every collector must declare a bound. An unbounded
collector turns a busy host into an unfinished collection.

**Degradation.** `test_one_failing_collector_does_not_lose_the_others` breaks a
collector and asserts the collection reaches `partially_completed` with the
working collector's evidence intact and the failure itself recorded as evidence.

**Migration regression.** `test_upgrading_from_v4_preserves_every_execution_event`
builds a schema-4 database with real rows, migrates it, and counts. Migration 5
and 6 were also each run against the actual development database (1,849 and
5,322 execution events preserved).

**No command route.** `test_there_is_no_route_that_runs_a_command_on_an_endpoint`
walks the URL map and fails if any endpoint route name contains command, exec,
shell, run or script.

**Report length against evidence volume.**
`test_evidence_volume_does_not_change_the_report_length` renders the same
narrative over 20 activities and over 700, and fails if the page count moves by
more than two. The claim "the report is short because there is little to say"
has to be checkable, or it is just a shorter report.

**Nothing lost in the split.** `test_no_record_is_lost_between_the_report_and_the_package`
counts activities, command-history records, artifacts, findings, threads and
processes on both sides of the export, and a second test compares the individual
evidence references rather than only the totals.

**PDF text, actually read.** `backend.pdf_report.extract_text` decodes the
ASCII85-then-Flate streams and maps subset-CID glyph codes back through the
document's own ToUnicode table. Without it, an assertion that the report *says*
something passes against a report that says no such thing — four of the first
seven such assertions were passing for exactly that reason.

## Flutter suites

`test/widget/` renders each screen against a scripted transport. The harness
replaces only the transport and the two stores; every controller, repository and
the API client itself run their real code, so the tests exercise the actual
request path rather than a stand-in.

`test/widget/case_file_test.dart` asserts that each panel states its own
boundary where an investigator will read it — that a source is never
overwritten, that no remote command is sent, that health means contact rather
than uptime, that the audit trail is not evidence about the host.

## Windows

The suite runs on `windows-latest` in `.github/workflows/windows.yml`. Tests
that exercise POSIX file mechanics rather than JOCKY's behaviour — mode bits,
effective uid, birth time — skip themselves there with a stated reason, so the
skip count is visible rather than hidden behind a deselection flag that could
also swallow a real Windows failure.

`packaging/windows/smoke_packaged.ps1` drives the **final packaged artifact**:
the unpacked archive and, separately, the silently installed copy. It checks the
bundle carries its own interpreter and every data file read at import time,
starts the engine over the bootstrap channel, refuses an unauthenticated
request, runs a read-only collection, renders the report, and shuts down
cleanly.

## What is not tested

**Windows forensic collection.** The build and the packaged runtime are
validated; the collectors are not. `analysis/execution_windows.py` is
fixture-tested against documented event formats, and no output has been compared
with a real Windows host's telemetry. See `docs/WindowsValidation.md`.

**Real memory images.** The workflow around an image — registration, hashing,
re-verification before analysis, provenance, findings linkage — is fully tested.
The Volatility3-driving path itself has never seen a real image.

**Two physical machines.** Multi-host is validated on two Docker containers with
genuinely separate filesystems, hostnames and process tables — the validation
proves that separation before it asserts anything else, and runs as a test. But
containers share the host kernel, so kernel-level evidence is not covered, and
the validation deliberately asserts nothing that depends on it.

**Forensic container extraction.** Containers are identified from their headers
and preserved. Nothing extracts one, by design.

## The two validations that are not unit tests

```bash
python3 validation/multihost.py      # two separate Linux environments
bash validation/clean_install.sh     # the built .deb on a clean Ubuntu
```

**`validation/multihost.py`** starts two containers and proves they are
genuinely separate before it asserts anything else — distinct hostnames,
distinct process tables both beginning at pid 1, and a file planted on one host
demonstrably absent on the other. It then plants one file on both and one on
only one, and checks the shared digest correlates naming both endpoints while
the unique one does not correlate at all. It runs in the Python suite and in
CI, and skips honestly where Docker is absent rather than passing.

**`validation/clean_install.sh`** installs the built `.deb` into an
`ubuntu:24.04` container with no Python, no build tools and no source tree,
checks the interpreter and all four data files landed, then drives the installed
engine over its own bootstrap channel: health, an unauthenticated request
refused, a real collection with program-selected sources, the investigator
report, the routine report, a review brief and the evidence package. It runs in
the release workflow, where there is a package to install.

A package that runs on the machine that built it has proved nothing.

## CI

`.github/workflows/ci.yml` runs five jobs on every push and pull request:

| Job | What it guards |
|-----|----------------|
| `backend` | The Python suite and the packaged-engine smoke test |
| `demo` | The whole chain end to end, and that every synthetic record is labelled |
| `client` | `flutter analyze` and the Flutter suite |
| `multihost` | Real two-host correlation, and that the non-match does not correlate |
| `boundaries` | Registry-bound collectors, no command column, no execution path in the agent |

`release.yml` additionally installs the built `.deb` in a clean container and
uses it there before anything is published.
