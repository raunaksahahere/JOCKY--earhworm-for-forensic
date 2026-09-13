"""
Windows historical execution collection.

Every test here drives the collectors with recorded fixtures in the shape the
real sources produce. None of it has been executed against a real Windows host:
these tests establish that parsing, normalisation and status reporting behave
as specified, not that the telemetry was collected from Windows in practice.
"""
from datetime import timezone

import pytest

from analysis import execution_windows as windows
from analysis.execution_model import (
    AVAILABLE, CollectionWindow, HISTORICAL_EVIDENCE, NOT_AVAILABLE, NOT_ENABLED,
    PERMISSION_DENIED,
)
from tests.fixtures import telemetry as fixture


@pytest.fixture
def window():
    return CollectionWindow(fixture.at(-60), fixture.at(600), 11)


@pytest.fixture(autouse=True)
def pretend_windows(monkeypatch):
    """The collectors refuse to run off-platform; the parsing still must work."""
    monkeypatch.setattr(windows, "is_windows", lambda: True)


def test_off_windows_every_source_reports_not_available(window, monkeypatch):
    monkeypatch.setattr(windows, "is_windows", lambda: False)

    sources, events = windows.collect(window)

    assert events == []
    assert {source["status"] for source in sources} == {NOT_AVAILABLE}
    assert all("Not a Windows host" in source["detail"] for source in sources)


def test_security_4688_is_normalized(window):
    runner = fixture.channel_runner({"Security": fixture.SECURITY_4688})

    source, events = windows.collect_process_creation(window, runner=runner)

    assert source["status"] == AVAILABLE and len(events) == 2
    cmd = events[0]
    assert cmd["executable"] == r"C:\Windows\System32\cmd.exe"
    assert cmd["pid"] == 0x4d2 and cmd["parent_pid"] == 0x1a4
    assert cmd["parent_process"] == r"C:\Windows\explorer.exe"
    assert cmd["user"] == "WORKSTATION\\analyst"
    assert cmd["classification"] == HISTORICAL_EVIDENCE
    assert cmd["source_record_id"] == "5001"


def test_4688_explains_a_missing_command_line(window):
    runner = fixture.channel_runner({"Security": fixture.SECURITY_4688})

    _source, events = windows.collect_process_creation(window, runner=runner)

    without = events[0]
    assert "is not enabled on this host" in without["unavailable"]["command_line"]


def test_4688_command_lines_are_opt_in_and_redacted(window):
    runner = fixture.channel_runner({"Security": fixture.SECURITY_4688})

    _source, events = windows.collect_process_creation(
        window, runner=runner, include_command_lines=True)

    stage = next(event for event in events if "stage.exe" in (event["executable"] or ""))
    assert "Hunter2" not in stage["command_line"]
    assert "[redacted]" in stage["command_line"]


def test_audit_policy_off_is_not_enabled_not_a_failure(window):
    runner = fixture.channel_runner({"Security": ("AVAILABLE", "")})

    source, events = windows.collect_process_creation(window, runner=runner)

    assert source["status"] == NOT_ENABLED and events == []
    assert "Audit Process Creation" in source["detail"]
    assert "does not change audit policy" in source["detail"]


def test_security_channel_permission_denied(window):
    runner = fixture.channel_runner({"Security": (PERMISSION_DENIED, "")})

    source, _events = windows.collect_process_creation(window, runner=runner)

    assert source["status"] == PERMISSION_DENIED
    assert "administrative rights" in source["detail"]


def test_sysmon_carries_parent_image_and_sha256(window):
    runner = fixture.channel_runner({"Microsoft-Windows-Sysmon/Operational": fixture.SYSMON_1})

    source, events = windows.collect_sysmon(window, runner=runner)

    assert source["status"] == AVAILABLE
    event = events[0]
    assert event["parent_process"] == r"C:\Windows\System32\cmd.exe"
    assert event["hash"] == "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
    assert event["interpreter"] == "powershell.exe"


