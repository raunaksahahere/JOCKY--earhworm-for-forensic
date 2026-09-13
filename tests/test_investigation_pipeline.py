"""Analyze This Device end to end: history, artifacts, correlation, report, restart."""
from backend.versions import REPORT_SCHEMA_VERSION
import time

import pytest

from backend.api import create_app
from backend.pdf_report import render_pdf
from backend.service import ServiceError, Workstation
from backend.storage import Store


@pytest.fixture
def store(tmp_path):
    from backend.paths import Paths
    paths = Paths.resolve(str(tmp_path / "workspace"))
    return Store(paths)


@pytest.fixture
def service(store):
    workstation = Workstation(store)
    yield workstation
    workstation.close()


def wait(service, case_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        case = service.get_case(case_id)
        if case["status"] in {"completed", "partially_completed", "failed", "cancelled", "interrupted"}:
            service.queue.join()
            return case
        time.sleep(0.05)
    raise AssertionError(f"collection did not finish: {service.get_case(case_id)}")


@pytest.fixture
def investigated(service, tmp_path):
    evidence = tmp_path / "invoice.pdf.exe"
    evidence.write_bytes(b"fixture bytes")
    case = service.create_case({"title": "Device analysis", "examiner": "Investigator"})
    service.collect(case["id"], {"paths": [str(evidence)], "window_hours": 168})
    assert wait(service, case["id"])["status"] in {"completed", "partially_completed"}
    return case["id"]


def test_execution_events_are_persisted_with_provenance(service, investigated):
    events = service.related(investigated, "execution_events")

    assert events, "historical execution evidence must be stored, not only reported"
    sshd = next(event for event in events if event["executable"] == "/usr/sbin/sshd")
    assert sshd["source"] == "systemd journal"
    assert sshd["classification"] == "HISTORICAL_EVIDENCE"
    assert sshd["source_record_id"] and sshd["timestamp"]
    assert sshd["payload"]["evidence_strength"]


def test_artifacts_named_by_evidence_are_observed(service, investigated):
    artifacts = service.related(investigated, "artifact_observations")

    paths = {record["path"]: record for record in artifacts}
    # The fixture journal names an image under /tmp and one that does not exist.
    assert any(record["collection_status"] == "MISSING" for record in artifacts)
    selected = next(record for record in artifacts if record["filename"] == "invoice.pdf.exe")
    assert selected["hash"] and selected["collection_status"] == "COLLECTED"
    assert selected["source"] == "investigator-selected path"
    assert "/usr/bin/removed-tool" in paths


def test_findings_are_generated_and_traceable(service, investigated):
    findings = service.related(investigated, "findings")
    links = service.related(investigated, "finding_evidence")

    categories = {finding["category"] for finding in findings}
    assert "execution_artifact_missing" in categories
    assert "suspicious_filename" in categories, "the double-extension fixture must be flagged"
    limitations = {item["category"] for item in service.related(investigated, "collection_limitations")}
    assert "telemetry_unavailable" in limitations, "a disabled source is a limitation, not a finding"
    assert "telemetry_unavailable" not in categories
    assert all(finding["confidence"] for finding in findings)
    assert links and all(link["kind"] and link["reference"] for link in links)
    referenced = {link["finding_id"] for link in links}
    assert referenced <= {finding["id"] for finding in findings}


def test_timeline_is_persisted_and_ordered(service, investigated):
    entries = service.related(investigated, "timeline_events")

    assert entries
    stamps = [entry["timestamp"] for entry in entries if entry["timestamp"]]
    assert stamps == sorted(stamps)
    assert {"EXECUTION_EVIDENCE", "FINDING"} <= {entry["kind"] for entry in entries}


def test_report_separates_current_from_historical(service, investigated):
    report = service.related(investigated, "reports")[-1]["payload"]

    assert report["schema_version"] == REPORT_SCHEMA_VERSION
    assert report["historical_execution"]["telemetry_available"] is True
    assert report["collection_window"]["bounded"] is True
    assert report["current_process_snapshot"]["statistics"]["processes_recorded"] > 0
    assert report["appendix_process_listing"], "the raw listing moves to the appendix, it is not dropped"
    assert report["unavailable_telemetry"], "sources that were off must be named"
    assert any("does not establish historical execution" in limitation
               for limitation in report["limitations"])


def test_report_summary_states_the_basis_of_the_investigation(service, investigated):
    report = service.related(investigated, "reports")[-1]["payload"]

    assert "Historical execution evidence was collected from" in report["summary"]
    assert "systemd journal" in report["summary"]


def test_pdf_renders_the_new_sections(service, investigated):
    report = service.related(investigated, "reports")[-1]["payload"]

    pdf = render_pdf(report)

    assert pdf.startswith(b"%PDF-") and len(pdf) > 5000


def test_everything_survives_a_restart(service, store, investigated):
    before = {name: service.related(investigated, name)
              for name in ("execution_events", "artifact_observations", "timeline_events", "findings")}
    service.close()

    restarted = Workstation(Store(store.paths))
    try:
        for name, rows in before.items():
            assert restarted.related(investigated, name) == rows, name
        assert restarted.get_case(investigated)["status"] in {"completed", "partially_completed"}
    finally:
        restarted.close()


def test_new_collections_are_reachable_through_the_api(service, investigated):
    app = create_app(service, "token", "instance")
    client = app.test_client()
    headers = {"Authorization": "Bearer token", "X-Jocky-Instance": "instance"}

    for alias in ("execution-events", "artifacts", "event-timeline", "finding-evidence",
                  "collection-limitations"):
        response = client.get(f"/api/v1/investigations/{investigated}/{alias}", headers=headers)
        assert response.status_code == 200, alias
        assert isinstance(response.get_json()["items"], list)

    unknown = client.get(f"/api/v1/investigations/{investigated}/sqlite_master", headers=headers)
    assert unknown.status_code == 400


def test_capabilities_advertise_historical_collection(service):
    app = create_app(service, "token", "instance")
    payload = app.test_client().get("/api/v1/capabilities", headers={
        "Authorization": "Bearer token", "X-Jocky-Instance": "instance"}).get_json()

    assert payload["historical_execution_telemetry"] is True
    assert payload["historical_execution_sources"]
    assert payload["collection_window_default_hours"] == 168
    assert "never enables a disabled source" in payload["historical_execution_availability"]


@pytest.mark.parametrize("body,message", [
    ({"window_hours": 0}, "greater than zero"),
    ({"window_hours": 99999}, "must not exceed"),
    ({"window_hours": "soon"}, "number of hours"),
    ({"max_processes": 0}, "between 1"),
    ({"max_processes": "many"}, "must be an integer"),
    ({"include_command_lines": "yes"}, "true or false"),
])
def test_collection_options_are_validated(service, body, message):
    case = service.create_case({})

    with pytest.raises(ServiceError, match=message):
        service.collect(case["id"], body)


def test_bounded_options_are_honoured(service):
    case = service.create_case({})
    service.collect(case["id"], {"max_processes": 5, "window_hours": 1})
    wait(service, case["id"])

    report = service.related(case["id"], "reports")[-1]["payload"]
    snapshot = report["current_process_snapshot"]
    assert snapshot["limits"]["max_processes"] == 5
    assert snapshot["statistics"]["processes_recorded"] <= 5
    assert any("truncated" in limitation for limitation in report["limitations"])
