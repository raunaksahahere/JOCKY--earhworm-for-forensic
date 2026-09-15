"""How reports are packaged, and what that must not cost.

One claim is under test throughout: the investigator report's length reflects
how much there is to say, and raw evidence volume must not inflate it. The
evidence itself is unchanged -- every record that left the PDF is in the
package, and the tests count both sides to prove it.
"""
import io
import json
import zipfile

import pytest

from analysis.threads import MAX_REPORTED_THREADS, select_reported_threads
from backend.evidence_package import PACKAGE_VERSION, build_package, verify_package
from backend.pdf_report import (
    extract_text, page_count, render_full_pdf, render_investigator_pdf, render_pdf,
)
from backend.versions import versions

#: What the primary report is for. A normal investigation should land inside
#: this; a genuinely eventful one may exceed it, and that is not a failure --
#: the requirement is that evidence *volume* must not be what pushes it over.
PREFERRED_PAGES = 10


def _activity(count, *, kind="COMMAND_HISTORY", priority="PRIORITY_3",
              category="NOT_HARMFUL_ON_AVAILABLE_EVIDENCE"):
    """A lot of unremarkable activity, which is what a real day looks like."""
    groups = []
    for index in range(count):
        command = f"git status --porcelain --branch --long-option-{index}"
        groups.append({
            "full_command_line": command, "normalized_command": command,
            "executable": "/usr/bin/git", "process_name": "git", "evidence_kind": kind,
            "occurrences": 3, "execution_confirmed": kind == "EXECUTION_EVIDENCE",
            "command_reconstruction_status": "EXACT", "command_evidence_strength": "STRONG",
            "sources": ["bash history"], "first_seen": "2026-03-14T09:00:00+00:00",
            "last_seen": "2026-03-14T09:00:00+00:00", "lead_id": None,
            "records": [{"reference": f"CMD-{index:04d}", "source": "bash history",
                         "timestamp": "2026-03-14T09:00:00+00:00", "user": "analyst",
                         "evidence_kind": kind, "execution_confirmed": False,
                         "payload": {"raw": "preserved"}}],
            "classification": {
                "category": category, "label": category, "presentation": "ROUTINE_RECOGNIZED",
                "presentation_label": "Routine / recognized", "presentation_reason": "routine",
                "investigator_priority": priority, "priority_label": f"{priority} label",
                "reason": "Recognised as version control.", "signals": [], "why": [],
                "unknowns": [], "limitations": [], "recommended_action": None,
            },
        })
    return groups


def _thread(index, *, priority="PRIORITY_3", shape="related_activity", activities=2,
            confirmed=False):
    return {
        "thread_id": f"THREAD-{index:03d}", "shape": shape, "title": "Related activity",
        "why": "These records appear related.", "shared_terms": ["term"],
        "activity_count": activities, "record_count": activities * 2,
        "commands": [f"command {index}-{n}" for n in range(activities)],
        "execution": "not established", "execution_confirmed": confirmed,
        "classification": "NEEDS_REVIEW", "priority": priority, "priority_rank": 2,
        "sources": ["bash history"], "first_seen": None, "last_seen": None,
        "evidence_references": [f"CMD-{index:04d}"], "unknowns": [], "limitations": [],
        "recommended_action": None, "note": "A thread states that records appear related.",
    }


