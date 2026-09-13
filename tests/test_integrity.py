import gzip
import zipfile

import pytest

from analysis import integrity


def test_valid_zip(tmp_path):
    path = tmp_path / "archive.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("sample.txt", b"abc")
    assert integrity.check_basic_integrity(str(path))["status"] == "ok"


def test_zip_crc_failure(tmp_path):
    path = tmp_path / "archive.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("sample.txt", b"UNIQUE_PAYLOAD")
    path.write_bytes(path.read_bytes().replace(b"UNIQUE_PAYLOAD", b"BROKEN_PAYLOAD"))
    assert integrity.check_basic_integrity(str(path))["status"] == "critical"


@pytest.mark.parametrize("extension", ["zip", "docx", "xlsx", "pptx", "jar", "apk"])
def test_invalid_zip_structure(tmp_path, extension):
    path = tmp_path / ("archive." + extension)
    path.write_bytes(b"not an archive")
    assert integrity.check_basic_integrity(str(path))["status"] == "critical"


def test_valid_gzip(tmp_path):
    path = tmp_path / "data.gz"
    path.write_bytes(gzip.compress(b"abc"))
    assert integrity.check_basic_integrity(str(path))["status"] == "ok"


@pytest.mark.parametrize("payload", [b"not gzip", gzip.compress(b"abc")[:-5], gzip.compress(b"abc")[:-8] + b"\x00" * 8])
def test_corrupt_gzip(tmp_path, payload):
    path = tmp_path / "data.gz"
    path.write_bytes(payload)
    assert integrity.check_basic_integrity(str(path))["status"] == "critical"


@pytest.mark.parametrize(("extension", "payload", "status"), [
    ("jpg", b"\xff\xd8\xff\xff\xd9", "ok"),
    ("jpeg", b"\xff\xd8\xffmissing trailer", "warning"),
    ("jpg", b"invalid", "critical"),
    ("png", b"\x89PNG\r\n\x1a\nIEND", "ok"),
    ("png", b"\x89PNG\r\n\x1a\nmissing trailer", "warning"),
    ("png", b"invalid", "critical"),
    ("pdf", b"%PDF-1.7\n%%EOF", "ok"),
    ("pdf", b"%PDF-1.7\nmissing trailer", "warning"),
    ("pdf", b"invalid", "critical"),
    ("gif", b"GIF89a", "unknown"),
    ("bin", b"some bytes", "unknown"),
    ("png", b"", "warning"),
])
def test_markers_only_not_full_format_validation(tmp_path, extension, payload, status):
    path = tmp_path / ("fixture." + extension)
    path.write_bytes(payload)
    assert integrity.check_basic_integrity(str(path))["status"] == status


def test_missing(tmp_path):
    assert integrity.check_basic_integrity(str(tmp_path / "missing"))["status"] == "critical"


@pytest.mark.parametrize("extension", ["bin", "png", "gz"])
def test_unreadable_input(tmp_path, monkeypatch, extension):
    path = tmp_path / ("fixture." + extension)
    path.write_bytes(b"data")
    def denied(*args, **kwargs):
        raise PermissionError("fixture denied")
    monkeypatch.setattr("builtins.open", denied)
    assert integrity.check_basic_integrity(str(path))["status"] == "critical"


def test_input_size_limit(tmp_path, monkeypatch):
    path = tmp_path / "data.bin"
    path.write_bytes(b"abcd")
    monkeypatch.setattr(integrity, "MAX_INPUT_BYTES", 3)
    result = integrity.check_basic_integrity(str(path))
    assert result["status"] == "unknown" and not result["performed"]
    assert "limit" in result["message"]


@pytest.mark.parametrize("extension", ["zip", "gz"])
def test_decompression_limit(tmp_path, monkeypatch, extension):
    path = tmp_path / ("archive." + extension)
    if extension == "gz":
        path.write_bytes(gzip.compress(b"a" * 1000))
    else:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("sample", b"a" * 1000)
    monkeypatch.setattr(integrity, "MAX_DECOMPRESSED_BYTES", 10)
    result = integrity.check_basic_integrity(str(path))
    assert result["status"] == "unknown" and "limit" in result["message"]


def test_archive_member_limit(tmp_path, monkeypatch):
    path = tmp_path / "archive.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a", "a")
        archive.writestr("b", "b")
    monkeypatch.setattr(integrity, "MAX_ARCHIVE_MEMBERS", 1)
    assert integrity.check_basic_integrity(str(path))["status"] == "unknown"
