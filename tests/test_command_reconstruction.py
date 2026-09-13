"""The command an investigator sees is the command the source recorded."""
import pytest

from analysis import execution_linux as linux
from analysis.execution_model import (
    COMMAND_HISTORY, EXACT, EXECUTABLE_ONLY, EXECUTION_EVIDENCE, SESSION_EVENT,
    STRONG, WEAK, CollectionWindow, describe_command, normalize_for_search,
)
from tests.fixtures import telemetry as fixture


@pytest.fixture
def window():
    return CollectionWindow(fixture.at(-60), fixture.at(600), 11)


def history_events(window, text, tmp_path):
    (tmp_path / ".bash_history").write_text(text)
    return linux.collect_shell_history(window, home=tmp_path)[1]


def test_full_shell_history_command_is_preserved(window, tmp_path):
    events = history_events(window, fixture.bash_history_with_times(), tmp_path)

    commands = [event["full_command_line"] for event in events]
    for original in fixture.COMMANDS:
        assert original in commands, f"{original} must survive verbatim"


def test_quoting_redirection_and_pipes_survive(window, tmp_path):
    original = 'sudo python3 "/home/user/test.py" --url "https://example.com/a" > /tmp/out.txt 2>&1'
    events = history_events(window, fixture.bash_history_with_times([original]), tmp_path)

    assert events[0]["full_command_line"] == original
    assert '"' in events[0]["full_command_line"]
    assert "> /tmp/out.txt 2>&1" in events[0]["full_command_line"]


def test_pipes_survive(window, tmp_path):
    original = "curl -fsSL https://example.com/install.sh | sudo bash"
    events = history_events(window, fixture.bash_history_with_times([original]), tmp_path)

    assert events[0]["full_command_line"] == original


def test_the_full_command_is_shown_not_only_the_executable(window, tmp_path):
    events = history_events(
        window, fixture.bash_history_with_times(["git clone https://github.com/example/project.git"]), tmp_path)

    event = events[0]
    assert event["process_name"] == "git"
    assert event["full_command_line"] == "git clone https://github.com/example/project.git"
    assert event["full_command_line"] != event["process_name"]
    assert event["command_reconstruction_status"] == EXACT


def test_a_missing_command_line_is_stated_not_invented(window):
    record = describe_command(command_line=None, executable="/usr/bin/python3",
                              process_name="python3", source="systemd journal")

    assert record["full_command_line"] is None
    assert record["command_reconstruction_status"] == EXECUTABLE_ONLY
    assert record["command_evidence_strength"] == WEAK


def test_no_placeholder_arguments_are_ever_produced(window):
    _record, events = linux.collect_journal(window, runner=fixture.journal_runner())

    for event in events:
        text = event["full_command_line"] or ""
        assert "unknown arguments" not in text
        assert "<" not in text or event["command_reconstruction_status"] == EXACT
        if event["full_command_line"] is None:
            assert "not available from this evidence" in event["unavailable"]["full_command_line"]


def test_shell_history_is_command_history_and_never_execution(window, tmp_path):
    events = history_events(window, fixture.bash_history_with_times(), tmp_path)

    assert events, "the fixture must produce records"
    for event in events:
        assert event["evidence_kind"] == COMMAND_HISTORY
        assert event["execution_confirmed"] is False
        assert "does not establish that it ran" in event["evidence_strength"]


def test_journal_records_stay_execution_evidence(window):
    _record, events = linux.collect_journal(window, runner=fixture.journal_runner())

    for event in events:
        assert event["evidence_kind"] == EXECUTION_EVIDENCE
        assert event["execution_confirmed"] is True


def test_sessions_are_neither_execution_nor_command_history(tmp_path):
    import struct
    from datetime import datetime, timedelta, timezone
    moment = datetime.now(timezone.utc) - timedelta(minutes=5)
    log = tmp_path / "wtmp"
    log.write_bytes(struct.pack(linux.UTMP_RECORD, 7, 1, b"tty1", b"t1", b"analyst", b"console",
                                0, 0, 0, int(moment.timestamp()), 0, 0, 0, 0, 0))

    _source, events = linux.collect_login_sessions(CollectionWindow.resolve(24), path=str(log))

    assert events[0]["evidence_kind"] == SESSION_EVENT
    assert events[0]["execution_confirmed"] is False


def test_journal_command_lines_are_exact_when_collected(window):
    _record, events = linux.collect_journal(
        window, runner=fixture.journal_runner(), include_command_lines=True)

    python = next(event for event in events if event["process_name"] == "python3")
    assert python["command_reconstruction_status"] == EXACT
    assert python["command_evidence_strength"] == STRONG
    assert python["full_command_line"].startswith("python3 deploy.py")


def test_the_raw_command_remains_available_for_audit(window, tmp_path):
    events = history_events(window, fixture.bash_history_with_times(["apt update"]), tmp_path)

    # Raw source metadata is retained alongside the reconstructed command.
    assert events[0]["raw"]["shell"] == "bash"
    assert events[0]["source_record_id"].endswith(":2")
    assert events[0]["provenance"].endswith(".bash_history")


@pytest.mark.parametrize("command,expected_in", [
    ("python3 /home/u/proj/script.py > /tmp/out", "script.py"),
    ("curl https://example.com/a.sh | sh", "URL"),
    ("git clone https://github.com/x/y.git", "URL"),
])
def test_the_search_form_is_additional_not_a_replacement(command, expected_in):
    normalized = normalize_for_search(command)

    assert expected_in in normalized
    assert normalized != command, "the search form is reduced"