@pytest.fixture
def large_report():
    """An investigation with a lot of evidence and little to say about it."""
    groups = _activity(700)
    return {
        "report_id": "rep-1", "schema_version": 5, "created_at": "2026-03-14T10:00:00+00:00",
        "investigation_id": "inv-1", "status": "partially_completed",
        "investigation": {"title": "Volume test", "case_id": "CASE-1",
                          "started_at": "2026-03-14T09:00:00+00:00",
                          "completed_at": "2026-03-14T09:05:00+00:00"},
        "versions": versions(), "device": {"hostname": "test-host"},
        "summary": "A collection with a great deal of routine activity.",
        "conclusion": "Nothing reached the investigate-first tier.",
        "collection_window": {"start": "2026-03-13T09:00:00+00:00",
                              "end": "2026-03-14T09:00:00+00:00",
                              "requested_hours": 24.0, "maximum_hours": 2160, "bounded": True},
        "activity": {"groups": groups, "group_count": len(groups), "record_count": 2100,
                     "counts_by_kind": {"command_history_records": 2100}},
        "threads": [_thread(index) for index in range(1, 26)],
        "leads": [], "findings": [
            {"reference": f"F-{index:04d}", "title": f"Finding {index}",
             "explanation": "An explanation.", "category": "cat", "severity": "low",
             "triage": "NEEDS_REVIEW", "investigator_priority": "PRIORITY_3",
             "confidence": "single source", "why": "because", "unknowns": [],
             "evidence_references": [{"kind": "execution_event", "id": "CMD-0001"}]}
            for index in range(60)],
        "artifacts": [{"reference": f"ART-{index:04d}", "path": f"/usr/bin/tool-{index}",
                       "filename": f"tool-{index}", "hash": f"{index:064d}",
                       "collection_status": "COLLECTED", "size_bytes": 1024,
                       "recognition": {"recognized": True, "recognized_name": "pkg",
                                       "confidence": "HIGH", "basis_codes": ["x"]}}
                      for index in range(70)],
        "appendix_process_listing": [{"pid": index, "name": f"proc-{index}",
                                      "executable": f"/usr/bin/proc-{index}"}
                                     for index in range(400)],
        "evidence": [{"id": f"ev-{index}", "type": "EXECUTION HISTORY", "source": "journal",
                      "status": "completed", "collected_at": "2026-03-14T09:00:00+00:00",
                      "payload": {"versions": versions()}} for index in range(9)],
        "executions": [{"id": f"ex-{index}", "command": "EXECUTION HISTORY", "state": "completed",
                        "started_at": "2026-03-14T09:00:00+00:00", "versions": versions()}
                       for index in range(9)],
        "timeline": [{"timestamp": "2026-03-14T09:00:00+00:00", "state": "completed",
                      "detail": None}],
        "event_timeline": [{"timestamp": "2026-03-14T09:00:00+00:00", "kind": "x",
                            "detail": "y"} for _ in range(300)],
        "significant_events": {"note": "Bounded.", "groups": [], "events": []},
        "routine_summary": {"total": 700, "examples": ["git status"]},
        "review_reasons": [], "triage": {"counts": {}, "priorities": {}},
        "record_counts": {"command_history_records": 2100, "artifacts": 70, "findings": 60,
                          "distinct_activity": 700, "threads": 25, "session_records": 0,
                          "execution_source_records": 0},
        "limitations": ["The kernel audit log was not available."],
        "collection_limitations": [{"detail": "The kernel audit log was not available."}],
        "historical_execution": {"platform": "Linux", "event_count": 2100, "events": [],
                                 "telemetry_available": True,
                                 "sources": [{"name": "bash history", "status": "AVAILABLE",
                                              "event_count": 2100}]},
        "recognition": {"recognition_version": 1, "artifacts_examined": 70,
                        "artifacts_recognized": 68, "software": [{"name": "pkg", "count": 68,
                                                                  "confidence": "HIGH"}]},
        "supplementary": {"NETWORK": {"connections": [{"remote_address": "198.51.100.1"}]},
                          "BROWSER": {"downloads": [], "history": []}},
        "provenance": {"collector": "test"}, "unavailable_telemetry": [],
        "current_process_snapshot": {"statistics": {"processes_recorded": 400}},
        "lead_count": 0, "thread_count": 25,
    }


