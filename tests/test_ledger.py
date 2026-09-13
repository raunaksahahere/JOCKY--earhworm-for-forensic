from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

import pytest

from analysis import ledger

DIGEST = hashlib.sha256(b"abc").hexdigest()


def test_first_repeated_changed_and_algorithm():
    assert ledger.get_last_hash("file") is None
    assert ledger.observe_hash("file", "sha256", DIGEST, 3)[1]["status"] == "first_recorded"
    assert ledger.observe_hash("file", "sha256", DIGEST, 3)[1]["status"] == "unchanged"
    other = hashlib.sha256(b"other").hexdigest()
    assert ledger.observe_hash("file", "sha256", other, 5)[1]["status"] == "altered"
    assert ledger.observe_hash("file", "md5", hashlib.md5(b"other").hexdigest(), 5)[1]["status"] == "algorithm_mismatch"


@pytest.mark.parametrize("data", ["invalid JSON", "[]", "null", '{"x": []}', '{"x": [null]}', '{"x": [{}]}', '{"x": "bad"}'])
def test_corrupt_history_is_visible_and_preserved(data):
    path = Path(ledger._LEDGER_PATH)
    path.parent.mkdir()
    path.write_text(data)
    with pytest.raises(ledger.LedgerError):
        ledger.get_last_hash("x")
    with pytest.raises(ledger.LedgerError):
        ledger.record_hash("y", "sha256", DIGEST, 3)
    assert path.read_text() == data


@pytest.mark.parametrize(("key", "value"), [
    ("algorithm", "unknown"), ("hash", "not a digest"), ("size_bytes", -1),
    ("size_bytes", True), ("timestamp", "yesterday"), ("algorithm", None),
    ("timestamp", "2026-01-01T00:00:00"),
])
def test_invalid_observation(key, value):
    entry = {"algorithm": "SHA256", "hash": DIGEST, "size_bytes": 3, "timestamp": "2026-01-01T00:00:00+00:00"}
    entry[key] = value
    with pytest.raises(ledger.LedgerError):
        ledger.compare_to_last(entry, "sha256", DIGEST)


def test_missing_storage_created():
    assert not Path(ledger._DATA_DIR).exists()
    ledger.record_hash("file", "sha256", DIGEST, 3)
    assert ledger.get_last_hash("file")["hash"] == DIGEST


def test_concurrent_observations_are_serialized():
    with ThreadPoolExecutor(max_workers=8) as executor:
        observations = list(executor.map(lambda _: ledger.observe_hash("file", "sha256", DIGEST, 3), range(20)))
    assert sum(r[1]["status"] == "first_recorded" for r in observations) == 1
    assert sum(r[1]["status"] == "unchanged" for r in observations) == 19
    assert len(json.loads(Path(ledger._LEDGER_PATH).read_text())["file"]) == 20


def test_concurrent_different_paths_not_lost():
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda i: ledger.record_hash(str(i), "sha256", DIGEST, 3), range(30)))
    assert len(json.loads(Path(ledger._LEDGER_PATH).read_text())) == 30


def test_history_limit():
    for i in range(25):
        ledger.record_hash("file", "sha256", hashlib.sha256(str(i).encode()).hexdigest(), i)
    history = json.loads(Path(ledger._LEDGER_PATH).read_text())["file"]
    assert len(history) == 20
    assert history[0]["size_bytes"] == 5


def test_failed_replace_preserves_previous(monkeypatch):
    ledger.record_hash("file", "sha256", DIGEST, 3)
    before = Path(ledger._LEDGER_PATH).read_bytes()
    def fail(*args):
        raise PermissionError("fixture denied")
    monkeypatch.setattr(ledger.os, "replace", fail)
    with pytest.raises(ledger.LedgerError):
        ledger.record_hash("file", "sha256", DIGEST, 3)
    assert Path(ledger._LEDGER_PATH).read_bytes() == before


def test_unreadable_storage(monkeypatch):
    def fail(*args, **kwargs):
        raise PermissionError("fixture denied")
    monkeypatch.setattr(ledger, "open", fail, raising=False)
    with pytest.raises(ledger.LedgerError):
        ledger.get_last_hash("file")


def test_storage_path_is_file():
    Path(ledger._DATA_DIR).write_text("not a directory")
    with pytest.raises(ledger.LedgerError):
        ledger.record_hash("file", "sha256", DIGEST, 3)
