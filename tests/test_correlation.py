"""Correlation produces findings that name their evidence and claim no more."""
import pytest

from analysis.correlation import HIGH, INFO, LOW, MEDIUM, correlate
from analysis.execution_model import AVAILABLE, NOT_ENABLED, PERMISSION_DENIED, source_record


def execution(events=(), sources=None, **extra):
    sources = sources if sources is not None else [
        source_record("systemd journal", AVAILABLE, detail="ok", event_count=len(events))]
    return {"events": list(events), "sources": sources,
            "telemetry_available": any(s["status"] == AVAILABLE for s in sources), **extra}


def event(executable, source="systemd journal", event_id=None):
    return {"executable": executable, "source": source,
            "event_id": event_id or f"{source}:{executable}", "timestamp": "2026-09-10T12:00:00+00:00"}


def artifact(path, **overrides):
    record = {"path": path, "filename": path.rsplit("/", 1)[-1], "collection_status": "COLLECTED",
              "hash": "a" * 64, "hash_algorithm": "SHA256", "indicators": [], "integrity": None,
              "integrity_history": None, "previous_hash": None, "notable_location": None}
    record.update(overrides)
    return record


def categories(result):
    return {finding["category"] for finding in result["findings"]}


def test_missing_executable_produces_a_qualified_finding():
    result = correlate(
        execution=execution([event("/usr/bin/removed")]),
        artifacts={"artifacts": [artifact("/usr/bin/removed", collection_status="MISSING", hash=None)]})

    finding = next(f for f in result["findings"] if f["category"] == "execution_artifact_missing")
    assert finding["severity"] == MEDIUM
    assert "package upgrade" in finding["explanation"], "alternatives must be stated, not just suspicion"
    assert {reference["kind"] for reference in finding["evidence_references"]} == {"execution_event", "artifact"}


def test_unusual_location_is_a_reason_to_look_not_a_verdict():
    result = correlate(
        execution=execution([event("/tmp/stage")]),
        artifacts={"artifacts": [artifact("/tmp/stage", notable_location="tmp")]})

    finding = next(f for f in result["findings"] if f["category"] == "unusual_execution_location")
    assert "not a conclusion about it" in finding["explanation"]
    assert "malware" not in finding["explanation"].lower()


def test_present_artifact_corroborates_without_claiming_the_bytes_that_ran():
    result = correlate(
        execution=execution([event("/usr/bin/curl")]),
        artifacts={"artifacts": [artifact("/usr/bin/curl")]})

    finding = next(f for f in result["findings"] if f["category"] == "execution_artifact_matched")
    assert finding["severity"] == INFO
    assert "does not prove these are the bytes that ran" in finding["explanation"]


def test_two_sources_naming_one_image_are_reported_as_corroborated():
    result = correlate(
        execution=execution([event("/usr/bin/curl"), event("/usr/bin/curl", source="kernel audit log")]),
        artifacts={"artifacts": [artifact("/usr/bin/curl")]})

    finding = next(f for f in result["findings"] if f["category"] == "execution_artifact_matched")
    assert "corroborated by more than one source" == finding["confidence"]


def test_single_source_is_labelled_as_uncorroborated():
    result = correlate(
        execution=execution([event("/usr/bin/removed")]),
        artifacts={"artifacts": [artifact("/usr/bin/removed", collection_status="MISSING", hash=None)]})

    finding = next(f for f in result["findings"] if f["category"] == "execution_artifact_missing")
    assert finding["confidence"] == "single source; not corroborated"


def test_hash_change_is_reported_without_assigning_a_cause():
    result = correlate(execution=execution(), artifacts={"artifacts": [
        artifact("/usr/bin/tool", integrity_history={"status": "altered"},
                 previous_hash={"hash": "b" * 64})]})

    finding = next(f for f in result["findings"] if f["category"] == "artifact_hash_changed")
    assert finding["severity"] == HIGH
    assert "Routine updates produce the same result as tampering" in finding["explanation"]


def test_filename_indicators_become_findings_traceable_to_the_file():
    result = correlate(execution=execution(), artifacts={"artifacts": [
        artifact("/home/a/invoice.pdf.exe", indicators=[
            {"level": "warning", "label": "Possible extension spoofing", "detail": "Looks spoofed."}])]})

    finding = next(f for f in result["findings"] if f["category"] == "suspicious_filename")
    assert finding["severity"] == MEDIUM
    assert finding["evidence_references"][0]["id"] == "/home/a/invoice.pdf.exe"
    assert "not a statement about the file's behaviour" in finding["explanation"]


@pytest.mark.parametrize("status,severity", [
    (NOT_ENABLED, LOW), (PERMISSION_DENIED, MEDIUM)])
def test_unavailable_telemetry_is_itself_a_finding(status, severity):
    result = correlate(execution=execution(sources=[
        source_record("systemd journal", AVAILABLE, detail="ok"),
        source_record("kernel audit log", status, detail="not readable")]))

    finding = next(f for f in result["findings"] if f["category"] == "telemetry_unavailable")
    assert finding["severity"] == severity
    assert finding["classification"] == "UNAVAILABLE"
    assert "outside the evidence available" in finding["explanation"]


def test_no_telemetry_at_all_is_a_high_severity_gap():
    result = correlate(execution=execution(sources=[
        source_record("systemd journal", NOT_ENABLED, detail="off")]))

    finding = next(f for f in result["findings"] if f["category"] == "no_historical_telemetry")
    assert finding["severity"] == HIGH
    assert "cannot establish what ran before collection started" in finding["explanation"]


def test_truncation_and_undated_records_are_reported():
    result = correlate(
        execution=execution(truncated=True, undated_event_count=4, limits={"max_total_events": 10}),
        artifacts={"truncated": True, "artifacts": [], "limits": {"max_artifacts": 2},
                   "statistics": {"by_collection_status": {"PERMISSION_DENIED": 3}}},
        processes={"truncated": True, "limits": {"max_processes": 5}})

    assert "collection_truncated" in categories(result)
    assert "undated_evidence" in categories(result)
    assert "permission_gap" in categories(result)
    truncations = [f for f in result["findings"] if f["category"] == "collection_truncated"]
    assert len(truncations) == 3, "execution, artifact and process bounds are each reported"


def test_clean_collection_produces_no_invented_findings():
    result = correlate(execution=execution(), artifacts={"artifacts": []}, processes={})

    assert result["findings"] == []
    assert result["statistics"]["findings_by_severity"] == {}


def test_every_finding_names_its_evidence():
    result = correlate(
        execution=execution([event("/tmp/stage")], sources=[
            source_record("systemd journal", AVAILABLE, detail="ok"),
            source_record("kernel audit log", NOT_ENABLED, detail="off")]),
        artifacts={"artifacts": [artifact("/tmp/stage", notable_location="tmp")]})

    assert result["findings"]
    for finding in result["findings"]:
        assert finding["evidence_references"], finding["title"]
        assert finding["confidence"] and finding["classification"]


def test_links_record_which_events_had_an_artifact():
    result = correlate(
        execution=execution([event("/usr/bin/curl"), event("/usr/bin/gone")]),
        artifacts={"artifacts": [artifact("/usr/bin/curl"),
                                 artifact("/usr/bin/gone", collection_status="MISSING", hash=None)]})

    assert result["statistics"]["execution_events_with_artifact"] == 1
    assert result["statistics"]["execution_events_without_artifact"] == 1
