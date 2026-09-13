"""Clearing command history removes ad-hoc records and never evidence."""
import json
import time

import pytest

from backend.api import create_app
from backend.paths import Paths
from backend.service import Workstation
from backend.storage import Store
from backend.workstation_view import clear_history, view


@pytest.fixture
def store(tmp_path):
    return Store(Paths.resolve(str(tmp_path / "workspace")))


@pytest.fixture
def service(store):
    workstation = Workstation(store)
    yield workstation
    workstation.close()


def wait(service, case_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if service.get_case(case_id)["status"] in {"completed", "partially_completed", "failed"}:
            service.queue.join()
            return
        time.sleep(0.05)
    raise AssertionError("collection did not finish")


@pytest.fixture
def populated(service, tmp_path):
    """One ad-hoc command plus one investigation that collected evidence."""
    evidence = tmp_path / "sample.bin"
    evidence.write_bytes(b"abc")
    service.command(f'HASH FILE "{evidence}"')
    service.command("SYSTEM INFO")
    case = service.create_case({"title": "Kept investigation"})
    service.command("SYSTEM INFO", case["id"])
    service.collect(case["id"], {"paths": [str(evidence)]})
    wait(service, case["id"])
    return case["id"]


def test_every_execution_is_deleted(service, populated):
    assert view(service)["executions"], "the fixture must produce history"

    result = clear_history(service)

    assert result["deleted"] >= 4, "ad-hoc commands and collection steps alike"
    assert view(service)["executions"] == [], "the History screen must come back empty"
    assert result["retained"] == 0


def test_investigation_collection_steps_are_removed_too(service, populated):
    steps = {execution["command"] for execution in service.related(populated, "executions")}
    assert {"SYSTEM INFO", "PROCESSES"} <= steps

    clear_history(service)

    assert service.related(populated, "executions") == []


def test_the_evidence_itself_survives(service, populated):
    """Clearing the job log must not cascade into the forensic record."""
    before = {
        "evidence": len(service.related(populated, "evidence")),
        "findings": len(service.related(populated, "findings")),
        "artifacts": len(service.related(populated, "artifact_observations")),
        "events": len(service.related(populated, "execution_events")),
        "timeline": len(service.related(populated, "timeline_events")),
    }
    assert before["evidence"] and before["events"]

    clear_history(service)

    assert len(service.related(populated, "evidence")) == before["evidence"]
    assert len(service.related(populated, "findings")) == before["findings"]
    assert len(service.related(populated, "artifact_observations")) == before["artifacts"]
    assert len(service.related(populated, "execution_events")) == before["events"]
    assert len(service.related(populated, "timeline_events")) == before["timeline"]


def test_the_investigation_report_still_exists_and_still_renders(service, populated):
    """The collection report survives; per-command reports go with their runs."""
    from backend.pdf_report import render_pdf
    before = service.related(populated, "reports")
    collection_reports = [row for row in before if row["execution_id"] is None]
    assert collection_reports, "the fixture must have produced a collection report"

    clear_history(service)

    after = service.related(populated, "reports")
    assert [row["id"] for row in after] == [row["id"] for row in collection_reports]
    assert len(after) < len(before), "a report issued for a cleared command goes with it"
    # The investigation can still be exported after its job log was cleared.
    assert render_pdf(after[-1]["payload"]).startswith(b"%PDF-")


def test_evidence_is_detached_rather_than_orphaned(service, populated):
    clear_history(service)

    for record in service.related(populated, "evidence"):
        assert record["execution_id"] is None, "no evidence row may point at a deleted execution"
        # The observation keeps its own provenance.
        assert record["type"] and record["source"] and record["collected_at"]


def test_what_was_preserved_is_reported(service, populated):
    result = clear_history(service)

    assert result["preserved"]["evidence"] > 0
    assert result["preserved"]["investigation_reports"] > 0
    assert "Only the execution log was removed" in result["preserved_reason"]


def test_integrity_ledger_survives_with_its_link_cleared(service, populated, store):
    before = store.rows("SELECT id,path,digest FROM hash_observations")
    assert before

    clear_history(service)

    after = store.rows("SELECT id,path,digest,execution_id FROM hash_observations")
    assert len(after) == len(before), "digest history is evidence across investigations"
    assert {row["digest"] for row in after} == {row["digest"] for row in before}
    assert all(row["execution_id"] is None for row in after)


def test_the_clearance_is_itself_recorded(service, populated, store):
    clear_history(service)
    clear_history(service)

    recorded = json.loads(store.rows(
        "SELECT value FROM metadata WHERE key='history_clearances'")[0]["value"])
    assert len(recorded) == 2, "each clearance is appended, not overwritten"
    assert recorded[0]["deleted"] >= 4 and recorded[1]["deleted"] == 0
    assert all(entry["timestamp"] for entry in recorded)
    assert recorded[0]["preserved"]["evidence"] > 0


def test_clearing_an_empty_history_is_harmless(service):
    result = clear_history(service)

    assert result["deleted"] == 0 and result["retained"] == 0


def test_endpoint_clears_and_returns_the_refreshed_workstation(service, populated):
    app = create_app(service, "token", "instance")
    headers = {"Authorization": "Bearer token", "X-Jocky-Instance": "instance"}

    response = app.test_client().post("/api/v1/history/clear", json={}, headers=headers)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["deleted"] >= 4
    # The caller gets the authoritative state back, so the client never has to
    # guess what survived.
    remaining = {execution["id"] for execution in payload["workstation"]["executions"]}
    assert remaining == {execution["id"] for execution in view(service)["executions"]}


def test_saving_case_metadata_still_cannot_delete_executions(service, populated):
    """The original defect: the client could not clear history by saving records."""
    from backend.workstation_view import save_metadata
    before = len(view(service)["executions"])

    result = save_metadata(service, {"investigations": [], "active_case_id": None})

    assert len(result["executions"]) == before
