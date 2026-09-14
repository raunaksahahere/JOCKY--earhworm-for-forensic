"""Review briefs, the routine report, search, assessments and the case summary.

The rule these check is the same one throughout: a statement that cannot name
the record it rests on does not get made.
"""
import json

import pytest

from analysis.activity import build_routine
from analysis.briefs import BriefError, build_brief
from analysis.case_summary import build_case_summary
from analysis.search import search
from backend.versions import versions


def _classification(presentation="FOR_REVIEW", category="NEEDS_REVIEW", priority="PRIORITY_2"):
    return {
        "category": category, "label": category, "presentation": presentation,
        "presentation_label": presentation.replace("_", " ").title(),
        "presentation_reason": "because the evidence says so",
        "investigator_priority": priority, "priority_label": f"{priority} label",
        "reason": "a stated reason", "signals": [], "why": ["a stated reason"],
        "unknowns": ["something unknown"], "recommended_action": "read the command",
    }


@pytest.fixture
def report():
    """One investigation's stored payload, small enough to reason about."""
    event = {
        "reference": "CMD-0001", "source": "shell history", "evidence_kind": "COMMAND_HISTORY",
        "execution_confirmed": False, "timestamp": "2026-03-14T09:00:00+00:00",
        "full_command_line": "bash /home/a/Downloads/tool.sh", "process_name": "bash",
        "executable": "/home/a/Downloads/tool.sh", "user": "analyst",
        "recognition": {"recognized": False, "confidence": "NONE", "basis_codes": [],
                        "limitations": ["Nothing accounts for this path."]},
    }
    confirmed = {
        "reference": "EXEC-0001", "source": "kernel audit log",
        "evidence_kind": "EXECUTION_EVIDENCE", "execution_confirmed": True,
        "timestamp": "2026-03-14T09:01:00+00:00", "process_name": "python3",
        "executable": "/usr/bin/python3", "full_command_line": "python3 --version",
        "user": "analyst",
        "recognition": {"recognized": True, "confidence": "HIGH",
                        "recognized_name": "python3-minimal", "version": "3.12.3",
                        "basis_codes": ["package_manager_ownership"],
                        "recognition_basis": ["The package manager owns this path."],
                        "limitations": ["Ownership is not integrity."]},
    }
    groups = [
        {"full_command_line": event["full_command_line"], "executable": event["executable"],
         "process_name": "bash", "evidence_kind": "COMMAND_HISTORY", "occurrences": 1,
         "records": [event], "sources": ["shell history"], "execution_confirmed": False,
         "classification": _classification(), "first_seen": event["timestamp"],
         "last_seen": event["timestamp"], "lead_id": None},
        {"full_command_line": confirmed["full_command_line"], "executable": "/usr/bin/python3",
         "process_name": "python3", "evidence_kind": "EXECUTION_EVIDENCE", "occurrences": 4,
         "records": [confirmed], "sources": ["kernel audit log"], "execution_confirmed": True,
         "classification": _classification("ROUTINE_RECOGNIZED",
                                           "NOT_HARMFUL_ON_AVAILABLE_EVIDENCE", "PRIORITY_3"),
         "first_seen": confirmed["timestamp"], "last_seen": confirmed["timestamp"],
         "lead_id": None},
    ]
    return {
        "investigation_id": "inv-1",
        "investigation": {"title": "Test", "case_id": "CASE-1"},
        "versions": versions(),
        "activity": {"groups": groups, "group_count": 2, "counts_by_kind": {}},
        "artifacts": [
            {"reference": "ART-0001", "path": "/home/a/Downloads/tool.sh", "filename": "tool.sh",
             "hash": "a" * 64, "size_bytes": 9182, "modified": "2026-03-14T08:58:00+00:00",
             "collection_status": "COLLECTED",
             "recognition": {"recognized": False, "confidence": "NONE", "basis_codes": [],
                             "limitations": ["Nothing accounts for this path."]}},
            {"reference": "ART-0002", "path": "/usr/bin/python3", "filename": "python3",
             "hash": "b" * 64, "collection_status": "COLLECTED",
             "recognition": confirmed["recognition"]},
        ],
        "findings": [
            {"reference": "F-0001", "title": "A downloaded file was run: tool.sh",
             "explanation": "It was downloaded and the same path appears in execution evidence.",
             "category": "download_executed", "severity": "medium", "triage": "NEEDS_REVIEW",
             "investigator_priority": "PRIORITY_2", "confidence": "single source",
             "why": "downloaded then run", "unknowns": ["What the file does."],
             "recommended_action": "Check the download source.",
             "evidence_references": [{"kind": "artifact", "id": "ART-0001"},
                                     {"kind": "execution_event", "id": "CMD-0001"}]},
        ],
        "threads": [
            {"thread_id": "THREAD-001", "title": "Tool installation and subsequent use",
             "why": "These records appear related: both reference 'tool'.",
             "shared_terms": ["tool"], "activity_count": 2, "record_count": 2,
             "commands": [event["full_command_line"], confirmed["full_command_line"]],
             "classification": "NEEDS_REVIEW", "priority": "PRIORITY_2",
             "evidence_references": ["CMD-0001", "EXEC-0001"], "unknowns": [],
             "execution_confirmed": True},
        ],
        "leads": [
            {"lead_id": "LEAD-001", "title": "Remote content piped into an interpreter",
             "priority": "PRIORITY_2", "priority_label": "Priority 2 — review",
             "classification": "POTENTIALLY_HARMFUL", "activity_count": 1, "record_count": 1,
             "commands": [event["full_command_line"]], "execution_confirmed": False,
             "why": ["remote content into an interpreter"], "unknowns": ["what it fetched"],
             "recommended_action": "Read the full command.",
             "evidence_references": ["CMD-0001"], "groups": [groups[0]]},
        ],
        "supplementary": {
            "BROWSER": {"downloads": [{"url": "http://example.invalid/tool.sh",
                                       "target_path": "/home/a/Downloads/tool.sh",
                                       "downloaded_at": "2026-03-14T08:57:00+00:00"}],
                        "history": []},
            "NETWORK": {"connections": [{"process_name": "python3",
                                         "remote_address": "198.51.100.9", "remote_port": 443,
                                         "status": "ESTABLISHED"}]},
            "USB": {"mounts": [], "events": [], "devices": []},
        },
        "limitations": [{"detail": "The kernel audit log was not available."}],
        "record_counts": {"distinct_activity": 2, "artifacts": 2, "findings": 1},
        "recognition": {"artifacts_examined": 2, "artifacts_recognized": 1,
                        "software": [{"name": "python3-minimal", "count": 1,
                                      "confidence": "HIGH"}]},
        "historical_execution": {"sources": [
            {"name": "shell history", "status": "AVAILABLE"},
            {"name": "kernel audit log", "status": "NOT_AVAILABLE"}]},
    }


