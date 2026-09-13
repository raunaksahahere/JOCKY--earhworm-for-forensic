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


def test_ad_hoc_history_is_deleted(service, populated):
    before = len(view(service)["executions"])

    result = clear_history(service)

    assert result["deleted"] >= 2, "the two Command Center runs must go"
    assert len(view(service)["executions"]) == before - result["deleted"]


def test_investigation_evidence_is_never_deleted(service, populated):
    clear_history(service)

    executions = service.related(populated, "executions")
    assert executions, "an investigation's executions are evidence and must survive"
    assert service.related(populated, "evidence")
    assert service.related(populated, "findings")
    assert service.related(populated, "reports")
    for record in service.related(populated, "evidence"):
        assert record["execution_id"] is None or any(
            execution["id"] == record["execution_id"] for execution in executions), \
            "no evidence row may be left pointing at a deleted execution"


def test_retained_count_and_reason_are_reported(service, populated):
    result = clear_history(service)

    assert result["retained"] >= 1
    assert "forensic records and were kept" in result["retained_reason"]


def test_integrity_ledger_survives_with_its_link_cleared(service, populated, store):
    before = store.rows("SELECT id,path,digest FROM hash_observations")
    assert before

    clear_history(service)

    after = store.rows("SELECT id,path,digest,execution_id FROM hash_observations")
    assert len(after) == len(before), "digest history is evidence across investigations"
    assert {row["digest"] for row in after} == {row["digest"] for row in before}


def test_the_clearance_is_itself_recorded(service, populated, store):
    clear_history(service)
    clear_history(service)

    recorded = json.loads(store.rows(
        "SELECT value FROM metadata WHERE key='history_clearances'")[0]["value"])
    assert len(recorded) == 2, "each clearance is appended, not overwritten"
    assert recorded[0]["deleted"] >= 2 and recorded[1]["deleted"] == 0
    assert all(entry["timestamp"] for entry in recorded)


def test_clearing_an_empty_history_is_harmless(service):
    result = clear_history(service)

    assert result["deleted"] == 0 and result["retained"] == 0


def test_endpoint_clears_and_returns_the_refreshed_workstation(service, populated):
    app = create_app(service, "token", "instance")
    headers = {"Authorization": "Bearer token", "X-Jocky-Instance": "instance"}

    response = app.test_client().post("/api/v1/history/clear", json={}, headers=headers)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["deleted"] >= 2
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