# --- the primary report -------------------------------------------------------
def test_the_investigator_report_stays_short_under_a_lot_of_evidence(large_report):
    """2,100 records, 700 activities, 25 threads, and little to report."""
    pages = page_count(render_investigator_pdf(large_report))
    assert pages <= PREFERRED_PAGES, (
        f"the investigator report is {pages} pages for an investigation with nothing much to "
        "say; evidence volume has inflated it")


def test_evidence_volume_does_not_change_the_report_length(large_report):
    """The real test of the claim: multiply the evidence, keep the narrative."""
    small = dict(large_report)
    small["activity"] = {**large_report["activity"], "groups": _activity(20), "group_count": 20}
    few = page_count(render_investigator_pdf(small))
    many = page_count(render_investigator_pdf(large_report))
    assert abs(many - few) <= 2, (
        f"{few} pages for 20 activities and {many} for 700: the report is growing with the "
        "evidence rather than with what there is to say")


def test_the_investigator_report_contains_no_appendices(large_report):
    text = extract_text(render_investigator_pdf(large_report))
    assert "Appendix" not in text, "the primary report must not carry appendices"


def test_the_investigator_report_carries_every_required_section(large_report):
    text = extract_text(render_investigator_pdf(large_report))
    for section in ("Investigation overview", "Investigation result", "Top investigative leads",
                    "Important investigation threads", "Significant events", "Routine activity",
                    "Uncertain activity", "Collection limitations",
                    "Evidence package and next steps"):
        assert section in text, f"missing section: {section}"


def test_the_investigator_report_says_where_the_rest_is(large_report):
    text = extract_text(render_investigator_pdf(large_report))
    assert "JOCKY_Evidence_Package" in text
    assert "none were discarded to" in text, (
        "the report must say the evidence was not trimmed to shorten it")
    assert "routine activity report" in text and "review brief" in text, (
        "the report must name the other two documents rather than leaving them to be discovered")


def test_the_investigator_report_records_which_build_produced_it(large_report):
    text = extract_text(render_investigator_pdf(large_report))
    assert versions()["application"] in text, (
        "a report that cannot say which build produced it is not evidence of anything")


def test_the_full_report_still_carries_every_appendix(large_report):
    """Nothing was removed. The long document is unchanged and still available."""
    text = extract_text(render_full_pdf(large_report))
    for appendix in ("Appendix A", "Appendix B", "Appendix C", "Appendix D", "Appendix E",
                     "Appendix F", "Appendix G", "Appendix H", "Appendix I"):
        assert appendix in text, f"the full report lost {appendix}"
    assert page_count(render_full_pdf(large_report)) > page_count(
        render_investigator_pdf(large_report))


def test_render_pdf_still_defaults_to_the_full_document(large_report):
    """Existing callers keep the behaviour they had.

    Compared by content rather than by bytes: two renders of the same payload
    differ in their document identifier, which is not a difference anyone cares
    about.
    """
    default = render_pdf(large_report)
    assert page_count(default) == page_count(render_full_pdf(large_report))
    assert "Appendix I" in extract_text(default)


# --- thread selection ---------------------------------------------------------
def test_only_a_few_threads_are_printed(large_report):
    selection = select_reported_threads(large_report["threads"])
    assert len(selection["reported"]) <= MAX_REPORTED_THREADS
    assert selection["counts"]["total"] == 25
    assert selection["withheld"] == 25 - len(selection["reported"])


def test_priority_one_and_two_threads_always_appear():
    threads = ([_thread(1, priority="PRIORITY_1")] + [_thread(2, priority="PRIORITY_2")]
               + [_thread(index) for index in range(3, 30)])
    reported = select_reported_threads(threads)["reported"]
    assert {thread["thread_id"] for thread in reported} >= {"THREAD-001", "THREAD-002"}


def test_a_thread_whose_only_claim_is_resemblance_is_counted_not_printed():
    threads = [_thread(index) for index in range(1, 21)]
    selection = select_reported_threads(threads)
    assert selection["counts"]["routine"] == 20
    assert selection["reported"] == []


