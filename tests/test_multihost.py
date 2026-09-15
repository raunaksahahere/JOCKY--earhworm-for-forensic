"""Multi-host validation, memory workflow and the evidence package.

The multi-host test runs against genuinely separate Linux environments when
Docker is available and skips honestly when it is not. It never passes by
running two agents on the same machine, which is the thing the previous pass
did and said so about.
"""
import io
import json
import shutil
import subprocess
import zipfile

import pytest

from backend.casework import Casework, CaseworkError, identify_container
from backend.evidence_package import build_package, verify_package
from backend.memory_workflow import MemoryWorkflow
from backend.paths import Paths
from backend.storage import Store
from backend.versions import DATABASE_SCHEMA_VERSION, REPORT_SCHEMA_VERSION, versions


def docker_usable():
    """Whether two separate Linux environments can actually be started here.

    Docker being installed is not enough: the Windows runners have a Docker
    whose daemon runs Windows containers, which cannot host the Linux images
    this validation uses. Asking the daemon what it runs is the difference
    between skipping honestly and failing for a reason that is not a defect.
    """
    if not shutil.which("docker"):
        return False
    try:
        probe = subprocess.run(["docker", "info", "--format", "{{.OSType}}"],
                               capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0 and probe.stdout.strip().lower() == "linux"


needs_docker = pytest.mark.skipif(
    not docker_usable(),
    reason="real multi-host validation needs two separate Linux environments; without a "
           "Linux container daemon there are none, and the requirement matrix must keep "
           "saying NOT VALIDATED rather than this passing vacuously")


@pytest.fixture
def store(tmp_path):
    return Store(Paths.resolve(str(tmp_path / "workspace")))


# --- real multi-host ----------------------------------------------------------
@needs_docker
@pytest.mark.real_telemetry
def test_two_real_hosts_correlate_on_a_shared_file_and_not_on_a_unique_one(tmp_path):
    """The whole validation, run in-process so CI reports it as a test."""
    from validation.multihost import main

    assert main(["--output", str(tmp_path / "out")]) == 0
    report = json.loads((tmp_path / "out" / "multihost-validation.json").read_text())
    assert report["result"] == "PASSED"
    assert report["hostnames"]["endpoint-a"] != report["hostnames"]["endpoint-b"]
    matched = {item["value"] for item in report["correlation"]["correlations"]}
    assert report["shared_sha256"] in matched
    assert report["unique_sha256"] not in matched, (
        "a file on one host only must never be reported as a cross-host match")
    assert report["limitations"], "the validation must state what it does not establish"


def test_the_validation_skips_rather_than_pretending(monkeypatch):
    """With no separate environment available, it must not quietly pass."""
    from validation import multihost

    monkeypatch.setattr(multihost.shutil, "which", lambda name: None)
    assert multihost.main(["--output", "/tmp/jocky-should-not-exist"]) == 2


# --- memory workflow ----------------------------------------------------------
def test_an_image_is_registered_and_hashed_before_analysis(store, tmp_path):
    workflow = MemoryWorkflow(store, Casework(store))
    image = tmp_path / "lab.raw"
    image.write_bytes(b"lab image bytes")
    source = workflow.register_image({"path": str(image)})
    assert source["source_type"] == "memory_image"
    assert len(source["sha256"]) == 64
    assert source["processing_status"] == "REGISTERED"


def test_analysis_records_the_digest_of_the_image_it_read(store, tmp_path):
    casework = Casework(store)
    workflow = MemoryWorkflow(store, casework)
    image = tmp_path / "lab.raw"
    image.write_bytes(b"lab image bytes")
    source = workflow.register_image({"path": str(image)})
    analysis = workflow.analyse({
        "evidence_source_id": source["id"],
        "fixture": {"processes": [{"PID": 4, "PPID": 0, "ImageFileName": "System"}]}})
    assert analysis["status"] == "COMPLETED"
    assert analysis["image_sha256"] == source["sha256"]
    assert analysis["result"]["processes"][0]["process_name"] == "System"


def test_a_changed_image_is_refused_rather_than_analysed(store, tmp_path):
    """Findings must never be attributed to bytes that are no longer there."""
    casework = Casework(store)
    workflow = MemoryWorkflow(store, casework)
    image = tmp_path / "lab.raw"
    image.write_bytes(b"original")
    source = workflow.register_image({"path": str(image)})
    image.write_bytes(b"different bytes entirely")
    with pytest.raises(CaseworkError) as error:
        workflow.analyse({"evidence_source_id": source["id"], "fixture": {"processes": []}})
    assert "no longer matches" in str(error.value)


def test_a_fixture_analysis_says_it_is_not_evidence_about_a_machine(store):
    workflow = MemoryWorkflow(store, Casework(store))
    analysis = workflow.analyse({"fixture": {"processes": [
        {"PID": 4, "PPID": 0, "ImageFileName": "System"}]}})
    assert analysis["provenance"] == "FIXTURE"
    assert "not evidence about any real machine" in analysis["provenance_statement"]


def test_memory_findings_are_linked_to_the_analysis(store):
    workflow = MemoryWorkflow(store, Casework(store))
    analysis = workflow.analyse({"fixture": {"processes": [
        {"PID": 4, "PPID": 0, "ImageFileName": "System"},
        {"PID": 900, "PPID": 777, "ImageFileName": "updater.exe"}]}})
    categories = {finding["category"] for finding in analysis["result"]["findings"]}
    assert "memory_orphan_process" in categories


def test_analysis_needs_an_image_or_a_fixture(store):
    workflow = MemoryWorkflow(store, Casework(store))
    with pytest.raises(CaseworkError) as error:
        workflow.analyse({})
    assert "does not acquire memory" in str(error.value)


def test_the_capability_endpoint_states_what_this_host_can_do(store):
    capability = MemoryWorkflow(store, Casework(store)).capability()
    assert capability["acquires_memory"] is False
    assert capability["parses_images_itself"] is False
    assert capability["read_only"] is True
    assert capability["detail"]


def test_memory_analysis_never_claims_a_real_image_without_one(store):
    workflow = MemoryWorkflow(store, Casework(store))
    analysis = workflow.analyse({"image_path": "/nonexistent/image.raw"})
    assert analysis["provenance"] == "UNAVAILABLE"
    assert "Nothing should be concluded" in analysis["provenance_statement"]


# --- file and disk evidence ---------------------------------------------------
@pytest.mark.parametrize("header, expected", [
    (b"", "raw"),
    (b"EVF\x09\x0d\x0a\xff\x00", "ewf"),
    (b"QFI\xfb", "qcow"),
    (b"KDMV", "vmdk"),
    (b"conectix", "vhd"),
])
def test_a_container_is_identified_from_its_own_header(tmp_path, header, expected):
    path = tmp_path / "image.bin"
    path.write_bytes(header + b"\x00" * 512)
    fmt, detail = identify_container(path)
    assert fmt == expected
    assert detail


def test_an_unextractable_container_is_preserved_and_says_so(store, tmp_path):
    """JOCKY does not parse forensic containers. It must say that, not fail."""
    casework = Casework(store)
    image = tmp_path / "evidence.E01"
    image.write_bytes(b"EVF\x09\x0d\x0a\xff\x00" + b"\x00" * 512)
    record = casework.register_evidence({"path": str(image), "source_type": "disk_image"})
    assert record["acquisition_status"] == "HASHED"
    assert record["container_format"] == "ewf"
    assert "not extract" in record["format_detail"]
    assert record["sha256"], "the container's own digest must be kept"


# --- evidence package ---------------------------------------------------------
@pytest.fixture
def package():
    report = {
        "investigation_id": "inv-1", "report_id": "rep-1",
        "schema_version": REPORT_SCHEMA_VERSION,
        "investigation": {"title": "Test", "case_id": "CASE-1", "started_at": "t"},
        "versions": versions(),
        "activity": {"groups": []}, "artifacts": [], "findings": [], "threads": [],
        "record_counts": {"artifacts": 0},
        "recognition": {"recognition_version": 1},
        "historical_execution": {"platform": "Linux", "sources": [
            {"name": "shell history", "status": "AVAILABLE", "detail": "read"}]},
    }
    return build_package(
        report=report, case={"id": "CASE-1", "title": "Test case", "examiner": "R"},
        endpoints=[{"id": "EP-1", "name": "lab-1", "hostname": "lab-1", "platform": "Linux",
                    "authorization_reference": "W/1"}],
        evidence_sources=[{"id": "EV-1", "sha256": "a" * 64, "verification_state": "VERIFIED",
                           "processing_status": "REGISTERED", "integrity_events": [{}]}],
        programs=[{"id": "P-1", "platform": "linux", "ir_version": 1, "plan_version": 1}],
        audit_events=[{"action": "case.created"}],
        routine={"groups": []}, case_summary={"statements": []}, narrative=[], briefs=[])


def test_the_package_describes_itself(package):
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("MANIFEST.json"))
    assert manifest["case"]["id"] == "CASE-1"
    assert manifest["investigation"]["id"] == "inv-1"
    assert manifest["versions"]["database_schema"] == DATABASE_SCHEMA_VERSION
    assert manifest["endpoints"][0]["name"] == "lab-1"
    assert manifest["evidence_sources"][0]["sha256"] == "a" * 64
    assert manifest["collectors"]["sources"][0]["status"] == "AVAILABLE"
    assert manifest["programs"][0]["ir_version"] == 1


