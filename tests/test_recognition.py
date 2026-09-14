"""Software recognition.

The property that matters most here is the negative one: a familiar filename in
a place no package accounts for must not be recognized. A recognition layer that
can be fooled by naming a file `python3` is worse than none, because it
reassures an investigator about the one record that deserved their attention.
"""
import json

import pytest

from analysis import recognition
from analysis.recognition import (
    HIGH, LOW, MODERATE, NONE, RECOGNITION_VERSION, SoftwareIndex, recognize_artifacts,
    recognize_events, recognize_path,
)


@pytest.fixture
def index(tmp_path):
    """An index over a fabricated system, so assertions do not depend on the host."""
    info = tmp_path / "dpkg" / "info"
    info.mkdir(parents=True)
    (info / "python3-minimal.list").write_text("/usr/bin/python3\n/usr/lib/python3.12/os.py\n")
    (info / "git.list").write_text("/usr/bin/git\n")
    status = tmp_path / "status"
    status.write_text(
        "Package: python3-minimal\nStatus: install ok installed\nVersion: 3.12.3-0ubuntu2\n"
        "Section: python\nMaintainer: Ubuntu Developers <x@example.invalid>\n"
        "Description: minimal subset of the Python language\n\n"
        "Package: git\nStatus: install ok installed\nVersion: 1:2.43.0\nSection: vcs\n"
        "Description: distributed revision control system\n\n")

    snap = tmp_path / "snap" / "chromium" / "current" / "meta"
    snap.mkdir(parents=True)
    (snap / "snap.yaml").write_text(
        "name: chromium\ntitle: Chromium\nversion: 141.0.1\nsummary: web browser\n")

    reference = tmp_path / "software_reference.json"
    reference.write_text(json.dumps({
        "name": "test reference", "version": 1,
        "entries": [{"name": "Flutter SDK", "category": "development toolchain",
                     "path_contains": "/flutter/", "marker": "bin/cache/flutter.version.json",
                     "version_json_key": "frameworkVersion", "confidence": "HIGH"}],
    }))
    flutter = tmp_path / "opt" / "flutter" / "bin" / "cache"
    flutter.mkdir(parents=True)
    (flutter / "flutter.version.json").write_text(json.dumps({"frameworkVersion": "3.47.2"}))

    return SoftwareIndex(dpkg_info=str(info), dpkg_status=str(status),
                         snap_root=str(tmp_path / "snap"), reference_path=reference), tmp_path


# --- the layers ---------------------------------------------------------------
def test_package_ownership_names_and_versions_the_software(index):
    built, _root = index
    result = recognize_path("/usr/bin/python3", built)
    assert result["recognized"] is True
    assert result["recognized_name"] == "python3-minimal"
    assert result["version"] == "3.12.3-0ubuntu2"
    assert result["confidence"] == HIGH
    assert result["basis_codes"] == ["package_manager_ownership"]


def test_snap_metadata_is_recognized(index):
    built, root = index
    result = recognize_path(f"{root}/snap/chromium/current/usr/lib/chromium/chrome", built)
    assert result["recognized_name"] == "Chromium"
    assert result["version"] == "141.0.1"
    assert result["basis_codes"] == ["snap_metadata"]


def test_a_vendor_layout_needs_its_marker_file(index, tmp_path):
    """A directory named after software is not an installation of it."""
    built, root = index
    real = recognize_path(f"{root}/opt/flutter/bin/flutter", built)
    assert real["recognized"] is True and real["version"] == "3.47.2"

    fake = recognize_path("/home/someone/Downloads/flutter/bin/flutter", built)
    assert fake["recognized"] is False, (
        "a folder called flutter with no installation inside it is not Flutter")


# --- the negative cases, which matter most ------------------------------------
def test_a_familiar_name_in_a_writable_location_is_not_recognized(index):
    built, _root = index
    result = recognize_path("/tmp/.cache/python3", built)
    assert result["recognized"] is False
    assert result["confidence"] == NONE
    assert "world-writable" in result["limitations"][0]


def test_a_system_location_is_reported_as_a_location_not_an_identity(index):
    built, _root = index
    result = recognize_path("/usr/bin/not-a-package", built)
    assert result["recognized"] is False, "location is not identity"
    assert result["confidence"] == LOW
    assert result["basis_codes"] == ["trusted_system_location"]
    assert result["recognized_name"] is None


def test_an_unknown_path_is_unrecognized_rather_than_guessed(index):
    built, _root = index
    result = recognize_path("/home/user/scripts/helper", built)
    assert result["recognized"] is False and result["recognized_name"] is None


