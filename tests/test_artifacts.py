"""Artifact observation: evidence-driven, bounded, and honest about gaps."""
import os

import pytest

from analysis.evidence_paths import normalize
from tests.conftest import requires_posix

from analysis import artifacts
from analysis.evidence_paths import normalize
from analysis.artifacts import (
    COLLECTED, MISSING, NOT_A_FILE, PERMISSION_DENIED, SKIPPED_TOO_LARGE,
    artifact_from_hash_result, collect_artifacts, merge_artifacts, notable_location,
    observe_artifact,
)


def event(executable, source="systemd journal"):
    return {"executable": executable, "source": source, "event_id": f"{source}:{executable}"}


def test_present_file_is_hashed_with_metadata(tmp_path):
    target = tmp_path / "report.pdf"
    target.write_bytes(b"%PDF-1.4 fixture")

    record = observe_artifact(str(target), source="test")

    assert record["collection_status"] == COLLECTED
    assert record["hash"] and record["hash_algorithm"] == "SHA256"
    assert record["size_bytes"] == 16 and record["extension"] == ".pdf"
    assert record["modified"] and record["integrity"] is not None


def test_missing_artifact_is_recorded_not_dropped(tmp_path):
    record = observe_artifact(str(tmp_path / "gone.exe"), source="test")

    assert record["collection_status"] == MISSING
    assert record["classification"] == "UNAVAILABLE"
    assert "does not exist at collection time" in record["unavailable"]["file"]
    assert record["hash"] is None


@requires_posix
def test_unreadable_artifact_is_recorded_as_permission_denied(tmp_path):
    target = tmp_path / "secret.bin"
    target.write_bytes(b"x")
    target.chmod(0o000)
    try:
        record = observe_artifact(str(target), source="test")
    finally:
        target.chmod(0o600)
    if os.geteuid() == 0:
        pytest.skip("root bypasses the mode bits")
    assert record["collection_status"] == PERMISSION_DENIED
    assert record["hash"] is None


def test_oversized_file_keeps_metadata_but_skips_the_digest(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "MAX_HASH_BYTES", 4)
    target = tmp_path / "large.bin"
    target.write_bytes(b"0123456789")

    record = observe_artifact(str(target), source="test")

    assert record["collection_status"] == SKIPPED_TOO_LARGE
    assert record["size_bytes"] == 10 and record["hash"] is None
    assert "hashing limit" in record["unavailable"]["hash"]


def test_directory_is_recorded_without_a_digest(tmp_path):
    record = observe_artifact(str(tmp_path), source="test")

    assert record["collection_status"] == NOT_A_FILE
    assert record["hash"] is None


def test_executables_named_by_evidence_are_collected(tmp_path):
    present = tmp_path / "present.sh"
    present.write_text("#!/bin/sh\n")
    events = [event(str(present)), event(str(tmp_path / "absent.exe"))]

    result = collect_artifacts(events=events)

    # Compared through the same normalization the records use. A record stores
    # one spelling of a path so that evidence from any host can be joined on it,
    # and on Windows str(Path) is the other spelling.
    statuses = {record["path"]: record["collection_status"] for record in result["artifacts"]}
    assert statuses[normalize(str(present))] == COLLECTED
    assert statuses[normalize(str(tmp_path / "absent.exe"))] == MISSING
    assert result["statistics"]["referenced_path_count"] == 2
    assert any("not present at collection time" in warning for warning in result["warnings"])


def test_relative_history_text_is_never_treated_as_a_path():
    # Shell history records typed words, not resolved paths.
    result = collect_artifacts(events=[event("whoami", source="bash history")])

    assert result["artifacts"] == []


def test_selected_directory_is_one_level_and_never_recursive(tmp_path):
    (tmp_path / "top.txt").write_text("a")
    nested = tmp_path / "deep"
    nested.mkdir()
    (nested / "hidden.txt").write_text("b")

    result = collect_artifacts(selected_paths=[str(tmp_path)])

    paths = {record["path"] for record in result["artifacts"]}
    assert normalize(str(tmp_path / "top.txt")) in paths
    assert normalize(str(nested)) in paths
    assert normalize(str(nested / "hidden.txt")) not in paths, "collection must not recurse"
    assert result["limits"]["recursive"] is False


def test_artifact_count_is_bounded_and_truncation_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "MAX_ARTIFACTS", 2)
    for index in range(5):
        (tmp_path / f"file{index}.bin").write_text("x")

    result = collect_artifacts(selected_paths=[str(tmp_path)])

    assert result["artifact_count"] == 2
    assert result["truncated"] is True
    assert any("bound" in warning for warning in result["warnings"])


def test_duplicate_paths_are_observed_once(tmp_path):
    target = tmp_path / "once.bin"
    target.write_text("x")

    result = collect_artifacts(selected_paths=[str(target)],
                               events=[event(str(target)), event(str(target))])

    assert result["artifact_count"] == 1


@pytest.mark.parametrize("path,expected", [
    ("/tmp/stage", "tmp"),
    ("/var/tmp/stage", "var/tmp"),
    ("/dev/shm/x", "dev/shm"),
    ("/usr/bin/ls", None),
    (r"C:\Users\a\AppData\Local\Temp\x.exe", "appdata\\local\\temp"),
    (r"C:\Windows\System32\cmd.exe", None),
])
def test_notable_locations(path, expected):
    assert notable_location(path) == expected


def test_hash_result_adapter_reuses_the_existing_digest(tmp_path):
    from analysis import hashing
    target = tmp_path / "evidence.bin"
    target.write_bytes(b"abc")
    result = hashing.hash_file(str(target))

    record = artifact_from_hash_result(result, source="investigator-selected path")

    assert record["hash"] == result["hash"]
    assert record["collection_status"] == COLLECTED
    assert record["integrity_history"] == result["integrity_history"]


def test_merge_keeps_one_record_per_path(tmp_path):
    target = tmp_path / "x.bin"
    target.write_text("x")
    first = collect_artifacts(selected_paths=[str(target)])
    second = collect_artifacts(events=[event(str(target))])

    merged = merge_artifacts(first, second)

    assert merged["artifact_count"] == 1
    assert merged["statistics"]["by_collection_status"] == {COLLECTED: 1}


def test_cancellation_stops_between_artifacts(tmp_path):
    class Cancelled:
        def is_set(self):
            return True

    with pytest.raises(InterruptedError):
        observe_artifact(str(tmp_path), source="test", cancel=Cancelled())