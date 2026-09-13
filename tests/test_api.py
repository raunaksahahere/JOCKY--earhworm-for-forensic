import pytest
import psutil

from communication import server


@pytest.mark.parametrize("payload", [None, [], [1], "text", 7, {}, {"command": None}, {"command": 5}, {"command": []}, {"command": ""}, {"command": "  "}])
def test_invalid_request_has_report(client, payload):
    response = client.post("/command", json=payload)
    assert response.status_code == 400
    data = response.get_json()
    assert data["status"] == "error" and data["error_kind"] == "validation"
    assert data["report"]["status"] == "failed" and data["report"]["errors"]
    assert data["result"] is None


def test_malformed_json(client):
    response = client.post("/command", data="{broken", content_type="application/json")
    assert response.status_code == 400
    assert response.json["report"]["status"] == "failed"


def test_syntax_error(client):
    response = client.post("/command", json={"command": "HASH FILE a b"})
    assert response.status_code == 400
    assert response.json["error_kind"] == "parser"
    assert response.json["error_code"] == "invalid_syntax"


def test_execution_error_retains_identity(client, tmp_path):
    path = str(tmp_path / "missing file")
    response = client.post("/command", json={"command": f'HASH FILE "{path}"'})
    assert response.status_code == 400
    data = response.json
    assert data["error_kind"] == "execution" and data["error_code"] == "not_found"
    assert data["report"]["action"] == "hash" and data["report"]["target"] == path
    assert data["normalized_command"]["schema_version"] == 1


def test_hash_end_to_end(client, evidence):
    response = client.post("/command", json={"command": f'HASH FILE "{evidence}"'})
    assert response.status_code == 200
    data = response.json
    assert data["result"]["hash"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert data["report"]["result"] == data["result"]
    assert data["report"]["normalized_command"] == data["normalized_command"]
    assert data["error"] is None and data["report"]["status"] == "completed"


def test_search_root_error(client, evidence):
    response = client.post("/command", json={"command": f'SEARCH FILE x IN "{evidence}"'})
    assert response.status_code == 400 and response.json["error_code"] == "not_a_directory"


def test_report_preserves_truncation(client, tmp_path, monkeypatch):
    from analysis import files
    (tmp_path / "a").write_text("a")
    (tmp_path / "b").write_text("b")
    monkeypatch.setattr(files, "MAX_LIST_ENTRIES", 1)
    response = client.post("/command", json={"command": f'LIST FILES "{tmp_path}"'})
    assert response.status_code == 200
    assert response.json["report"]["warnings"]
    assert response.json["report"]["result"]["truncated"]


def test_unexpected_error_is_server_failure(client, monkeypatch):
    def broken(command):
        raise TypeError("private implementation detail")
    monkeypatch.setattr(server, "execute_command", broken)
    response = client.post("/command", json={"command": "PROCESSES"})
    assert response.status_code == 500
    assert response.json["error_code"] == "internal_error"
    assert "private" not in response.json["error"]
    assert response.json["report"]["action"] == "processes"


def test_health_and_reference(client):
    assert client.get("/health").json["engine"] == "online"
    reference = client.get("/commands").json
    assert reference["schema_version"] == 1 and len(reference["commands"]) == 6


def test_process_enumeration_denied_is_execution_failure(client, monkeypatch):
    def denied(attrs):
        raise psutil.AccessDenied()
    monkeypatch.setattr(psutil, "process_iter", denied)
    response = client.post("/command", json={"command": "PROCESSES"})
    assert response.status_code == 400
    assert response.json["error_code"] == "permission_denied"
    assert response.json["error_kind"] == "execution"


def test_process_api_nullable_measurements(client, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: iter([
        SimpleNamespace(info={"pid": 1, "memory_percent": None})
    ]))
    response = client.post("/command", json={"command": "PROCESSES"})
    assert response.status_code == 200
    assert response.json["result"]["processes"][0]["cpu_percent"] is None
    assert response.json["report"]["warnings"]


def test_system_api_unavailable_metrics(client, monkeypatch):
    from analysis import system
    monkeypatch.setattr(system, "psutil", None)
    monkeypatch.setattr(system.socket, "gethostname", lambda: "fixture-host")
    response = client.post("/command", json={"command": "SYSTEM INFO"})
    assert response.status_code == 200
    assert response.json["result"]["hostname"] == "fixture-host"
    assert response.json["report"]["warnings"]


def test_search_api_keeps_both_arguments(client, evidence):
    response = client.post("/command", json={"command": f'SEARCH FILE "नमूना" IN "{evidence.parent}"'})
    assert response.status_code == 200
    assert response.json["result"]["results"][0]["path"] == str(evidence)
    assert response.json["report"]["normalized_command"]["search_path"] == str(evidence.parent)


def test_encrypt_requires_explicit_safe_export(client, evidence):
    original = evidence.read_bytes()
    response = client.post("/command", json={"command": f'ENCRYPT FILE "{evidence}"'})
    assert response.status_code == 400
    assert response.json["report"]["status"] == "failed"
    assert "separate destination" in response.json["error"]
    assert evidence.read_bytes() == original


def test_corrupt_ledger_api_never_claims_integrity(client, evidence):
    from pathlib import Path
    from analysis import ledger
    path = Path(ledger._LEDGER_PATH)
    path.parent.mkdir()
    path.write_text("broken")
    response = client.post("/command", json={"command": f'HASH FILE "{evidence}"'})
    assert response.status_code == 400
    assert response.json["error_code"] == "ledger_unavailable"
    assert response.json["report"]["status"] == "failed"
