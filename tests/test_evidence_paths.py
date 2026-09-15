"""Paths that came from evidence, not from this machine.

Two defects sat behind this module, both invisible on Linux and both fatal on
Windows. They are the reason it exists, so they are the first things tested.
"""
import os

import pytest

from analysis.correlation import correlate
from analysis.evidence_paths import basename, dirname, is_absolute, normalize, same_path


# --- what a path from a record means ------------------------------------------
@pytest.mark.parametrize("path, expected", [
    ("/usr/bin/curl", "/usr/bin/curl"),
    ("C:\\Windows\\System32\\cmd.exe", "C:/Windows/System32/cmd.exe"),
    ("C:/Windows/System32/cmd.exe", "C:/Windows/System32/cmd.exe"),
    ("/tmp//x///y", "/tmp/x/y"),
    ("/tmp/x/", "/tmp/x"),
    ("/", "/"),
    ("", ""),
    (None, ""),
])
def test_one_spelling_for_one_path(path, expected):
    assert normalize(path) == expected


def test_a_unc_share_keeps_its_leading_pair():
    assert normalize("\\\\server\\share\\file.bin") == "//server/share/file.bin"


@pytest.mark.parametrize("path", ["/usr/bin/curl", "C:\\Windows", "C:/Windows",
                                  "\\\\server\\share", "/"])
def test_an_absolute_path_is_absolute_on_any_platform(path):
    assert is_absolute(path) is True


@pytest.mark.parametrize("path", ["relative/path", "file.bin", "", None, "./x"])
def test_a_relative_path_is_not_resolved_by_guessing(path):
    """The working directory it was relative to is not in the evidence."""
    assert is_absolute(path) is False


@pytest.mark.parametrize("path, expected", [
    ("/usr/bin/curl", "curl"),
    ("C:\\Windows\\cmd.exe", "cmd.exe"),
    ("/tmp/x/", "x"),
    ("plain", "plain"),
])
def test_the_last_segment_splits_on_either_separator(path, expected):
    assert basename(path) == expected


@pytest.mark.parametrize("path, expected", [
    ("/usr/bin/curl", "/usr/bin"),
    ("C:\\Windows\\cmd.exe", "C:/Windows"),
    ("/x", "/"),
    ("plain", ""),
])
def test_the_leading_segments_are_reported(path, expected):
    assert dirname(path) == expected


def test_case_is_left_alone():
    """Two paths differing only in case are one file on Windows and two on
    Linux. The evidence does not say which host it came from, so neither does
    this."""
    assert normalize("/Usr/Bin") != normalize("/usr/bin")
    assert same_path("/usr/bin", "/usr/bin") is True
    assert same_path("/usr/bin", None) is False


