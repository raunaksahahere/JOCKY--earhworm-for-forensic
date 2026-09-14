"""Performance and reliability bounds.

These are not benchmarks. Each one guards a property that has already broken
once, or that would degrade silently: an algorithm that is quadratic in the
number of events, a collector with no ceiling, or a pipeline that loses evidence
when one stage fails.

The timings are deliberately loose. They are there to catch a return to
quadratic behaviour on a slow CI machine, not to measure milliseconds.
"""
import time

import pytest

from analysis.activity import assign_references, build_activity
from analysis.correlation import correlate
from analysis.execution_model import HISTORICAL_EVIDENCE, STRONG, build_event
from analysis.threads import build_threads
from analysis.timeline import build_timeline


def events(count, *, distinct=True):
    built = []
    for index in range(count):
        command = f"/usr/bin/tool-{index if distinct else 0} --flag value-{index}"
        built.append(build_event(
            source="fixture", source_record_id=str(index),
            timestamp=f"2026-03-14T{index // 3600 % 24:02d}:{index // 60 % 60:02d}:{index % 60:02d}+00:00",
            classification=HISTORICAL_EVIDENCE, evidence_strength=STRONG, provenance="test",
            execution_confirmed=True,
            observed={"process_name": f"tool-{index}", "executable": f"/usr/bin/tool-{index}",
                      "full_command_line": command, "command_line": command, "pid": 1000 + index}))
    return built


@pytest.mark.parametrize("count", [500, 2000])
def test_activity_grouping_stays_roughly_linear(count):
    records = events(count)
    assign_references(records, artifacts=[])
    started = time.monotonic()
    activity = build_activity(records, artifacts=[])
    elapsed = time.monotonic() - started
    assert len(activity["groups"]) == count
    assert elapsed < 10, f"grouping {count} events took {elapsed:.1f}s"


def test_thread_building_does_not_go_quadratic():
    """Thread building once stalled collection past the smoke-test timeout.

    The fix was an inverted index over rare tokens. This is the guard against
    that regression: doubling the input must not multiply the time by four.
    """
    def build(count):
        records = events(count)
        assign_references(records, artifacts=[])
        groups = build_activity(records, artifacts=[])["groups"]
        started = time.monotonic()
        threads = build_threads(groups)
        return time.monotonic() - started, threads

    small, _ = build(500)
    large, threads = build(2000)
    assert large < 5, f"threading 2000 activities took {large:.1f}s"
    # Four times the input on a quadratic algorithm is sixteen times the work.
    assert large < max(small, 0.01) * 12, (
        f"threading scaled {large / max(small, 0.001):.1f}x for 4x the input")
    assert isinstance(threads, list)


def test_a_thread_never_grows_without_bound():
    """Identical commands must not merge into one enormous thread."""
    from analysis.threads import MAX_THREAD_MEMBERS

    records = events(400, distinct=False)
    assign_references(records, artifacts=[])
    groups = build_activity(records, artifacts=[])["groups"]
    for thread in build_threads(groups):
        assert len(thread["members"]) <= MAX_THREAD_MEMBERS


def test_correlation_and_timeline_handle_a_large_collection():
    records = events(2000)
    assign_references(records, artifacts=[])
    started = time.monotonic()
    correlation = correlate(execution={"events": records}, artifacts={"artifacts": []},
                            processes={})
    timeline = build_timeline(execution={"events": records}, artifacts={"artifacts": []},
                              processes={}, findings=correlation["findings"], transitions=[])
    elapsed = time.monotonic() - started
    assert elapsed < 20, f"correlation and timeline took {elapsed:.1f}s"
    assert len(timeline) >= 1


@pytest.mark.parametrize("module, attribute, ceiling", [
    ("analysis.network", "MAX_CONNECTIONS", 10000),
    ("analysis.usb", "MAX_DEVICES", 10000),
    ("analysis.drivers", "MAX_MODULES", 10000),
    ("analysis.memory", "MAX_PROCESSES", 100000),
    ("analysis.browser", "MAX_RECORDS_PER_PROFILE", 100000),
    ("analysis.system_services", "MAX_UNITS", 10000),
])
def test_every_collector_has_a_ceiling(module, attribute, ceiling):
    """An unbounded collector turns a busy host into an unfinished collection."""
    import importlib

    limit = getattr(importlib.import_module(module), attribute)
    assert 0 < limit <= ceiling


def test_one_failing_collector_does_not_lose_the_others(tmp_path, monkeypatch):
    """A collection is a sequence of independent steps, by design."""
    import time as clock

    from backend.paths import Paths
    from backend.service import Workstation
    from backend.storage import Store
    from backend import plan_runner

    def explode(**_kwargs):
        raise RuntimeError("this collector is broken")

    monkeypatch.setitem(plan_runner.REGISTRY, "NETWORK",
                        (explode, "analysis.network.collect_network", "NETWORK"))
    working = {"status": "success", "classification": "CURRENT_OBSERVATION", "complete": True}
    monkeypatch.setitem(plan_runner.REGISTRY, "USB",
                        (lambda **_kwargs: working,
                         "analysis.usb.collect_removable_media", "USB"))
    service = Workstation(Store(Paths.resolve(str(tmp_path / "workspace"))))
    try:
        case = service.create_case({"title": "partial"})
        service.collect(case["id"], {"paths": [], "sources": ["NETWORK", "USB"]})
        deadline = clock.monotonic() + 120
        while clock.monotonic() < deadline:
            current = service.get_case(case["id"])
            if current["status"] in ("completed", "partially_completed", "failed", "cancelled"):
                break
            clock.sleep(0.5)
        assert current["status"] == "partially_completed", (
            "a broken collector must degrade the collection, not fail it")
        collected = {record["type"] for record in service.related(case["id"], "evidence")}
        assert "USB" in collected, "the working collector's evidence must survive"
        assert "NETWORK" in collected, "the failure itself must be recorded as evidence"
    finally:
        service.close()