def test_an_empty_path_recognizes_nothing(index):
    built, _root = index
    assert recognize_path(None, built)["recognized"] is False


# --- explainability -----------------------------------------------------------
def test_every_recognition_states_its_basis_and_limits(index):
    built, _root = index
    for path in ("/usr/bin/python3", "/usr/bin/git"):
        result = recognize_path(path, built)
        assert result["recognition_basis"], f"{path} was recognized without saying why"
        assert result["limitations"], f"{path} was recognized without stating its limits"
        assert result["recognition_version"] == RECOGNITION_VERSION
        assert result["source"]


def test_package_recognition_does_not_claim_the_bytes_are_unchanged(index):
    built, _root = index
    limits = " ".join(recognize_path("/usr/bin/python3", built)["limitations"])
    assert "does not establish that the bytes now there are still the package's" in limits


def test_there_is_no_opaque_safety_score(index):
    built, _root = index
    result = recognize_path("/usr/bin/python3", built)
    for forbidden in ("safe", "safety", "score", "trusted", "clean", "benign"):
        assert forbidden not in json.dumps(result).lower().replace("trusted_system_location", "")


# --- recognition never executes anything --------------------------------------
def test_recognition_runs_no_program():
    """Version numbers come from metadata on disk, never from `--version`.

    Running the binary would change the machine under examination and would
    execute a file whose provenance is the open question.
    """
    import inspect
    import re

    source = inspect.getsource(recognition)
    forbidden = re.compile(r"(subprocess|os\.system|popen|run_command|eval\(|exec\()")
    offending = [line.strip() for line in source.splitlines() if forbidden.search(line)]
    assert not offending, f"recognition must not execute anything: {offending}"


# --- bulk application ---------------------------------------------------------
def test_artifacts_are_annotated_and_summarized(index):
    built, _root = index
    artifacts = [{"path": "/usr/bin/python3", "reference": "ART-0001"},
                 {"path": "/usr/bin/git", "reference": "ART-0002"},
                 {"path": "/tmp/x/unknown", "reference": "ART-0003"}]
    summary = recognize_artifacts(artifacts, index=built)
    assert summary["artifacts_examined"] == 3
    assert summary["artifacts_recognized"] == 2
    assert {item["name"] for item in summary["software"]} == {"python3-minimal", "git"}
    assert artifacts[2]["recognition"]["recognized"] is False
    assert "not a statement that the file is safe" in summary["note"]


def test_a_recognized_artifact_cites_the_evidence_it_annotates(index):
    built, _root = index
    artifacts = [{"path": "/usr/bin/git", "reference": "ART-0007"}]
    recognize_artifacts(artifacts, index=built)
    assert artifacts[0]["recognition"]["matched_evidence"] == ["ART-0007"]


def test_events_are_recognized_by_executable_never_by_process_name(index):
    built, _root = index
    events = [{"executable": "/usr/bin/python3", "process_name": "python3", "reference": "EXEC-1"},
              {"executable": None, "process_name": "python3", "reference": "EXEC-2"}]
    recognize_events(events, index=built)
    assert events[0]["recognition"]["recognized"] is True
    assert events[1]["recognition"]["recognized"] is False
    assert "process name alone is not evidence" in events[1]["recognition"]["limitations"][0]


def test_the_index_reports_which_sources_it_could_read(index):
    built, _root = index
    statuses = {entry["source"]: entry["status"] for entry in built.sources}
    assert statuses["dpkg"] == "AVAILABLE"
    assert statuses["snap"] == "AVAILABLE"


def test_a_missing_package_database_is_reported_not_fatal(tmp_path):
    built = SoftwareIndex(dpkg_info=str(tmp_path / "absent"), dpkg_status=str(tmp_path / "none"),
                          snap_root=str(tmp_path / "nosnap"),
                          reference_path=tmp_path / "missing.json")
    statuses = {entry["source"]: entry["status"] for entry in built.sources}
    assert statuses["dpkg"] == "NOT_AVAILABLE"
    assert recognize_path("/usr/bin/python3", built)["recognized"] is False


@pytest.mark.real_telemetry
def test_the_real_host_package_database_recognizes_real_software():
    """Exercised against this machine, not a fixture."""
    built = SoftwareIndex()
    if not built.paths:
        pytest.skip("no package database on this host")
    result = recognize_path("/usr/bin/python3", built)
    assert result["recognized"] is True and result["version"]
