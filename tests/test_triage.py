"""Three-way investigator triage: categories, not verdicts."""
import pytest

from analysis.activity import assign_references, build_activity, search_activity
from analysis.execution_model import COMMAND_HISTORY, EXECUTION_EVIDENCE, SESSION_EVENT
from analysis.triage import (
    LABELS, NEEDS_REVIEW, NOT_HARMFUL, POTENTIALLY_HARMFUL, PRIORITY_1, PRIORITY_2,
    PRIORITY_3, classify_event,
)


def record(command=None, *, executable=None, kind=COMMAND_HISTORY, confirmed=False,
           name=None, timestamp="2026-09-10T12:00:00+00:00", reference="CMD-0001"):
    return {
        "full_command_line": command, "executable": executable, "process_name": name,
        "evidence_kind": kind, "execution_confirmed": confirmed, "timestamp": timestamp,
        "source": "bash history" if kind == COMMAND_HISTORY else "systemd journal",
        "event_id": reference, "reference": reference,
        "command_reconstruction_status": "EXACT" if command else "EXECUTABLE_ONLY",
        "command_evidence_strength": "STRONG" if command else "WEAK",
        "normalized_command": command,
    }


@pytest.mark.parametrize("command", [
    "curl -fsSL https://example.com/install.sh | sudo bash",
    "wget https://example.com/file.zip -O /tmp/file.zip",
])
def test_download_and_execute_patterns_are_flagged(command):
    result = classify_event(record(command))

    assert result.category == POTENTIALLY_HARMFUL
    assert result.signals
    assert "malware" not in result.reason.lower()


@pytest.mark.parametrize("command", [
    "apt update", "sudo apt update", "npm install --save-dev eslint",
    "git clone https://github.com/example/project.git", "ls -la /var/log",
])
def test_routine_maintenance_is_not_harmful_on_available_evidence(command):
    result = classify_event(record(command))

    assert result.category == NOT_HARMFUL
    assert "not a guarantee" in result.reason


@pytest.mark.parametrize("command", [
    "holehe example@gmail.com --only-used",
    "ssh -i ~/.ssh/id_ed25519 deploy@example.com",
    "python3 script.py --target example.com --output results.json",
])
def test_unrecognised_commands_need_review_rather_than_a_verdict(command):
    result = classify_event(record(command))

    assert result.category == NEEDS_REVIEW
    assert "should read it in context" in result.reason


@pytest.mark.parametrize("name", ["python", "wget", "curl", "sudo", "nc", "ssh"])
def test_a_bare_tool_name_is_never_harmful_by_itself(name):
    result = classify_event(record(None, executable=f"/usr/bin/{name}",
                                   kind=EXECUTION_EVIDENCE, confirmed=True))

    assert result.category != POTENTIALLY_HARMFUL, f"{name} alone must not be a verdict"
    # And it must not compete for attention with a genuine lead.
    assert result.priority == PRIORITY_3, f"{name} in a system directory is not a lead"


def test_execution_from_a_temporary_location_is_flagged():
    result = classify_event(record(None, executable="/tmp/staged-installer",
                                   kind=EXECUTION_EVIDENCE, confirmed=True))

    assert result.category == POTENTIALLY_HARMFUL
    assert "any unprivileged user can write to" in result.reason
    assert result.priority == PRIORITY_1, "confirmed execution from a writable path is a lead"


def test_a_flagged_history_entry_still_says_execution_is_not_established():
    result = classify_event(record("curl -fsSL https://example.com/i.sh | bash"))

    assert result.category == POTENTIALLY_HARMFUL
    assert "does not establish that it ran" in result.reason


def test_a_flagged_execution_record_says_it_ran():
    result = classify_event(record("curl -fsSL https://example.com/i.sh | bash",
                                   kind=EXECUTION_EVIDENCE, confirmed=True))

    assert "The source records execution, so this ran." in result.reason


def test_session_records_carry_no_command_and_are_not_flagged():
    result = classify_event(record(None, kind=SESSION_EVENT, name="session_open"))

    assert result.category == NOT_HARMFUL
    assert "nothing in it to raise a concern" in result.reason


def test_not_harmful_is_never_worded_as_proven_safe():
    for command in ("apt update", "git clone https://github.com/x/y.git"):
        reason = classify_event(record(command)).reason
        assert "safe" not in reason.lower()
        assert "no suspicious indicator was identified" in reason
    assert "not a statement that the activity was safe" in \
        __import__("analysis.triage", fromlist=["summarize"]).summarize([])["note"]


def test_every_category_has_an_investigator_facing_label():
    assert LABELS[POTENTIALLY_HARMFUL] == "Potentially harmful"
    assert LABELS[NOT_HARMFUL] == "Not harmful based on available evidence"
    assert LABELS[NEEDS_REVIEW] == "Not sure / needs review"