# --- artifact brief -----------------------------------------------------------
def test_an_artifact_brief_answers_what_it_is_and_whether_it_ran(report):
    brief = build_brief(report, subject_type="artifact", subject_id="ART-0001")
    assert brief["subject"]["label"] == "/home/a/Downloads/tool.sh"
    assert brief["execution"]["state"] in {"CONFIRMED", "NOT ESTABLISHED", "CURRENT ONLY"}
    assert brief["recognition"]["state"] == "UNKNOWN"
    assert brief["summary"]
    assert brief["evidence_ids"], "a brief must cite the evidence it rests on"


def test_a_brief_cites_browser_evidence_only_when_a_record_names_the_path(report):
    linked = build_brief(report, subject_type="artifact", subject_id="ART-0001")
    browser = next(item for item in linked["sections"] if item["title"] == "Browser context")
    assert any("example.invalid" in line for line in browser["body"])
    assert browser["evidence"], "the browser claim must carry its citation"

    unlinked = build_brief(report, subject_type="artifact", subject_id="ART-0002")
    browser = next(item for item in unlinked["sections"] if item["title"] == "Browser context")
    assert "No browser download record names this path" in browser["body"][0]
    assert browser["evidence"] == []


def test_a_recognized_artifact_brief_states_what_recognition_does_not_prove(report):
    brief = build_brief(report, subject_type="artifact", subject_id="ART-0002")
    assert brief["recognition"]["state"] == "RECOGNIZED"
    assert any("published hash" in line for line in brief["unknown"])


