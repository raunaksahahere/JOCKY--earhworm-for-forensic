"""Authorized multi-endpoint collection.

The security properties are the point of these tests: authorization precedes
enrollment, credentials never leave the server, a task never carries a command,
and an endpoint refuses anything its own registry does not recognise.
"""
import json

import pytest

from backend.casework import Casework, CaseworkError
from backend.fleet import ABANDONED, QUEUED, REVOKED, SUCCEEDED, Fleet
from backend.paths import Paths
from backend.storage import Store
from compiler.investigation import compile_program
from compiler.plan import build_plan

PROGRAM = 'CASE "c"\nTARGET "host"\nCOLLECT NETWORK\nCOLLECT USB\nREPORT SUMMARY\n'


@pytest.fixture
def fleet(tmp_path):
    store = Store(Paths.resolve(str(tmp_path / "workspace")))
    return Fleet(store, Casework(store))


@pytest.fixture
def enrolled(fleet):
    issued = fleet.issue_enrollment_token({
        "endpoint_name": "lab-1", "authorization_reference": "WARRANT-2026/11"})
    identity = fleet.enroll({"enrollment_token": issued["enrollment_token"],
                             "endpoint_name": "lab-1", "platform": "Linux",
                             "capabilities": ["NETWORK", "USB"]})
    return fleet, identity


@pytest.fixture
def plan():
    return build_plan(compile_program(PROGRAM), platform_name="linux")


# --- authorization ------------------------------------------------------------
def test_authorization_requires_a_stated_authority(fleet):
    """Collecting from another machine should carry a record of who permitted it."""
    with pytest.raises(CaseworkError) as error:
        fleet.issue_enrollment_token({"endpoint_name": "lab-1"})
    assert "authorization_reference" in str(error.value)


def test_an_enrollment_token_is_single_use(enrolled):
    fleet, _identity = enrolled
    issued = fleet.issue_enrollment_token({"endpoint_name": "lab-2",
                                           "authorization_reference": "W/1"})
    fleet.enroll({"enrollment_token": issued["enrollment_token"], "endpoint_name": "lab-2"})
    with pytest.raises(CaseworkError):
        fleet.enroll({"enrollment_token": issued["enrollment_token"], "endpoint_name": "lab-2"})


def test_an_invalid_enrollment_token_is_refused(fleet):
    fleet.issue_enrollment_token({"endpoint_name": "lab-1", "authorization_reference": "W/1"})
    with pytest.raises(CaseworkError) as error:
        fleet.enroll({"enrollment_token": "guessed", "endpoint_name": "lab-1"})
    assert error.value.status == 401


def test_an_expired_enrollment_token_is_refused(fleet):
    issued = fleet.issue_enrollment_token({"endpoint_name": "lab-1",
                                           "authorization_reference": "W/1"})
    with fleet.store.transaction() as db:
        db.execute("UPDATE enrollment_tokens SET expires_at=?",
                   ("2000-01-01T00:00:00+00:00",))
    with pytest.raises(CaseworkError):
        fleet.enroll({"enrollment_token": issued["enrollment_token"], "endpoint_name": "lab-1"})


def test_two_endpoints_cannot_share_a_name(fleet):
    fleet.issue_enrollment_token({"endpoint_name": "lab-1", "authorization_reference": "W/1"})
    issued = fleet.issue_enrollment_token({"endpoint_name": "lab-1",
                                           "authorization_reference": "W/1"})
    fleet.enroll({"enrollment_token": issued["enrollment_token"], "endpoint_name": "lab-1"})
    with pytest.raises(CaseworkError):
        fleet.issue_enrollment_token({"endpoint_name": "lab-1", "authorization_reference": "W/1"})


# --- credentials --------------------------------------------------------------
def test_the_stored_credential_is_not_the_token(enrolled):
    fleet, identity = enrolled
    stored = fleet.store.rows("SELECT token_digest FROM endpoints WHERE id=?",
                              (identity["endpoint_id"],))[0]["token_digest"]
    assert identity["endpoint_token"] not in stored


def test_no_credential_appears_in_a_response(enrolled):
    fleet, identity = enrolled
    presented = json.dumps(fleet.get_endpoint(identity["endpoint_id"]))
    assert "token_digest" not in presented and "token_salt" not in presented
    assert identity["endpoint_token"] not in presented


def test_a_wrong_credential_is_refused(enrolled):
    fleet, identity = enrolled
    with pytest.raises(CaseworkError) as error:
        fleet.authenticate(identity["endpoint_id"], "not-the-token")
    assert error.value.status == 401


def test_a_revoked_endpoint_cannot_authenticate(enrolled):
    fleet, identity = enrolled
    fleet.revoke(identity["endpoint_id"])
    with pytest.raises(CaseworkError) as error:
        fleet.authenticate(identity["endpoint_id"], identity["endpoint_token"])
    assert error.value.status == 403


