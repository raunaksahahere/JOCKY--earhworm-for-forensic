"""A program's FILTER applied to what that program collected.

The property under test is that a selection is a *view*: it answers the
program's question without removing, rewriting or re-hashing any evidence.
"""
import copy

from analysis.selection import select_for_program
from compiler.investigation import compile_program

REPORT = {
    "activity": {"groups": [
        {"full_command_line": "curl -s http://example.test/a.sh", "executable": "/usr/bin/curl",
         "process_name": "curl", "occurrences": 2,
         "classification": {"presentation_label": "Noteworthy", "priority_label": "Priority 2"},
         "records": [{"reference": "E-11", "user": "analyst"}]},
        {"full_command_line": "apt install nginx", "executable": "/usr/bin/apt",
         "process_name": "apt", "occurrences": 1, "classification": {},
         "records": [{"reference": "E-12", "user": "root"}]},
    ]},
    "artifacts": [
        {"reference": "A-1", "path": "/tmp/a.sh", "hash": "abc123"},
        {"reference": "A-2", "path": "/usr/share/doc/readme", "hash": "def456"},
    ],
    "supplementary": {
        "BROWSER": {"downloads": [{"url": "http://example.test/a.sh", "target_path": "/tmp/a.sh"}],
                    "history": []},
        "NETWORK": {"connections": [
            {"remote_address": "198.51.100.42", "process_name": "curl"},
            {"remote_address": "10.0.0.1", "process_name": "apt"}]},
    },
}


def _filters(program):
    return compile_program('CASE "c"\nCOLLECT PROCESSES\n' + program + "\n")["filters"]


def test_a_program_with_no_filter_selects_nothing_and_says_so():
    selection = select_for_program(REPORT, [])
    assert selection["applied"] is False
    assert selection["results"] == []
    assert "no FILTER" in selection["note"]


def test_a_filter_selects_across_every_surface():
    selection = select_for_program(REPORT, _filters('FILTER COMMAND CONTAINS "curl"'))
    assert selection["applied"] is True
    kinds = {result["kind"] for result in selection["results"]}
    assert "activity" in kinds
    assert selection["counts"]["activity"] == 1


def test_a_selected_activity_carries_its_evidence_reference():
    selection = select_for_program(REPORT, _filters('FILTER COMMAND CONTAINS "curl"'))
    activity = next(item for item in selection["results"] if item["kind"] == "activity")
    assert activity["id"] == "E-11", "a selected record must be traceable to its evidence"
    assert activity["priority"] == "Priority 2"


def test_a_compound_filter_narrows_the_way_the_program_reads():
    selection = select_for_program(
        REPORT, _filters('FILTER COMMAND CONTAINS "curl" AND NOT USER EQUALS "root"'))
    labels = [result["label"] for result in selection["results"] if result["kind"] == "activity"]
    assert labels == ["curl -s http://example.test/a.sh"]


def test_several_filters_narrow_together():
    selection = select_for_program(
        REPORT, _filters('FILTER PATH STARTS "/tmp"\nFILTER PATH ENDS ".sh"'))
    paths = [result["label"] for result in selection["results"] if result["kind"] == "artifact"]
    assert paths == ["/tmp/a.sh"]


def test_a_network_record_is_selected_by_address():
    selection = select_for_program(REPORT, _filters('FILTER ADDRESS EQUALS "198.51.100.42"'))
    assert [result["label"] for result in selection["results"] if result["kind"] == "network"] == [
        "curl -> 198.51.100.42"]


def test_a_browser_download_is_selected_by_url():
    selection = select_for_program(REPORT, _filters('FILTER URL CONTAINS "example.test"'))
    assert any(result["kind"] == "browser download" for result in selection["results"])


def test_a_selection_that_matches_nothing_is_empty_not_missing():
    selection = select_for_program(REPORT, _filters('FILTER COMMAND CONTAINS "nothing-here"'))
    assert selection["applied"] is True
    assert selection["total"] == 0
    assert selection["filters"] == ["COMMAND CONTAINS nothing-here"]


def test_selecting_never_alters_the_report():
    """Evidence is hashed whole; a view over it may not touch it."""
    before = copy.deepcopy(REPORT)
    select_for_program(REPORT, _filters('FILTER COMMAND CONTAINS "curl"'))
    assert REPORT == before


def test_the_selection_says_it_did_not_touch_the_evidence():
    selection = select_for_program(REPORT, _filters('FILTER COMMAND CONTAINS "curl"'))
    assert "No record was removed" in selection["note"]


def test_the_filters_are_reported_back_in_readable_form():
    selection = select_for_program(
        REPORT, _filters('FILTER PATH ONEOF ["/tmp/a.sh"] AND NOT USER EQUALS "root"'))
    assert selection["filters"] == ['(PATH ONEOF [/tmp/a.sh] AND NOT USER EQUALS root)']