def test_sysmon_absent_is_reported_as_not_installed(window):
    source, events = windows.collect_sysmon(window, runner=fixture.channel_runner({}))

    assert source["status"] == NOT_AVAILABLE and events == []


def test_powershell_script_block_is_redacted_and_qualified(window):
    runner = fixture.channel_runner({"Microsoft-Windows-PowerShell/Operational": fixture.POWERSHELL_4104})

    source, events = windows.collect_powershell(window, runner=runner)

    assert source["status"] == AVAILABLE
    event = events[0]
    assert "abc123secret" not in event["command_line"]
    assert "does not carry its outcome" in event["evidence_strength"]


def test_prefetch_metadata_only(window, tmp_path, monkeypatch):
    import os
    from datetime import datetime
    entry = tmp_path / "STAGE.EXE-A1B2C3D4.pf"
    entry.write_bytes(b"MAM\x04compressed-body-not-parsed")
    stamp = fixture.at(5).timestamp()
    os.utime(entry, (stamp, stamp))

    source, events = windows.collect_prefetch(window, directory=str(tmp_path))

    assert source["status"] == AVAILABLE and len(events) == 1
    event = events[0]
    assert event["process_name"] == "STAGE.EXE"
    assert "has run on this volume at least once" in event["evidence_strength"]
    # The body is never parsed, so no full path and no per-run history.
    assert event["unavailable"]["executable"]
    assert event["unavailable"]["command_line"]


def test_prefetch_missing_directory_is_not_enabled(window, tmp_path):
    source, events = windows.collect_prefetch(window, directory=str(tmp_path / "absent"))

    assert source["status"] == NOT_ENABLED and events == []
    assert "commonly disabled" in source["detail"]


def test_userassist_decodes_rot13_and_filetime(window):
    registry = fixture.FakeRegistry(fixture.userassist_tree())

    source, events = windows.collect_userassist(window, registry=registry)

    assert source["status"] == AVAILABLE and len(events) == 1
    event = events[0]
    assert event["executable"] == r"C:\Users\analyst\Downloads\report.exe"
    assert event["run_count"] == 3
    assert event["timestamp"].startswith(fixture.at(12).astimezone(timezone.utc).isoformat()[:16])


def test_userassist_ignores_undersized_values(window):
    registry = fixture.FakeRegistry(fixture.userassist_tree())

    _source, events = windows.collect_userassist(window, registry=registry)

    assert all("too-short" not in event["source_record_id"] for event in events)


def test_userassist_absent_key_is_not_available(window):
    source, events = windows.collect_userassist(window, registry=fixture.FakeRegistry({}))

    assert source["status"] == NOT_AVAILABLE and events == []


def test_full_windows_collection_merges_sources(window, tmp_path):
    runner = fixture.channel_runner({
        "Security": fixture.SECURITY_4688,
        "Microsoft-Windows-Sysmon/Operational": fixture.SYSMON_1,
        "Microsoft-Windows-PowerShell/Operational": fixture.POWERSHELL_4104,
    })

    sources, events = windows.collect(
        window, runner=runner, prefetch_directory=str(tmp_path / "absent"),
        registry=fixture.FakeRegistry(fixture.userassist_tree()))

    names = {source["name"]: source["status"] for source in sources}
    assert names["Windows Security 4688"] == AVAILABLE
    assert names["Sysmon Event 1"] == AVAILABLE
    assert names["PowerShell operational log"] == AVAILABLE
    assert names["Windows Prefetch"] == NOT_ENABLED
    assert names["UserAssist"] == AVAILABLE
    assert len(events) == 5


def test_filetime_conversion_rejects_nonsense():
    assert windows.filetime_to_iso(0) is None
    assert windows.filetime_to_iso(2 ** 63) is None
    assert windows.filetime_to_iso(133000000000000000).startswith("2022-")