def test_an_unknown_artifact_is_asked_about_rather_than_assumed(report):
    brief = build_brief(report, subject_type="artifact", subject_id="ART-0001")
    assert any("What this file is" in line for line in brief["unknown"])
    assert any("Establish what this file is" in step for step in brief["suggested_review"])


# --- finding, activity, lead, thread -----------------------------------------
def test_a_finding_brief_lists_the_evidence_the_finding_cites(report):
    brief = build_brief(report, subject_type="finding", subject_id="F-0001")
    assert set(brief["evidence_ids"]) == {"ART-0001", "CMD-0001"}
    assert brief["unknown"] == ["What the file does."]


def test_an_activity_brief_is_addressed_by_an_evidence_identifier(report):
    brief = build_brief(report, subject_type="activity", subject_id="CMD-0001")
    assert brief["subject"]["label"] == "bash /home/a/Downloads/tool.sh"
    assert brief["thread"] == "THREAD-001"


def test_an_activity_brief_reports_command_history_as_unestablished(report):
    brief = build_brief(report, subject_type="activity", subject_id="CMD-0001")
    assert brief["execution"]["state"] == "NOT ESTABLISHED"
    assert "Nothing in the collected evidence establishes that it ran" in \
        brief["execution"]["detail"]


def test_network_context_is_matched_on_the_process_not_on_timing(report):
    linked = build_brief(report, subject_type="activity", subject_id="EXEC-0001")
    network = next(item for item in linked["sections"] if item["title"] == "Network context")
    assert any("198.51.100.9" in line for line in network["body"])

    unlinked = build_brief(report, subject_type="activity", subject_id="CMD-0001")
    network = next(item for item in unlinked["sections"] if item["title"] == "Network context")
    assert "No socket record" in network["body"][0]
    assert "had already closed" in network["body"][0], (
        "the absence of a socket record must state its own limit")


def test_a_thread_brief_reads_without_opening_every_record(report):
    brief = build_brief(report, subject_type="thread", subject_id="THREAD-001")
    sequence = next(item for item in brief["sections"] if item["title"] == "Sequence")
    assert len(sequence["body"]) == 2
    assert set(brief["evidence_ids"]) >= {"CMD-0001", "EXEC-0001"}
    assert any("never what anyone intended" in line for line in brief["unknown"])


def test_a_lead_brief_shows_every_command_in_the_pattern(report):
    brief = build_brief(report, subject_type="lead", subject_id="LEAD-001")
    commands = next(item for item in brief["sections"]
                    if item["title"] == "Commands in this pattern")
    assert commands["body"] == ["bash /home/a/Downloads/tool.sh"]


def test_every_brief_carries_its_disclaimer_and_limitations(report):
    for kind, identifier in (("artifact", "ART-0001"), ("finding", "F-0001"),
                             ("activity", "CMD-0001"), ("thread", "THREAD-001"),
                             ("lead", "LEAD-001")):
        brief = build_brief(report, subject_type=kind, subject_id=identifier)
        assert "not a malware verdict" in brief["disclaimer"]
        assert brief["collection_limitations"]
        assert brief["unknown"], f"{kind} brief states nothing as unknown"


def test_an_unknown_subject_is_refused_with_the_available_kinds(report):
    with pytest.raises(BriefError) as error:
        build_brief(report, subject_type="nonsense", subject_id="X")
    assert "artifact" in str(error.value)
    with pytest.raises(BriefError):
        build_brief(report, subject_type="artifact", subject_id="ART-9999")


def test_a_brief_is_json_serializable(report):
    json.dumps(build_brief(report, subject_type="artifact", subject_id="ART-0001"))