def test_every_file_in_the_package_is_hashed(package):
    """No member may be in the archive without a digest, or the reverse."""
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("MANIFEST.json"))
        names = set(archive.namelist()) - {"MANIFEST.json"}
    assert {entry["name"] for entry in manifest["files"]} == names
    for entry in manifest["files"]:
        assert len(entry["sha256"]) == 64


def test_a_package_verifies_against_its_own_manifest(package):
    result = verify_package(package)
    assert result["verified"] is True
    assert result["files_checked"] == len(
        json.loads(zipfile.ZipFile(io.BytesIO(package)).read("MANIFEST.json"))["files"])


def test_an_altered_package_fails_verification(package):
    """The point of the digests: alteration has to be detectable.

    The member to alter is taken from the manifest rather than named here, so a
    renamed file cannot make this pass by altering nothing -- which is exactly
    what happened when the package layout moved evidence into subdirectories.
    """
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("MANIFEST.json"))
    target_name = next(entry["name"] for entry in manifest["files"]
                       if entry["name"].endswith(".json"))

    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(package)) as source:
        with zipfile.ZipFile(buffer, "w") as target:
            for name in source.namelist():
                data = source.read(name)
                if name == target_name:
                    data = b'[{"title": "a finding nobody made"}]'
                target.writestr(name, data)

    result = verify_package(buffer.getvalue())
    assert result["verified"] is False
    assert result["mismatched"] == [target_name]
    assert "altered since export" in result["detail"]


def test_the_package_explains_what_a_digest_does_not_prove(package):
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        readme = archive.read("README.txt").decode()
        manifest = json.loads(archive.read("MANIFEST.json"))
    assert "establishes nothing about the examined machine" in manifest["integrity"]
    assert "not a verdict" in manifest["not_a_verdict"].lower()
    assert "WHAT THIS PACKAGE IS NOT" in readme
