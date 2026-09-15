import builtins
import hashlib

import pytest

from tests.conftest import requires_posix

from analysis import hashing, ledger


@pytest.mark.parametrize("algorithm", ["sha256", "sha1", "md5", "sha512"])
@pytest.mark.parametrize("payload", [b"", b"abc", bytes(range(256)) * 1025], ids=["empty", "known", "multi-chunk"])
def test_hashes(tmp_path, algorithm, payload):
    path = tmp_path / "file.bin"
    path.write_bytes(payload)
    result = hashing.hash_file(str(path), algorithm)
    assert result["hash"] == hashlib.new(algorithm, payload).hexdigest()
    assert result["size_bytes"] == len(payload)
    assert result["algorithm"] == algorithm.upper()
    assert result["integrity_history"]["status"] == "first_recorded"
    assert path.read_bytes() == payload


def test_known_sha256(evidence):
    assert hashing.hash_file(str(evidence))["hash"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


@pytest.mark.parametrize("algorithm", ["invalid", "sha3", "sha-256"])
def test_invalid_algorithm(evidence, algorithm):
    with pytest.raises(ValueError, match="Unsupported algorithm"):
        hashing.hash_file(str(evidence), algorithm)


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        hashing.hash_file(str(tmp_path / "missing"))


def test_directory_rejected(tmp_path):
    with pytest.raises(ValueError):
        hashing.hash_file(str(tmp_path))


def test_permission_failure(evidence, monkeypatch):
    original = builtins.open
    def denied(path, *args, **kwargs):
        if str(path) == str(evidence):
            raise PermissionError("denied fixture")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(builtins, "open", denied)
    with pytest.raises(PermissionError):
        hashing.hash_file(str(evidence))


def test_relative_path_normalizes_only_at_execution(evidence, monkeypatch):
    monkeypatch.chdir(evidence.parent)
    result = hashing.hash_file(evidence.name)
    assert result["target"] == evidence.name
    assert result["absolute_path"] == str(evidence)


def test_repeated_and_changed(evidence):
    hashing.hash_file(str(evidence))
    assert hashing.hash_file(str(evidence))["integrity_history"]["status"] == "unchanged"
    evidence.write_bytes(b"changed")
    assert hashing.hash_file(str(evidence))["integrity_history"]["status"] == "altered"


def test_change_during_precheck_not_recorded(evidence, monkeypatch):
    def change(path):
        evidence.write_bytes(b"changed during collection")
        return {"status": "unknown"}
    monkeypatch.setattr(hashing, "check_basic_integrity", change)
    with pytest.raises(RuntimeError, match="changed"):
        hashing.hash_file(str(evidence))
    assert ledger.get_last_hash(str(evidence)) is None


def test_change_during_digest_read_not_recorded(evidence, monkeypatch):
    original = builtins.open
    class ChangingReader:
        def __enter__(self):
            self.handle = original(evidence, "rb")
            self.changed = False
            return self
        def __exit__(self, *args):
            self.handle.close()
        def fileno(self):
            return self.handle.fileno()
        def read(self, size):
            data = self.handle.read(size)
            if not self.changed:
                with original(evidence, "ab") as writer:
                    writer.write(b"appended during read")
                self.changed = True
            return data
    monkeypatch.setattr(hashing, "open", lambda *args: ChangingReader(), raising=False)
    with pytest.raises(RuntimeError, match="changed"):
        hashing.hash_file(str(evidence))
    assert ledger.get_last_hash(str(evidence)) is None


def test_unusable_ledger_not_reported_as_verified(evidence):
    from pathlib import Path
    path = Path(ledger._LEDGER_PATH)
    path.parent.mkdir()
    path.write_text("corrupted", encoding="utf-8")
    with pytest.raises(ledger.LedgerError):
        hashing.hash_file(str(evidence))
    assert path.read_text() == "corrupted"


@requires_posix
def test_creation_time_not_ctime_on_linux(evidence):
    result = hashing.hash_file(str(evidence))
    stat = evidence.stat()
    if not hasattr(stat, "st_birthtime"):
        assert result["created"] is None
    assert result["metadata_changed"]