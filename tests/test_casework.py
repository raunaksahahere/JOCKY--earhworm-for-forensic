"""Cases, evidence sources, the audit trail and investigator notes.

The property under test throughout is that evidence is never silently altered:
a registration is never overwritten, a changed digest is reported rather than
corrected, and a failed acquisition is recorded rather than dropped.
"""
import pytest

from backend.casework import (
    FAILED, HASHED, MISMATCH, MISSING, VERIFIED, Casework, CaseworkError,
)
from backend.paths import Paths
from backend.storage import Store


@pytest.fixture
def casework(tmp_path):
    return Casework(Store(Paths.resolve(str(tmp_path / "workspace"))))


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / "sample.bin"
    path.write_bytes(b"forensic sample")
    return path


# --- cases --------------------------------------------------------------------
def test_a_case_is_created_and_read_back(casework):
    case = casework.create_case({"title": "Suspected staging", "examiner": "R. Saha"})
    assert case["status"] == "open"
    assert casework.get_case(case["id"])["title"] == "Suspected staging"


def test_a_case_needs_a_title(casework):
    with pytest.raises(CaseworkError):
        casework.create_case({"title": "   "})


def test_a_missing_case_is_a_404(casework):
    with pytest.raises(CaseworkError) as error:
        casework.get_case("CASE-NOPE")
    assert error.value.status == 404


def test_a_case_can_be_closed_and_reopened(casework):
    case = casework.create_case({"title": "x"})
    assert casework.close_case(case["id"])["status"] == "closed"
    assert casework.close_case(case["id"], reopen=True)["status"] == "open"


# --- evidence sources ---------------------------------------------------------
def test_registering_hashes_the_file_without_changing_it(casework, sample):
    before = sample.read_bytes()
    record = casework.register_evidence({"path": str(sample)})
    assert record["acquisition_status"] == HASHED
    assert record["verification_state"] == VERIFIED
    assert len(record["sha256"]) == 64
    assert sample.read_bytes() == before
    assert record["provenance"]["read_only"] is True


def test_evidence_needs_an_absolute_path(casework):
    with pytest.raises(CaseworkError):
        casework.register_evidence({"path": "relative/file.bin"})


def test_a_missing_file_is_recorded_not_rejected(casework):
    """A failed acquisition is itself a fact worth keeping."""
    record = casework.register_evidence({"path": "/nonexistent/evidence.raw"})
    assert record["acquisition_status"] == FAILED
    assert record["verification_state"] == MISSING
    assert record["integrity_events"][0]["outcome"] == "failed"


def test_registering_the_same_bytes_supersedes_rather_than_overwrites(casework, tmp_path):
    first = tmp_path / "one.bin"
    second = tmp_path / "two.bin"
    first.write_bytes(b"identical bytes")
    second.write_bytes(b"identical bytes")
    original = casework.register_evidence({"path": str(first)})
    duplicate = casework.register_evidence({"path": str(second)})
    assert duplicate["id"] != original["id"]
    assert duplicate["supersedes"] == original["id"]
    assert casework.get_evidence(original["id"])["sha256"] == original["sha256"], (
        "the original acquisition must survive a second one")


def test_verification_detects_a_changed_file(casework, sample):
    record = casework.register_evidence({"path": str(sample)})
    assert casework.verify_evidence(record["id"])["verification_state"] == VERIFIED
    sample.write_bytes(b"tampered")
    after = casework.verify_evidence(record["id"])
    assert after["verification_state"] == MISMATCH
    assert after["sha256"] == record["sha256"], "the registered digest must not be rewritten"
    assert after["integrity_events"][-1]["observed_sha256"] != record["sha256"]


def test_verification_of_a_deleted_file_reports_missing(casework, sample):
    record = casework.register_evidence({"path": str(sample)})
    sample.unlink()
    assert casework.verify_evidence(record["id"])["verification_state"] == MISSING


def test_evidence_can_be_attached_to_a_case(casework, sample):
    case = casework.create_case({"title": "x"})
    casework.register_evidence({"case_id": case["id"], "path": str(sample)})
    assert casework.get_case(case["id"])["evidence_source_count"] == 1
    assert len(casework.list_evidence(case_id=case["id"])) == 1


def test_evidence_for_an_unknown_case_is_refused(casework, sample):
    with pytest.raises(CaseworkError):
        casework.register_evidence({"case_id": "CASE-NOPE", "path": str(sample)})


# --- audit trail --------------------------------------------------------------
def test_every_action_reaches_the_audit_trail(casework, sample):
    case = casework.create_case({"title": "x"})
    record = casework.register_evidence({"case_id": case["id"], "path": str(sample)})
    casework.verify_evidence(record["id"])
    actions = [entry["action"] for entry in casework.audit_trail(case_id=case["id"])]
    assert actions == ["evidence.verified", "evidence.registered", "case.created"]


def test_the_audit_trail_records_an_actor_and_an_outcome(casework):
    casework.create_case({"title": "x"})
    entry = casework.audit_trail()[0]
    assert entry["actor"] and entry["outcome"] == "success" and entry["timestamp"]


def test_a_failed_action_is_audited_as_failed(casework):
    casework.register_evidence({"path": "/nonexistent/evidence.raw"})
    assert casework.audit_trail()[0]["outcome"] == "failed"


def test_the_audit_trail_holds_no_file_contents(casework, sample):
    """The trail records what was done, not what the evidence contained."""
    casework.register_evidence({"path": str(sample)})
    for entry in casework.audit_trail():
        assert "forensic sample" not in str(entry)


# --- notes --------------------------------------------------------------------
def test_a_note_is_stored_against_its_subject(casework):
    case = casework.create_case({"title": "x"})
    note = casework.add_note({"case_id": case["id"], "subject_type": "case",
                              "subject_id": case["id"], "body": "Imaged from the workstation."})
    assert note["body"] == "Imaged from the workstation."
    assert casework.list_notes(case_id=case["id"])[0]["id"] == note["id"]


def test_an_empty_note_is_refused(casework):
    with pytest.raises(CaseworkError):
        casework.add_note({"body": "   "})


def test_an_unknown_note_subject_is_refused(casework):
    with pytest.raises(CaseworkError):
        casework.add_note({"subject_type": "nonsense", "body": "text"})
