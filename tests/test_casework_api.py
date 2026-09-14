"""The HTTP surface for casework, programs and endpoints.

Two boundaries are checked here that exist nowhere else: the local UI routes
stay loopback-only, and the endpoint routes -- which must be reachable from
another machine -- authenticate with an endpoint credential and expose nothing
but forensic collection.
"""
import pytest

from backend.api import create_app
from backend.paths import Paths
from backend.service import Workstation
from backend.storage import Store

HEADERS = {"Authorization": "Bearer token", "X-Jocky-Instance": "instance"}
PROGRAM = 'CASE "c"\nTARGET "host"\nCOLLECT NETWORK\nCOLLECT USB\nREPORT SUMMARY\n'


@pytest.fixture
def client(tmp_path):
    service = Workstation(Store(Paths.resolve(str(tmp_path / "workspace"))))
    try:
        yield create_app(service, "token", "instance").test_client()
    finally:
        service.close()


def post(client, url, payload=None, **kwargs):
    return client.post(url, json=payload if payload is not None else {}, headers=HEADERS, **kwargs)


# --- cases, evidence, notes, audit --------------------------------------------
def test_a_case_round_trips_through_the_api(client):
    case = post(client, "/api/v1/cases", {"title": "Staging", "examiner": "R"}).get_json()
    assert client.get(f"/api/v1/cases/{case['id']}", headers=HEADERS).get_json()["title"] == "Staging"
    assert client.get("/api/v1/cases", headers=HEADERS).get_json()["items"][0]["id"] == case["id"]


def test_registering_and_verifying_evidence_over_the_api(client, tmp_path):
    evidence = tmp_path / "sample.bin"
    evidence.write_bytes(b"bytes")
    record = post(client, "/api/v1/evidence-sources", {"path": str(evidence)}).get_json()
    assert record["verification_state"] == "VERIFIED"
    verified = post(client, f"/api/v1/evidence-sources/{record['id']}/verify").get_json()
    assert verified["verification_state"] == "VERIFIED"


def test_a_relative_evidence_path_is_a_400(client):
    assert post(client, "/api/v1/evidence-sources", {"path": "relative"}).status_code == 400


def test_the_audit_route_says_what_it_is_and_is_not(client):
    post(client, "/api/v1/cases", {"title": "x"})
    payload = client.get("/api/v1/audit", headers=HEADERS).get_json()
    assert payload["items"]
    assert "not evidence about the examined host" in payload["note"]


def test_notes_are_stored_against_a_subject(client):
    case = post(client, "/api/v1/cases", {"title": "x"}).get_json()
    post(client, "/api/v1/notes", {"case_id": case["id"], "subject_type": "case",
                                   "subject_id": case["id"], "body": "Observed by hand."})
    notes = client.get(f"/api/v1/notes?case_id={case['id']}", headers=HEADERS).get_json()
    assert notes["items"][0]["body"] == "Observed by hand."


# --- programs -----------------------------------------------------------------
def test_a_program_can_be_compiled_without_collecting(client):
    # The platform is named rather than inherited from the host: the same
    # program yields different plans per platform, which is the whole point.
    payload = post(client, "/api/v1/programs/compile",
                   {"program": PROGRAM, "platform": "linux"}).get_json()
    assert payload["plan"]["ready_task_count"] == 2
    assert payload["explanation"] and payload["plan_explanation"]


def test_compiling_for_windows_names_what_it_cannot_collect(client):
    payload = post(client, "/api/v1/programs/compile",
                   {"program": PROGRAM, "platform": "windows"}).get_json()
    assert payload["plan"]["platform_validated"] is False
    assert "USB" in {item["source"] for item in payload["plan"]["unsupported"]}


def test_an_invalid_program_returns_a_program_error(client):
    response = post(client, "/api/v1/programs/compile", {"program": "COLLECT NETWORK\n"})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "program_error"


def test_the_selectable_sources_are_advertised(client):
    payload = client.get("/api/v1/collection-sources", headers=HEADERS).get_json()
    names = {item["source"] for item in payload["selectable"]}
    assert {"NETWORK", "BROWSER", "USB", "DRIVERS", "MEMORY", "SERVICES"} == names
    assert next(item for item in payload["selectable"]
                if item["source"] == "MEMORY")["needs_argument"] is True