def test_revoking_abandons_queued_work_but_keeps_collected_evidence(enrolled, plan):
    fleet, identity = enrolled
    endpoint = fleet.authenticate(identity["endpoint_id"], identity["endpoint_token"])
    fleet.dispatch_plan(plan=plan, endpoint_ids=[identity["endpoint_id"]])
    claimed = fleet.claim_tasks(endpoint, limit=1)["tasks"][0]
    fleet.submit_result(endpoint, claimed["task_id"], {"ok": True, "result": {"status": "success"}})

    fleet.revoke(identity["endpoint_id"])
    states = {task["id"]: task["status"] for task in fleet.tasks()}
    assert states[claimed["task_id"]] == SUCCEEDED, (
        "withdrawing future authority must not retract evidence already collected")
    assert ABANDONED in states.values()
    assert fleet.get_endpoint(identity["endpoint_id"])["status"] == REVOKED


# --- tasks --------------------------------------------------------------------
def test_a_task_never_carries_a_command(enrolled, plan):
    fleet, identity = enrolled
    endpoint = fleet.authenticate(identity["endpoint_id"], identity["endpoint_token"])
    fleet.dispatch_plan(plan=plan, endpoint_ids=[identity["endpoint_id"]])
    for task in fleet.claim_tasks(endpoint, limit=10)["tasks"]:
        assert set(task) == {"task_id", "source", "collector", "arguments", "options", "attempt"}
        assert "command" not in json.dumps(task).lower()


def test_every_endpoint_gets_every_task_so_they_run_in_parallel(fleet, plan):
    ids = []
    for name in ("lab-1", "lab-2", "lab-3"):
        issued = fleet.issue_enrollment_token({"endpoint_name": name,
                                               "authorization_reference": "W/1"})
        ids.append(fleet.enroll({"enrollment_token": issued["enrollment_token"],
                                 "endpoint_name": name})["endpoint_id"])
    dispatch = fleet.dispatch_plan(plan=plan, endpoint_ids=ids)
    assert dispatch["endpoint_count"] == 3
    assert len(dispatch["queued"]) == 3 * dispatch["tasks_per_endpoint"]
    for endpoint_id in ids:
        assert len(fleet.tasks(endpoint_id=endpoint_id)) == dispatch["tasks_per_endpoint"]


def test_an_endpoint_only_sees_its_own_tasks(fleet, plan):
    ids = []
    for name in ("lab-1", "lab-2"):
        issued = fleet.issue_enrollment_token({"endpoint_name": name,
                                               "authorization_reference": "W/1"})
        ids.append(fleet.enroll({"enrollment_token": issued["enrollment_token"],
                                 "endpoint_name": name}))
    fleet.dispatch_plan(plan=plan, endpoint_ids=[ids[0]["endpoint_id"]])
    second = fleet.authenticate(ids[1]["endpoint_id"], ids[1]["endpoint_token"])
    assert fleet.claim_tasks(second)["tasks"] == []


def test_a_result_cannot_be_submitted_for_another_endpoints_task(fleet, plan):
    ids = []
    for name in ("lab-1", "lab-2"):
        issued = fleet.issue_enrollment_token({"endpoint_name": name,
                                               "authorization_reference": "W/1"})
        ids.append(fleet.enroll({"enrollment_token": issued["enrollment_token"],
                                 "endpoint_name": name}))
    fleet.dispatch_plan(plan=plan, endpoint_ids=[ids[0]["endpoint_id"]])
    first = fleet.authenticate(ids[0]["endpoint_id"], ids[0]["endpoint_token"])
    second = fleet.authenticate(ids[1]["endpoint_id"], ids[1]["endpoint_token"])
    task = fleet.claim_tasks(first, limit=1)["tasks"][0]
    with pytest.raises(CaseworkError) as error:
        fleet.submit_result(second, task["task_id"], {"ok": True, "result": {}})
    assert error.value.status == 404


def test_a_failed_task_is_retried_then_abandoned_with_its_error(enrolled, plan):
    fleet, identity = enrolled
    endpoint = fleet.authenticate(identity["endpoint_id"], identity["endpoint_token"])
    fleet.dispatch_plan(plan=plan, endpoint_ids=[identity["endpoint_id"]])
    task_id = fleet.claim_tasks(endpoint, limit=1)["tasks"][0]["task_id"]

    outcome = fleet.submit_result(endpoint, task_id,
                                  {"ok": False, "error": {"code": "x", "message": "nope"}})
    assert outcome["status"] == QUEUED and outcome["retry_after"]

    for _attempt in range(fleet.MAX_ATTEMPTS):
        with fleet.store.transaction() as db:
            db.execute("UPDATE endpoint_tasks SET available_at='2000-01-01T00:00:00+00:00',"
                       " status=? WHERE id=?", (QUEUED, task_id))
        fleet.claim_tasks(endpoint, limit=1)
        outcome = fleet.submit_result(endpoint, task_id,
                                      {"ok": False, "error": {"code": "x", "message": "nope"}})
    assert outcome["status"] == ABANDONED
    abandoned = [task for task in fleet.tasks() if task["id"] == task_id][0]
    assert abandoned["error"]["message"] == "nope", "the last error must survive abandonment"


