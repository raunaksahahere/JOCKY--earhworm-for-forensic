"""Investigator assessments, and the immutability of the machine's conclusion.

The rule: an investigator may record what they think, and it is stored beside
what JOCKY concluded, never over it. A record that lost the machine's original
classification when an investigator disagreed would be a record of the
disagreement's outcome rather than of the disagreement.
"""
import pytest

from backend.paths import Paths
from backend.service import ServiceError, Workstation
from backend.storage import Store, encode, identifier, now


@pytest.fixture
def service(tmp_path):
    built = Workstation(Store(Paths.resolve(str(tmp_path / "workspace"))))
    try:
        yield built
    finally:
        built.close()


@pytest.fixture
def investigation(service):
    case = service.create_case({"title": "Assessment test"})
    evidence_id = identifier()
    with service.store.transaction() as db:
        db.execute("INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?)",
                   (evidence_id, case["id"], None, "EXECUTION HISTORY", "journal", now(),
                    "completed", encode({})))
        db.execute(
            "INSERT INTO execution_events (id,investigation_id,evidence_id,source,timestamp,"
            " process_name,classification,collection_status,payload,reference,triage,"
            " investigator_priority,priority_score) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (identifier(), case["id"], evidence_id, "journal", now(), "curl",
             "HISTORICAL_EVIDENCE", "AVAILABLE", encode({}), "CMD-0001",
             "POTENTIALLY_HARMFUL", "PRIORITY_1", 5))
    return case


def test_an_assessment_is_recorded_with_the_machines_conclusion(service, investigation):
    recorded = service.assess(investigation["id"], {
        "subject_type": "activity", "subject_id": "CMD-0001",
        "assessment": "ACCEPT_AS_ROUTINE", "note": "Our own deployment script."})
    assert recorded["assessment"] == "ACCEPT_AS_ROUTINE"
    assert recorded["machine_classification"] == "POTENTIALLY_HARMFUL"
    assert recorded["machine_priority"] == "PRIORITY_1"
    assert recorded["author"]


def test_the_machine_classification_is_untouched_by_an_assessment(service, investigation):
    service.assess(investigation["id"], {
        "subject_type": "activity", "subject_id": "CMD-0001", "assessment": "ACCEPT_AS_ROUTINE"})
    row = service.store.rows(
        "SELECT triage, investigator_priority FROM execution_events WHERE reference=?",
        ("CMD-0001",))[0]
    assert row["triage"] == "POTENTIALLY_HARMFUL", "the machine's conclusion must be immutable"
    assert row["investigator_priority"] == "PRIORITY_1"


def test_assessments_accumulate_rather_than_overwrite(service, investigation):
    for assessment in ("KEEP_FOR_REVIEW", "MARK_AS_RELEVANT", "ACCEPT_AS_ROUTINE"):
        service.assess(investigation["id"], {
            "subject_type": "activity", "subject_id": "CMD-0001", "assessment": assessment})
    recorded = service.assessments(investigation["id"], subject_id="CMD-0001")
    assert len(recorded) == 3, "an earlier judgement is part of the record too"
    assert recorded[0]["assessment"] == "ACCEPT_AS_ROUTINE", "newest first"


@pytest.mark.parametrize("assessment", ["ACCEPT_AS_ROUTINE", "KEEP_FOR_REVIEW", "MARK_AS_RELEVANT"])
def test_each_supported_assessment_is_accepted(service, investigation, assessment):
    assert service.assess(investigation["id"], {
        "subject_type": "activity", "subject_id": "CMD-0001",
        "assessment": assessment})["assessment"] == assessment


def test_an_unknown_assessment_is_refused(service, investigation):
    with pytest.raises(ServiceError) as error:
        service.assess(investigation["id"], {
            "subject_type": "activity", "subject_id": "CMD-0001", "assessment": "LOOKS_FINE"})
    assert "ACCEPT_AS_ROUTINE" in str(error.value)


def test_an_assessment_needs_a_subject(service, investigation):
    with pytest.raises(ServiceError):
        service.assess(investigation["id"], {"assessment": "KEEP_FOR_REVIEW"})


def test_an_assessment_reaches_the_audit_trail(service, investigation):
    service.assess(investigation["id"], {
        "subject_type": "activity", "subject_id": "CMD-0001", "assessment": "MARK_AS_RELEVANT"})
    actions = [entry["action"] for entry in service.casework.audit_trail()]
    assert "assessment.recorded" in actions


def test_an_assessment_of_an_unknown_subject_records_no_machine_conclusion(service, investigation):
    """Better an empty field than a fabricated one."""
    recorded = service.assess(investigation["id"], {
        "subject_type": "activity", "subject_id": "CMD-9999", "assessment": "KEEP_FOR_REVIEW"})
    assert recorded["machine_classification"] is None
