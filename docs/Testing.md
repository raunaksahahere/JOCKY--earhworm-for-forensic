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

## Flutter suites

`test/widget/` renders each screen against a scripted transport. The harness
replaces only the transport and the two stores; every controller, repository and
the API client itself run their real code, so the tests exercise the actual
request path rather than a stand-in.

`test/widget/case_file_test.dart` asserts that each panel states its own
boundary where an investigator will read it — that a source is never
overwritten, that no remote command is sent, that health means contact rather
than uptime, that the audit trail is not evidence about the host.

## What is not tested

**Windows.** The Windows collectors are fixture-tested. No Windows host has run
them. Nothing in the suite validates Windows behaviour.

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

## CI

`.github/workflows/ci.yml` runs the Python suite, `flutter analyze` and the
Flutter suite on every push and pull request, on native runners.