def test_nothing_here_reads_the_filesystem_or_the_working_directory():
    """The regression that made this module necessary.

    os.path.abspath('/usr/bin/curl') on Windows returns D:\\usr\\bin\\curl,
    inventing a drive that was never in the evidence.
    """
    import inspect

    from analysis import evidence_paths

    # Code lines only: the module's own docstring names os.path.abspath to
    # explain why it is not used.
    code = [line for line in inspect.getsource(evidence_paths).splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    body = "\n".join(code[code.index('from __future__ import annotations'):])
    for forbidden in ("os.path", "os.getcwd", "abspath", "realpath", "Path("):
        assert forbidden not in body, f"evidence paths must not use {forbidden}"


# --- the join that broke ------------------------------------------------------
def _event(executable):
    return {"source": "kernel audit log", "source_record_id": "1", "executable": executable,
            "process_name": basename(executable), "evidence_kind": "EXECUTION_EVIDENCE",
            "execution_confirmed": True, "timestamp": "2026-03-14T09:00:00+00:00",
            "classification": "HISTORICAL_EVIDENCE", "reference": "EXEC-0001",
            "full_command_line": executable}


def _artifact(path):
    return {"path": path, "filename": basename(path), "collection_status": "COLLECTED",
            "hash": "a" * 64, "hash_algorithm": "SHA256", "reference": "ART-0001",
            "source": "test", "size_bytes": 1024, "indicators": [],
            "extension": None, "modified": "2026-03-14T08:00:00+00:00"}


@pytest.mark.parametrize("path", [
    "/usr/local/bin/vendor-agent",
    "C:\\Program Files\\Vendor\\agent.exe",
])
def test_execution_and_artifact_are_joined_whatever_host_they_came_from(path):
    """Evidence from a Linux endpoint is correlated on whatever workstation the
    investigator is using, which is what the multi-endpoint architecture is for.

    This is the defect: the join absolutized the evidence path against the
    analysing machine, so on Windows a Linux endpoint's paths were rewritten
    onto the local drive and matched nothing.
    """
    result = correlate(execution={"events": [_event(path)]},
                       artifacts={"artifacts": [_artifact(path)]}, processes={})
    matched = [finding for finding in result["findings"]
               if finding["category"] == "execution_artifact_matched"]
    assert matched, f"{path} did not correlate with its own artifact"
    assert basename(path) in matched[0]["title"]


def test_the_join_survives_a_difference_in_separator_only():
    result = correlate(
        execution={"events": [_event("C:\\Vendor\\agent.exe")]},
        artifacts={"artifacts": [_artifact("C:/Vendor/agent.exe")]}, processes={})
    assert any(finding["category"] == "execution_artifact_matched"
               for finding in result["findings"])


def test_two_different_paths_still_do_not_join():
    result = correlate(
        execution={"events": [_event("/usr/bin/one")]},
        artifacts={"artifacts": [_artifact("/usr/bin/two")]}, processes={})
    assert not any(finding["category"] == "execution_artifact_matched"
                   for finding in result["findings"])


def test_correlation_does_not_consult_the_local_filesystem():
    import inspect

    from analysis import correlation

    offending = [line.strip() for line in inspect.getsource(correlation).splitlines()
                 if "os.path" in line and not line.lstrip().startswith("#")]
    assert not offending, (
        f"correlation must treat a path as evidence, not as a local path: {offending}")


# --- hashing identity ---------------------------------------------------------
def test_hashing_compares_snapshots_of_the_same_kind():
    """The other defect.

    An open handle and a path describe the same file differently on Windows:
    os.fstat and os.stat report different device and index values for it. The
    check compared one against the other, so every file looked as though it had
    changed and no digest was ever recorded there.
    """
    import inspect

    from analysis import hashing

    source = inspect.getsource(hashing.hash_file)
    assert "_identity(after_read) != _identity(opened)" in source
    assert "_identity(stat) != _identity(before)" in source
    assert "for snapshot in (opened, after_read, stat)" not in source, (
        "an fstat result is being compared against a stat result again")


def test_a_file_still_hashes(tmp_path):
    from analysis import hashing

    target = tmp_path / "evidence.bin"
    target.write_bytes(b"forensic sample")
    result = hashing.hash_file(str(target))
    assert len(result["hash"]) == 64
    assert result["size_bytes"] == 15


def test_a_file_swapped_while_it_is_read_is_refused(tmp_path, monkeypatch):
    """The check still has to do its job on the handle."""
    from analysis import hashing

    target = tmp_path / "evidence.bin"
    target.write_bytes(b"original bytes")

    real_fstat = os.fstat
    seen = {"n": 0}

    def shifting_fstat(fileno):
        result = real_fstat(fileno)
        seen["n"] += 1
        if seen["n"] > 1:
            # The second look at the same handle reports a different file.
            return os.stat_result(
                (result.st_mode, result.st_ino + 1) + tuple(result)[2:])
        return result

    monkeypatch.setattr(os, "fstat", shifting_fstat)
    with pytest.raises(RuntimeError, match="while it was being read"):
        hashing.hash_file(str(target))


def test_a_path_that_comes_to_mean_something_else_is_refused(tmp_path, monkeypatch):
    """And on the path.

    Keyed on the file having been opened rather than on a call count: os.stat is
    also called by the existence and type checks before the read, and counting
    those made an earlier version of this test pass for the wrong reason.
    """
    from analysis import hashing

    target = tmp_path / "evidence.bin"
    target.write_bytes(b"original bytes")

    real_stat, real_open = os.stat, open
    state = {"read": False}

    def watching_open(*args, **kwargs):
        state["read"] = True
        return real_open(*args, **kwargs)

    def shifting_stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if state["read"] and str(path).endswith("evidence.bin"):
            return os.stat_result((result.st_mode, result.st_ino + 1) + tuple(result)[2:])
        return result

    monkeypatch.setattr(hashing, "open", watching_open, raising=False)
    monkeypatch.setattr(os, "stat", shifting_stat)
    with pytest.raises(RuntimeError, match="changed during hashing"):
        hashing.hash_file(str(target))