def test_a_closed_task_cannot_be_resubmitted(enrolled, plan):
    fleet, identity = enrolled
    endpoint = fleet.authenticate(identity["endpoint_id"], identity["endpoint_token"])
    fleet.dispatch_plan(plan=plan, endpoint_ids=[identity["endpoint_id"]])
    task_id = fleet.claim_tasks(endpoint, limit=1)["tasks"][0]["task_id"]
    fleet.submit_result(endpoint, task_id, {"ok": True, "result": {"status": "success"}})
    with pytest.raises(CaseworkError):
        fleet.submit_result(endpoint, task_id, {"ok": True, "result": {"status": "success"}})


def test_a_result_is_hashed_on_arrival(enrolled, plan):
    fleet, identity = enrolled
    endpoint = fleet.authenticate(identity["endpoint_id"], identity["endpoint_token"])
    fleet.dispatch_plan(plan=plan, endpoint_ids=[identity["endpoint_id"]])
    task_id = fleet.claim_tasks(endpoint, limit=1)["tasks"][0]["task_id"]
    outcome = fleet.submit_result(endpoint, task_id, {"ok": True, "result": {"status": "success"}})
    assert len(outcome["result_sha256"]) == 64


def test_an_oversized_result_is_rejected_not_truncated(enrolled, plan, monkeypatch):
    """A silently shortened result would be evidence that is quietly wrong."""
    import backend.fleet as module
    monkeypatch.setattr(module, "MAX_RESULT_BYTES", 64)
    fleet, identity = enrolled
    endpoint = fleet.authenticate(identity["endpoint_id"], identity["endpoint_token"])
    fleet.dispatch_plan(plan=plan, endpoint_ids=[identity["endpoint_id"]])
    task_id = fleet.claim_tasks(endpoint, limit=1)["tasks"][0]["task_id"]
    outcome = fleet.submit_result(endpoint, task_id, {"ok": True, "result": {"x": "y" * 500}})
    assert outcome["status"] == QUEUED
    task = [item for item in fleet.tasks() if item["id"] == task_id][0]
    assert task["error"]["code"] == "result_too_large"
    assert task["result"] is None


def test_a_silent_endpoints_task_returns_to_the_queue(enrolled, plan):
    fleet, identity = enrolled
    endpoint = fleet.authenticate(identity["endpoint_id"], identity["endpoint_token"])
    fleet.dispatch_plan(plan=plan, endpoint_ids=[identity["endpoint_id"]])
    fleet.claim_tasks(endpoint, limit=1)
    with fleet.store.transaction() as db:
        db.execute("UPDATE endpoint_tasks SET dispatched_at='2000-01-01T00:00:00+00:00'")
    assert fleet.sweep()["requeued"] >= 1


# --- health -------------------------------------------------------------------
def test_a_heartbeat_updates_capabilities_and_health(enrolled):
    fleet, identity = enrolled
    endpoint = fleet.authenticate(identity["endpoint_id"], identity["endpoint_token"])
    fleet.heartbeat(endpoint, {"capabilities": ["NETWORK", "DRIVERS"], "platform": "Linux"})
    record = fleet.get_endpoint(identity["endpoint_id"])
    assert record["health"]["state"] == "healthy"
    assert record["capabilities"] == ["DRIVERS", "NETWORK"]


def test_a_silent_endpoint_is_stale_not_declared_absent(enrolled):
    fleet, identity = enrolled
    with fleet.store.transaction() as db:
        db.execute("UPDATE endpoints SET last_seen_at='2000-01-01T00:00:00+00:00'")
    health = fleet.get_endpoint(identity["endpoint_id"])["health"]
    assert health["state"] == "stale"
    assert "not that the machine is off" in health["detail"]


def test_enrollment_and_dispatch_reach_the_audit_trail(enrolled, plan):
    fleet, identity = enrolled
    fleet.dispatch_plan(plan=plan, endpoint_ids=[identity["endpoint_id"]])
    actions = [entry["action"] for entry in fleet.casework.audit_trail()]
    assert "endpoint.enrollment_authorized" in actions
    assert "endpoint.enrolled" in actions
    assert "collection.dispatched" in actions
