"""The merged timeline orders what was recorded and invents nothing."""
from analysis import timeline as timeline_module
from analysis.timeline import (
    ARTIFACT_OBSERVATION, COMMAND_HISTORY, EXECUTION_EVIDENCE, FINDING,
    INVESTIGATION_STATE, PROCESS_SNAPSHOT, SESSION_EVENT, build_timeline,
)


def execution(events):
    return {"events": events}


def event(stamp, name="tool", **extra):
    return {"timestamp": stamp, "process_name": name, "executable": f"/usr/bin/{name}",
            "source": "systemd journal", "event_id": f"journal:{name}:{stamp}",
            "evidence_kind": EXECUTION_EVIDENCE, "execution_confirmed": True,
            "classification": "HISTORICAL_EVIDENCE",
            "evidence_strength": "logged while running", **extra}


def test_entries_are_ordered_by_their_own_timestamps():
    result = build_timeline(execution=execution([
        event("2026-09-10T12:30:00+00:00", "late"),
        event("2026-09-10T09:00:00+00:00", "early"),
        event("2026-09-10T11:00:00+00:00", "middle"),
    ]))

    assert [entry["extra_name"] if False else entry["title"].rsplit("/", 1)[-1]
            for entry in result["entries"]] == ["early", "middle", "late"]
    assert result["undated_count"] == 0


def test_undated_records_are_kept_apart_not_given_a_time():
    result = build_timeline(execution=execution([
        event("2026-09-10T12:00:00+00:00", "dated"),
        event(None, "undated"),
    ]))

    assert result["entry_count"] == 1
    assert result["undated_count"] == 1
    assert result["undated_entries"][0]["timestamp"] is None
    assert "not the most recent activity" in result["note"]


def test_every_kind_is_distinguished():
    result = build_timeline(
        execution=execution([event("2026-09-10T12:00:00+00:00")]),
        artifacts={"artifacts": [{"path": "/tmp/x", "filename": "x", "modified": "2026-09-10T11:00:00+00:00",
                                  "collection_status": "COLLECTED", "source": "evidence", "hash": "a" * 64,
                                  "size_bytes": 1}]},
        processes={"action": "process_snapshot", "processes": [
            {"pid": 1, "name": "init", "started_at": "2026-09-10T08:00:00+00:00",
             "classification": "CURRENT_OBSERVATION"}]},
        findings=[{"title": "A finding", "explanation": "why", "severity": "medium",
                   "confidence": "single source; not corroborated", "category": "test",
                   "classification": "INFERRED", "timestamp": "2026-09-10T13:00:00+00:00",
                   "evidence_references": []}],
        transitions=[{"state": "created", "timestamp": "2026-09-10T07:00:00+00:00", "detail": None}],
    )

    assert set(result["kinds"]) == {EXECUTION_EVIDENCE, ARTIFACT_OBSERVATION, PROCESS_SNAPSHOT,
                                    FINDING, INVESTIGATION_STATE}
    assert result["statistics"]["by_kind"][EXECUTION_EVIDENCE] == 1


def test_a_file_time_is_labelled_as_metadata_not_a_witnessed_change():
    result = build_timeline(artifacts={"artifacts": [
        {"path": "/tmp/x", "filename": "x", "modified": "2026-09-10T11:00:00+00:00",
         "collection_status": "COLLECTED", "source": "evidence", "hash": None, "size_bytes": 1}]})

    entry = result["entries"][0]
    assert "not an observation of the change happening" in entry["detail"]


def test_current_processes_are_never_presented_as_history():
    result = build_timeline(processes={"action": "process_snapshot", "processes": [
        {"pid": 9, "name": "bash", "started_at": "2026-09-10T10:00:00+00:00",
         "classification": "CURRENT_OBSERVATION"}]})

    entry = result["entries"][0]
    assert entry["kind"] == PROCESS_SNAPSHOT
    assert entry["classification"] == "CURRENT_OBSERVATION"
    assert "not the past" in entry["detail"]


def test_missing_artifact_entry_is_classified_unavailable():
    result = build_timeline(artifacts={"artifacts": [
        {"path": "/tmp/gone", "filename": "gone", "modified": None, "collection_status": "MISSING",
         "source": "evidence", "hash": None, "size_bytes": None}]})

    assert result["undated_entries"][0]["classification"] == "UNAVAILABLE"


def test_timeline_is_bounded(monkeypatch):
    monkeypatch.setattr(timeline_module, "MAX_TIMELINE_ENTRIES", 3)
    events = [event(f"2026-09-10T12:{index:02d}:00+00:00", f"p{index}") for index in range(10)]

    result = build_timeline(execution=execution(events))

    assert result["truncated"] is True
    assert result["entry_count"] == 3
    # Truncation keeps the most recent, which is what an investigator reaches for.
    assert result["entries"][-1]["title"].endswith("p9")


def test_empty_inputs_produce_an_empty_timeline():
    result = build_timeline()

    assert result["entries"] == [] and result["undated_entries"] == []
    assert result["truncated"] is False
