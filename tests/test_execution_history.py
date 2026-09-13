"""Linux historical execution collection, driven by deterministic fixtures."""
import os
from datetime import datetime, timedelta, timezone

import pytest

from analysis import execution_linux as linux
from analysis.execution_history import collect_execution_history, collector_for, finalize
from analysis.execution_model import (
    AVAILABLE, CollectionWindow, HISTORICAL_EVIDENCE, NOT_AVAILABLE, NOT_COLLECTED,
    NOT_ENABLED, PERMISSION_DENIED, redact_command_line,
)
from tests.fixtures import telemetry as fixture


@pytest.fixture
def window():
    # Wide enough to contain every fixture timestamp, which sit around BASE.
    return CollectionWindow(fixture.at(-60), fixture.at(600), 11)


def test_window_is_always_bounded():
    assert CollectionWindow.resolve().requested_hours == CollectionWindow.DEFAULT_HOURS
    assert CollectionWindow.resolve(3).to_dict()["bounded"] is True
    for invalid in (0, -1, CollectionWindow.MAX_HOURS + 1, "soon"):
        with pytest.raises(ValueError):
            CollectionWindow.resolve(invalid)


def test_journal_aggregates_one_event_per_process_instance(window):
    record, events = linux.collect_journal(window, runner=fixture.journal_runner())

    assert record["status"] == AVAILABLE
    by_executable = {event["executable"]: event for event in events}
    # Two records for pid 900 collapse into one instance with first/last seen.
    sshd = by_executable["/usr/sbin/sshd"]
    assert sshd["timestamp"] < sshd["last_seen"]
    assert sshd["journal_record_count"] == 2
    assert sshd["classification"] == HISTORICAL_EVIDENCE
    assert sshd["pid"] == 900


def test_journal_skips_malformed_records_and_says_so(window):
    record, events = linux.collect_journal(window, runner=fixture.journal_runner())

    # A record with no _EXE says nothing about execution; a record with an
    # unparseable timestamp cannot be placed; neither may become an event.
    assert all(event["executable"] for event in events)
    assert "/usr/bin/broken" not in {event["executable"] for event in events}
    assert "unreadable" in record["detail"]


def test_journal_never_claims_a_start_time(window):
    _record, events = linux.collect_journal(window, runner=fixture.journal_runner())

    for event in events:
        assert "not when it started" in event["evidence_strength"]
        assert event["unavailable"]["parent_pid"]


def test_journal_command_lines_are_opt_in_and_redacted(window):
    _record, without = linux.collect_journal(window, runner=fixture.journal_runner())
    python = next(event for event in without if event["process_name"] == "python3")
    assert python["command_line"] is None
    assert "opts in" in python["unavailable"]["command_line"]

    _record, with_lines = linux.collect_journal(
        window, runner=fixture.journal_runner(), include_command_lines=True)
    python = next(event for event in with_lines if event["process_name"] == "python3")
    assert "s3cr3tvalue" not in python["command_line"]
    assert "[redacted]" in python["command_line"]
    assert python["unavailable"]["command_line_secrets"]


@pytest.mark.parametrize("status,expected", [
    (NOT_AVAILABLE, NOT_AVAILABLE), (PERMISSION_DENIED, PERMISSION_DENIED)])
def test_journal_reports_why_it_could_not_read(window, status, expected):
    record, events = linux.collect_journal(window, runner=fixture.journal_runner(status=status))

    assert record["status"] == expected and events == []
    assert record["detail"]


def test_journal_truncation_is_reported(window, monkeypatch):
    monkeypatch.setattr(linux, "MAX_EVENTS_PER_SOURCE", 1)
    record, events = linux.collect_journal(window, runner=fixture.journal_runner())

    assert len(events) == 1
    assert record["truncated"] is True


def test_bash_history_with_timestamps(window, tmp_path):
    (tmp_path / ".bash_history").write_text(fixture.BASH_HISTORY_TIMESTAMPED)

    record, events = linux.collect_shell_history(window, home=tmp_path)

    assert record["status"] == AVAILABLE
    assert [event["timestamp"] is not None for event in events] == [True, True]
    assert "hunter2" not in "".join(event["command_line"] for event in events)
    assert all("does not establish that it ran" in e["evidence_strength"] for e in events)


def test_untimestamped_history_says_the_time_is_unknown(window, tmp_path):
    (tmp_path / ".bash_history").write_text(fixture.BASH_HISTORY_PLAIN)

    record, events = linux.collect_shell_history(window, home=tmp_path)

    assert len(events) == 3
    assert all(event["timestamp"] is None for event in events)
    assert "HISTTIMEFORMAT" in events[0]["unavailable"]["timestamp"]
    assert "no timestamp" in record["detail"]


def test_zsh_extended_history_and_secret_masking(window, tmp_path):
    (tmp_path / ".zsh_history").write_text(fixture.ZSH_HISTORY)

    _record, events = linux.collect_shell_history(window, home=tmp_path)

    assert [event["interpreter"] for event in events] == ["zsh", "zsh"]
    assert "abcdef123456" not in "".join(event["command_line"] for event in events)


def test_history_absent_is_not_a_failure(window, tmp_path):
    record, events = linux.collect_shell_history(window, home=tmp_path)

    assert record["status"] == NOT_AVAILABLE and events == []