# --- routine report -----------------------------------------------------------
def test_routine_grouping_collapses_repetition(report):
    routine = build_routine(report["activity"])
    assert routine["totals"]["activities"] == 1
    assert routine["totals"]["excluded"] == 1
    assert routine["groups"][0]["label"].startswith("python3-minimal")
    assert routine["groups"][0]["evidence_references"] == ["EXEC-0001"]


def test_routine_grouping_keeps_the_evidence_reachable(report):
    routine = build_routine(report["activity"])
    for group in routine["groups"]:
        assert group["evidence_references"], "a group with no evidence cannot be checked"
        assert group["basis"], "a group must say why it is routine"


def test_routine_is_never_described_as_safe(report):
    routine = build_routine(report["activity"])
    assert "not a guarantee" in routine["note"]
    assert "safe" not in routine["note"].lower().replace("safety", "")


# --- search -------------------------------------------------------------------
@pytest.mark.parametrize("term, expected_kinds", [
    ("tool.sh", {"activity", "artifact", "finding", "thread", "lead", "browser download"}),
    ("python3", {"activity", "artifact", "thread"}),
    ("a" * 64, {"artifact"}),
    ("example.invalid", {"browser download"}),
    ("198.51.100.9", {"network"}),
    ("THREAD-001", {"thread"}),
])
def test_search_reaches_every_surface(report, term, expected_kinds):
    found = search(report, term)
    assert expected_kinds <= set(found["counts"]), (
        f"searching {term!r} found {sorted(found['counts'])}")


def test_search_says_which_field_matched(report):
    found = search(report, "python3-minimal")
    artifact = next(item for item in found["results"] if item["kind"] == "artifact")
    assert "recognized software" in artifact["matched_fields"]


def test_search_finds_a_recognized_name_that_appears_in_no_command(report):
    """The whole point: "python3-minimal" is in no command line anywhere."""
    found = search(report, "python3-minimal")
    assert found["total"] >= 1


def test_a_short_search_term_is_refused_rather_than_matching_everything(report):
    assert search(report, "a")["results"] == []


def test_search_can_be_narrowed_to_one_kind(report):
    found = search(report, "tool.sh", kinds=["artifact"])
    assert set(found["counts"]) == {"artifact"}


# --- case summary -------------------------------------------------------------
def test_every_summary_statement_is_attributed_to_a_section(report):
    summary = build_case_summary(report)
    assert summary["statements"]
    for statement in summary["statements"]:
        assert statement["section"] and statement["statement"]


def test_the_summary_cites_evidence_where_it_names_records(report):
    summary = build_case_summary(report)
    cited = [item for item in summary["statements"] if item["evidence_ids"]]
    assert cited, "no statement carried evidence identifiers"
    assert set(summary["evidence_ids"]) >= {"CMD-0001"}


def test_the_summary_never_claims_the_machine_is_clean(report):
    """Reassurance may only appear as something the summary explicitly refuses.

    "the machine is clean" is allowed to occur -- the summary says it is *not*
    a finding that the machine is clean -- so the test checks the claim is not
    made, rather than that the words never appear.
    """
    summary = build_case_summary(report)
    text = (summary["text"] + " " + summary["closing"]).lower()
    assert "not a verdict" in text
    for phrase in ("machine is clean", "system is safe", "no threats", "nothing suspicious"):
        for occurrence in range(len(text)):
            index = text.find(phrase, occurrence)
            if index < 0:
                break
            preceding = text[max(0, index - 40):index]
            assert any(negation in preceding for negation in ("not ", "never ", "no ")), (
                f"the summary asserts {phrase!r} without negating it")


def test_an_absent_priority_one_is_stated_as_a_limit_not_a_result(report):
    report["leads"] = []
    summary = build_case_summary(report)
    statement = next(item for item in summary["statements"] if item["section"] == "priority")
    assert "not a finding that the machine is clean" in statement["statement"]


def test_unreadable_sources_are_named_in_the_summary(report):
    summary = build_case_summary(report)
    text = summary["text"]
    assert "kernel audit log" in text and "NOT_AVAILABLE" in text
