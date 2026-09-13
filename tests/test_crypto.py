"""Safe authenticated export supersedes the destructive legacy format."""
import pytest
from cryptography.exceptions import InvalidTag
from crypto.crypto import encrypt_file, decrypt_file


@pytest.mark.parametrize("payload", [b"", b"abc", bytes(range(256))*12000])
def test_round_trip_preserves_source(tmp_path, payload):
    source, encrypted, restored = (tmp_path / name for name in ("来源 α.txt", "export.enc", "restored.txt"))
    source.write_bytes(payload)
    result = encrypt_file(source, encrypted, passphrase="correct horse नमस्ते")
    assert result["status"] == "success"
    assert source.read_bytes() == payload
    decrypt_file(encrypted, restored, passphrase="correct horse नमस्ते")
    assert restored.read_bytes() == payload


@pytest.mark.parametrize("change", ["wrong_passphrase", "modified", "truncated", "header"])
def test_authentication_failure_no_plaintext(tmp_path, change):
    source, encrypted, restored = (tmp_path / name for name in ("source", "enc", "restored"))
    source.write_bytes(b"evidence" * 100)
    encrypt_file(source, encrypted, passphrase="secret")
    content = bytearray(encrypted.read_bytes())
    if change == "modified": content[-20] ^= 1
    if change == "truncated": content = content[:-8]
    if change == "header": content[0] ^= 1
    encrypted.write_bytes(content)
    with pytest.raises((InvalidTag, ValueError)):
        decrypt_file(encrypted, restored, passphrase="wrong" if change == "wrong_passphrase" else "secret")
    assert not restored.exists()
    assert source.read_bytes() == b"evidence" * 100


def test_no_in_place_or_default_key(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"evidence")
    with pytest.raises(ValueError): encrypt_file(source)
    with pytest.raises(ValueError): encrypt_file(source, source, passphrase="secret")
    with pytest.raises(ValueError): encrypt_file(source, tmp_path / "export")
    assert source.read_bytes() == b"evidence"


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError): encrypt_file(tmp_path / "missing")


def test_export_disk_full_removes_partial_destination(tmp_path, monkeypatch):
    import shutil
    import errno
    source, encrypted = tmp_path / 'source', tmp_path / 'copy.enc'
    source.write_bytes(b'original')
    def fail_copy(src, dst, length):
        dst.write(b'partial')
        raise OSError(errno.ENOSPC, 'No space left')
    monkeypatch.setattr(shutil, 'copyfileobj', fail_copy)
    with pytest.raises(OSError): encrypt_file(source, encrypted, passphrase='secret')
    assert not encrypted.exists()
    assert source.read_bytes() == b'original'
    assert list(tmp_path.iterdir()) == [source]