def test_audit_log_records_execution_itself(window, tmp_path):
    log = tmp_path / "audit.log"
    log.write_text(fixture.AUDIT_LINES)

    record, events = linux.collect_audit_log(window, path=str(log))

    assert record["status"] == AVAILABLE
    assert {event["executable"] for event in events} == {"/usr/bin/curl", "/tmp/staged-installer"}
    staged = next(event for event in events if event["executable"] == "/tmp/staged-installer")
    assert staged["parent_pid"] == 2100
    assert "kernel audit subsystem recorded" in staged["evidence_strength"]
    assert "unparseable" in record["detail"]


def test_audit_log_absent_and_unreadable_are_distinguished(window, tmp_path):
    missing, _ = linux.collect_audit_log(window, path=str(tmp_path / "nope.log"))
    assert missing["status"] == NOT_AVAILABLE

    log = tmp_path / "audit.log"
    log.write_text(fixture.AUDIT_LINES)
    log.chmod(0o000)
    try:
        denied, _ = linux.collect_audit_log(window, path=str(log))
    finally:
        log.chmod(0o600)
    if os.geteuid() != 0:  # root bypasses the mode bits
        assert denied["status"] == PERMISSION_DENIED


def test_process_accounting_off_is_reported_not_enabled(window):
    record, events = linux.collect_process_accounting(window, paths=("/nonexistent/pacct",))

    assert record["status"] == NOT_ENABLED and events == []
    assert "does not make" in record["detail"]


def test_wtmp_layout_mismatch_is_reported_rather_than_decoded(window, tmp_path):
    log = tmp_path / "wtmp"
    log.write_bytes(b"\x00" * (linux.UTMP_SIZE + 7))

    record, events = linux.collect_login_sessions(window, path=str(log))

    assert record["status"] == NOT_AVAILABLE and events == []
    assert "not a multiple" in record["detail"]


def test_wtmp_decodes_session_records(tmp_path):
    import struct
    moment = datetime.now(timezone.utc) - timedelta(minutes=5)
    record_bytes = struct.pack(
        linux.UTMP_RECORD, 7, 4242, b"tty1", b"t1", b"analyst", b"console", 0, 0, 0,
        int(moment.timestamp()), 0, 0, 0, 0, 0)
    log = tmp_path / "wtmp"
    log.write_bytes(record_bytes)

    source, events = linux.collect_login_sessions(CollectionWindow.resolve(24), path=str(log))

    assert source["status"] == AVAILABLE
    assert events[0]["user"] == "analyst"
    assert events[0]["process_name"] == "session_open"
    assert "not that any particular program was executed" in events[0]["evidence_strength"]


def test_finalize_orders_dates_first_and_drops_duplicates(window):
    _record, events = linux.collect_journal(window, runner=fixture.journal_runner())
    undated = dict(events[0], timestamp=None, source_record_id="undated-1")
    duplicate = dict(events[0])

    result = finalize("Linux", window, [
        linux.collect_journal(window, runner=fixture.journal_runner())[0]], events + [undated, duplicate])

    assert result["duplicate_records_discarded"] == 1
    assert result["undated_event_count"] == 1
    assert result["events"][-1]["timestamp"] is None
    stamps = [event["timestamp"] for event in result["events"] if event["timestamp"]]
    assert stamps == sorted(stamps)


def test_no_available_source_is_reported_not_silently_empty(window):
    result = finalize("Linux", window, [
        linux.collect_process_accounting(window, paths=("/nonexistent",))[0]], [])

    assert result["telemetry_available"] is False
    assert result["classification"] == NOT_COLLECTED
    assert any("rests on current observation only" in warning for warning in result["warnings"])


def test_unsupported_platform_says_so():
    result = collect_execution_history(window_hours=1, platform_name="Plan9")

    assert result["telemetry_available"] is False
    assert result["sources"][0]["status"] == NOT_AVAILABLE
    assert collector_for("Linux").platform_name == "Linux"
    assert collector_for("Windows").platform_name == "Windows"


def test_cancellation_is_honoured(window):
    class Cancelled:
        def is_set(self):
            return True

    with pytest.raises(InterruptedError):
        linux.collect_journal(window, runner=fixture.journal_runner(), cancel=Cancelled())


@pytest.mark.real_telemetry
def test_real_host_collection_reports_every_source():
    result = collect_execution_history(window_hours=1)

    statuses = result["statistics"]["source_status"]
    assert set(statuses) >= {"systemd journal", "shell history", "kernel audit log",
                             "process accounting", "login sessions (wtmp)"}
    assert all(status in {AVAILABLE, NOT_AVAILABLE, NOT_ENABLED, PERMISSION_DENIED}
               for status in statuses.values())
    assert result["window"]["bounded"] is True


def test_redaction_masks_common_secret_shapes():
    for text, secret in [
        ("mysql --password=hunter2", "hunter2"),
        ("curl -H 'Authorization: Bearer abc123'", "abc123"),
        ("API_KEY=zzz ./run", "zzz"),
        ("tool --api-key qqq", "qqq"),
    ]:
        masked, changed = redact_command_line(text)
        assert changed and secret not in masked
    assert redact_command_line(None) == (None, False)