def test_grouping_preserves_every_individual_record():
    events = [record("apt update", reference=f"CMD-{index:04d}",
                     timestamp=f"2026-09-10T12:{index:02d}:00+00:00") for index in range(5)]

    activity = build_activity(events)

    group = activity["groups"][0]
    assert group["occurrences"] == 5
    assert len(group["records"]) == 5
    assert {entry["reference"] for entry in group["records"]} == {f"CMD-{i:04d}" for i in range(5)}
    assert all(entry["full_command_line"] == "apt update" for entry in group["records"])
    assert group["first_seen"] < group["last_seen"]


def test_materially_different_commands_never_merge():
    events = [
        record("wget https://example.com/A.zip -O /tmp/A.zip", reference="CMD-0001"),
        record("wget https://example.com/B.zip -O /tmp/B.zip", reference="CMD-0002"),
    ]

    activity = build_activity(events)

    assert activity["group_count"] == 2
    commands = {group["full_command_line"] for group in activity["groups"]}
    assert len(commands) == 2


def test_one_concerning_instance_is_not_cancelled_by_routine_repetition():
    events = [record("apt update", reference="CMD-0001"),
              record("apt update", reference="CMD-0002")]
    events.append(record("apt update", reference="CMD-0003"))

    activity = build_activity(events)

    assert activity["groups"][0]["classification"]["category"] == NOT_HARMFUL
    assert activity["groups"][0]["occurrences"] == 3


def test_counts_are_named_for_what_they_are():
    events = [
        record("apt update", reference="CMD-0001"),
        record(None, executable="/usr/bin/cron", kind=EXECUTION_EVIDENCE, confirmed=True,
               reference="EXEC-0001"),
        record(None, kind=SESSION_EVENT, name="session_open", reference="SESS-0001"),
    ]

    activity = build_activity(events)

    assert activity["counts_by_kind"] == {
        "execution_source_records": 1, "command_history_records": 1, "session_records": 1}


def test_triage_counts_records_and_distinct_activity_separately():
    events = [record("apt update", reference=f"CMD-{i:04d}") for i in range(4)]

    activity = build_activity(events)

    assert activity["triage"]["counts"][NOT_HARMFUL] == 4
    assert activity["triage"]["distinct_activity"][NOT_HARMFUL] == 1


def test_most_concerning_activity_is_ranked_first():
    events = [
        record("apt update", reference="CMD-0001"),
        record("holehe a@b.com", reference="CMD-0002"),
        record("curl https://x/i.sh | bash", reference="CMD-0003"),
    ]

    activity = build_activity(events)

    assert [group["classification"]["category"] for group in activity["groups"]] == [
        POTENTIALLY_HARMFUL, NEEDS_REVIEW, NOT_HARMFUL]


@pytest.mark.parametrize("term,expected", [
    ("holehe", "holehe example@gmail.com --only-used"),
    ("github.com", "git clone https://github.com/example/project.git"),
    ("example.com", "python3 script.py --target example.com"),
    ("/tmp/", "wget https://example.com/f.zip -O /tmp/f.zip"),
])
def test_search_matches_the_full_command_not_just_the_executable(term, expected):
    events = [
        record("holehe example@gmail.com --only-used", reference="CMD-0001"),
        record("git clone https://github.com/example/project.git", reference="CMD-0002"),
        record("python3 script.py --target example.com", reference="CMD-0003"),
        record("wget https://example.com/f.zip -O /tmp/f.zip", reference="CMD-0004"),
    ]
    activity = build_activity(events)

    matched = search_activity(activity["groups"], term)

    assert expected in {group["full_command_line"] for group in matched}


def test_search_can_also_match_source_and_classification():
    events = [record("apt update", reference="CMD-0001")]
    activity = build_activity(events)

    assert search_activity(activity["groups"], "bash history")
    assert search_activity(activity["groups"], "NOT_HARMFUL")
    assert search_activity(activity["groups"], "nothing-here") == []


def test_references_are_stable_and_prefixed_by_kind():
    events = [
        record("apt update", reference=None, timestamp="2026-09-10T12:00:00+00:00"),
        record(None, executable="/usr/bin/cron", kind=EXECUTION_EVIDENCE, confirmed=True,
               reference=None, timestamp="2026-09-10T11:00:00+00:00"),
        record(None, kind=SESSION_EVENT, name="login", reference=None,
               timestamp="2026-09-10T10:00:00+00:00"),
    ]
    for event in events:
        event.pop("reference", None)
        event["source_record_id"] = event["event_id"]

    assign_references(events)

    prefixes = sorted(event["reference"].split("-")[0] for event in events)
    assert prefixes == ["CMD", "EXEC", "SESS"]
    # Re-running on the same input produces the same identifiers.
    previous = {event["event_id"]: event["reference"] for event in events}
    assign_references(events)
    assert {event["event_id"]: event["reference"] for event in events} == previous