def test_a_thread_that_names_a_behaviour_is_printed():
    threads = [_thread(1, shape="install_then_use")] + [_thread(2)]
    selection = select_reported_threads(threads)
    assert [thread["thread_id"] for thread in selection["reported"]] == ["THREAD-001"]
    assert selection["counts"]["noteworthy"] == 1


def test_the_thread_tally_accounts_for_every_thread():
    threads = ([_thread(1, priority="PRIORITY_1")] + [_thread(2, priority="PRIORITY_2")]
               + [_thread(3, shape="install_then_use")] + [_thread(index) for index in range(4, 15)])
    counts = select_reported_threads(threads)["counts"]
    assert (counts["priority_1"] + counts["priority_2"] + counts["noteworthy"]
            + counts["routine"]) == counts["total"]


def test_the_report_states_what_it_set_aside(large_report):
    text = extract_text(render_investigator_pdf(large_report))
    assert "Investigation threads" in text
    assert "further thread" in text, "the report must say how many threads it did not print"
    assert "Routine" in text and "Informational but noteworthy" in text, (
        "the tally must account for the threads that were not printed")


# --- the evidence package -----------------------------------------------------
@pytest.fixture
def package(large_report):
    return build_package(
        report=large_report,
        pdf=render_investigator_pdf(large_report), full_pdf=render_full_pdf(large_report),
        case={"id": "CASE-1", "title": "Volume test", "examiner": "R"},
        endpoints=[{"id": "EP-1", "name": "lab-1", "hostname": "lab-1", "platform": "Linux",
                    "authorization_reference": "W/1"}],
        evidence_sources=[{"id": "EV-1", "sha256": "a" * 64, "verification_state": "VERIFIED",
                           "processing_status": "REGISTERED", "integrity_events": []}],
        programs=[{"id": "P-1", "platform": "linux", "ir_version": 1, "plan_version": 1,
                   "source": 'CASE "x"'}],
        audit_events=[{"action": "case.created"}],
        routine={"groups": [], "totals": {"records": 2100}},
        case_summary={"statements": [{"section": "scope", "statement": "s",
                                      "evidence_ids": ["CMD-0001"]}]},
        narrative=[{"section": "scope", "statement": "s", "evidence_ids": ["CMD-0001"]}],
        briefs=[])


def test_the_package_carries_every_source_the_report_left_out(package):
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        names = set(archive.namelist())
    for required in ("evidence/command-history.json", "evidence/activity.json",
                     "evidence/processes.json", "evidence/artifacts.json",
                     "evidence/findings.json", "evidence/threads.json",
                     "evidence/timeline.json", "evidence/telemetry-sources.json",
                     "evidence/limitations.json", "evidence/recognition.json",
                     "evidence/network.json", "evidence/browser.json",
                     "provenance/evidence-sources.json", "provenance/endpoints.json",
                     "provenance/audit-trail.json", "provenance/programs.json",
                     "provenance/investigation.json", "analysis/case-summary.json",
                     "analysis/narrative.json", "analysis/routine-activity.json",
                     "report.json", "investigator-report.pdf", "full-report.pdf",
                     "MANIFEST.json", "README.txt"):
        assert required in names, f"the package is missing {required}"


def test_a_source_that_was_not_collected_gets_no_empty_file(package):
    """An empty file would imply a collection that did not happen."""
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        names = set(archive.namelist())
    assert "evidence/memory.json" not in names
    assert "evidence/usb.json" not in names