def test_an_unknown_source_is_refused_with_the_list_of_known_ones(client):
    case = post(client, "/api/v1/investigations", {"title": "x"}).get_json()
    response = post(client, f"/api/v1/investigations/{case['id']}/collect",
                    {"paths": [], "sources": ["NOT_A_SOURCE"]})
    assert response.status_code == 400
    assert "NOT_A_SOURCE" in response.get_json()["error"]["message"]


def test_collecting_memory_without_an_image_is_refused(client):
    case = post(client, "/api/v1/investigations", {"title": "x"}).get_json()
    response = post(client, f"/api/v1/investigations/{case['id']}/collect",
                    {"paths": [], "sources": ["MEMORY"]})
    assert response.status_code == 400
    assert "does not acquire memory" in response.get_json()["error"]["message"]


# --- endpoints ----------------------------------------------------------------
def _enroll(client, name="lab-1"):
    issued = post(client, "/api/v1/endpoints/authorize",
                  {"endpoint_name": name, "authorization_reference": "W/1"}).get_json()
    return client.post("/api/v1/endpoints/enroll",
                       json={"enrollment_token": issued["enrollment_token"],
                             "endpoint_name": name, "platform": "Linux"}).get_json()


def test_enrollment_needs_no_local_session_but_the_control_routes_do(client):
    """An agent runs on another machine; the investigator's UI does not."""
    identity = _enroll(client)
    assert identity["endpoint_id"]
    assert client.get("/api/v1/endpoints").status_code == 401


def test_an_endpoint_authenticates_with_its_own_credential(client):
    identity = _enroll(client)
    agent = {"Authorization": f"Bearer {identity['endpoint_token']}",
             "X-Jocky-Endpoint": identity["endpoint_id"]}
    assert client.post("/api/v1/endpoints/heartbeat", json={}, headers=agent).status_code == 200
    assert client.post("/api/v1/endpoints/heartbeat", json={},
                       headers={**agent, "Authorization": "Bearer wrong"}).status_code == 401


def test_an_endpoint_credential_does_not_open_the_investigator_api(client):
    """An endpoint must not be able to read the case file it collects for."""
    identity = _enroll(client)
    agent = {"Authorization": f"Bearer {identity['endpoint_token']}",
             "X-Jocky-Endpoint": identity["endpoint_id"]}
    assert client.get("/api/v1/cases", headers=agent).status_code == 401
    assert client.get("/api/v1/audit", headers=agent).status_code == 401
    assert client.get("/api/v1/investigations", headers=agent).status_code == 401


def test_dispatch_queues_tasks_that_carry_no_command(client):
    identity = _enroll(client)
    response = post(client, "/api/v1/collections/dispatch",
                    {"program": PROGRAM, "platform": "linux",
                     "endpoints": [identity["endpoint_id"]]})
    assert response.status_code == 202
    assert "No task carries a command" in response.get_json()["note"]

    agent = {"Authorization": f"Bearer {identity['endpoint_token']}",
             "X-Jocky-Endpoint": identity["endpoint_id"]}
    claimed = client.post("/api/v1/endpoints/tasks/claim", json={}, headers=agent).get_json()
    assert {task["source"] for task in claimed["tasks"]} == {"NETWORK", "USB"}
    for task in claimed["tasks"]:
        assert "command" not in task


def test_dispatch_needs_at_least_one_endpoint(client):
    assert post(client, "/api/v1/collections/dispatch",
                {"program": PROGRAM, "endpoints": []}).status_code == 400


def test_there_is_no_route_that_runs_a_command_on_an_endpoint(client):
    """A regression guard: adding one would defeat the agent's whole premise."""
    endpoint_rules = [str(rule) for rule in client.application.url_map.iter_rules()
                      if "/endpoints" in str(rule) or "/endpoint-tasks" in str(rule)]
    assert endpoint_rules
    for rule in endpoint_rules:
        assert not any(word in rule for word in ("command", "exec", "shell", "run", "script"))
