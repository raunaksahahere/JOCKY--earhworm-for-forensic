import os
from types import SimpleNamespace

import pytest

from analysis import files


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "case"
    (root / "sub").mkdir(parents=True)
    (root / "Invoice.txt").write_text("abc")
    (root / "notes.txt").write_text("notes")
    (root / "sub" / "invoice-copy.exe").write_text("data")
    return root


def test_listing(tree):
    result = files.list_files(str(tree))
    assert [e["name"] for e in result["entries"]] == ["sub", "Invoice.txt", "notes.txt"]
    assert result["entry_count"] == result["returned_count"] == 3
    assert result["complete"] and not result["truncated"]


def test_recursive_substring_search(tree):
    result = files.search_file("INVO", str(tree))
    assert {os.path.basename(e["path"]) for e in result["results"]} == {"Invoice.txt", "invoice-copy.exe"}
    assert result["match_count"] == 2
    assert result["entries_scanned"] == 3


def test_empty_directory(tmp_path):
    assert files.list_files(str(tmp_path))["entries"] == []
    assert files.search_file("missing", str(tmp_path))["results"] == []


def test_no_matches(tree):
    result = files.search_file("absent", str(tree))
    assert result["results"] == [] and result["complete"]


@pytest.mark.parametrize("operation", [lambda p: files.list_files(p), lambda p: files.search_file("a", p)])
def test_missing_directory(tmp_path, operation):
    with pytest.raises(FileNotFoundError):
        operation(str(tmp_path / "missing"))


def test_file_as_search_root(evidence):
    with pytest.raises(NotADirectoryError):
        files.search_file("x", str(evidence))


@pytest.mark.parametrize("operation", [lambda p: files.list_files(p), lambda p: files.search_file("a", p)])
def test_inaccessible_root(tmp_path, monkeypatch, operation):
    def denied(path):
        raise PermissionError(13, "fixture denied", str(path))
    monkeypatch.setattr(files.os, "scandir", denied)
    with pytest.raises(PermissionError):
        operation(str(tmp_path))


def test_unreadable_subdirectory_reported(tree, monkeypatch):
    original = os.scandir
    def denied(path):
        if str(path) == str(tree / "sub"):
            raise PermissionError(13, "fixture denied", str(path))
        return original(path)
    monkeypatch.setattr(files.os, "scandir", denied)
    result = files.search_file("invoice", str(tree))
    assert result["skipped_count"] == 1 and not result["complete"]
    assert result["warnings"] and result["match_count"] == 1


def test_inaccessible_entry_not_silently_dropped(tmp_path, monkeypatch):
    def denied(**kwargs):
        raise PermissionError("fixture denied")
    class Scan:
        def __enter__(self):
            return iter([SimpleNamespace(stat=denied)])
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(files.os, "scandir", lambda path: Scan())
    result = files.list_files(str(tmp_path))
    assert result["skipped_count"] == 1 and result["warnings"] and not result["complete"]


def test_list_return_limit(tree, monkeypatch):
    monkeypatch.setattr(files, "MAX_LIST_ENTRIES", 1)
    result = files.list_files(str(tree))
    assert result["returned_count"] == 1 and result["entry_count"] == 3
    assert result["truncated"] and result["warnings"]


def test_list_scan_limit(tree, monkeypatch):
    monkeypatch.setattr(files, "MAX_LIST_ENTRIES_SCANNED", 1)
    result = files.list_files(str(tree))
    assert result["entries_scanned"] == 1 and result["truncated"]


@pytest.mark.parametrize("limit", ["MAX_SEARCH_MATCHES", "MAX_SEARCH_ENTRIES_SCANNED"])
def test_search_limits(tree, monkeypatch, limit):
    monkeypatch.setattr(files, limit, 1)
    result = files.search_file("i", str(tree))
    assert result["truncated"] and result["warnings"] and not result["complete"]
    if limit == "MAX_SEARCH_ENTRIES_SCANNED":
        assert result["entries_scanned"] == 1
    else:
        assert result["match_count"] <= 1