def test_no_record_is_lost_between_the_report_and_the_package(large_report, package):
    """Counted on both sides, because "nothing was removed" has to be checkable."""
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        activity = json.loads(archive.read("evidence/activity.json"))
        history = json.loads(archive.read("evidence/command-history.json"))
        artifacts = json.loads(archive.read("evidence/artifacts.json"))
        findings = json.loads(archive.read("evidence/findings.json"))
        threads = json.loads(archive.read("evidence/threads.json"))
        processes = json.loads(archive.read("evidence/processes.json"))

    assert len(activity["groups"]) == len(large_report["activity"]["groups"]) == 700
    assert len(history) == 700, "every command-history activity must survive the export"
    assert len(artifacts) == len(large_report["artifacts"]) == 70
    assert len(findings) == len(large_report["findings"]) == 60
    assert len(threads) == len(large_report["threads"]) == 25
    assert len(processes) == len(large_report["appendix_process_listing"]) == 400


def test_the_individual_records_survive_not_just_the_counts(large_report, package):
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        activity = json.loads(archive.read("evidence/activity.json"))
    stored = {record["reference"] for group in activity["groups"]
              for record in group["records"]}
    expected = {record["reference"] for group in large_report["activity"]["groups"]
                for record in group["records"]}
    assert stored == expected
    first = activity["groups"][0]["records"][0]
    assert first["payload"] == {"raw": "preserved"}, "the raw payload must survive"


# --- the manifest -------------------------------------------------------------
def test_the_manifest_answers_every_question_it_must(package):
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("MANIFEST.json"))

    assert manifest["package_version"] == PACKAGE_VERSION
    assert manifest["case"]["id"] == "CASE-1"
    assert manifest["investigation"]["id"] == "inv-1"
    assert manifest["endpoints"][0]["hostname"] == "lab-1"
    assert manifest["evidence_source_ids"] == ["EV-1"]
    assert manifest["exported_at"]

    period = manifest["collection_period"]
    assert period["start"] and period["end"] and period["bounded"] is True
    assert period["requested_hours"] == 24.0
    assert period["detail"], "the collection period must say what it bounds"

    applied = manifest["versions"]
    for key in ("application", "database_schema", "report_schema", "package", "ir", "plan",
                "detection_ruleset", "recognition"):
        assert applied.get(key) is not None, f"the manifest does not record {key}"

    assert manifest["collectors"]["platform"] == "Linux"
    assert manifest["collectors"]["versions"], "no collector recorded its version"
    assert manifest["collectors"]["sources"][0]["status"] == "AVAILABLE"
    assert manifest["record_counts"]
    assert manifest["files"]


def test_every_member_is_hashed_and_the_package_verifies(package):
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("MANIFEST.json"))
        names = set(archive.namelist()) - {"MANIFEST.json"}
    assert {entry["name"] for entry in manifest["files"]} == names
    result = verify_package(package)
    assert result["verified"] is True
    assert result["files_checked"] == len(names)


def test_an_altered_member_fails_verification_naming_itself(package):
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(package)) as source:
        with zipfile.ZipFile(buffer, "w") as target:
            for name in source.namelist():
                data = source.read(name)
                if name == "evidence/findings.json":
                    data = b'[{"title": "a finding nobody made"}]'
                target.writestr(name, data)
    result = verify_package(buffer.getvalue())
    assert result["verified"] is False
    assert result["mismatched"] == ["evidence/findings.json"]


def test_the_readme_says_what_is_not_in_the_package(package):
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        readme = archive.read("README.txt").decode()
    assert "WHAT IS NOT IN HERE" in readme
    assert "routine activity report" in readme
    assert "not a verdict" in readme.lower()


def test_statements_in_the_report_keep_their_evidence_references(large_report, package):
    """Shortening the presentation must not cost the traceability."""
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        narrative = json.loads(archive.read("analysis/narrative.json"))
        summary = json.loads(archive.read("analysis/case-summary.json"))
    assert narrative and narrative[0]["evidence_ids"] == ["CMD-0001"]
    assert summary["statements"][0]["evidence_ids"] == ["CMD-0001"]

    text = extract_text(render_investigator_pdf(large_report))
    assert "CMD-" in text, "the report must still print evidence identifiers"
