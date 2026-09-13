"""Non-destructive authenticated evidence export. Original files are never changed."""
import json
import os
import struct
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"JOCKYENC1"
CHUNK = 1024 * 1024


def _key(passphrase, salt):
    if not isinstance(passphrase, str) or not passphrase:
        raise ValueError("An explicit recovery passphrase is required; no key is stored by JOCKY")
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode("utf-8"))


def _output(source, destination):
    if destination is None:
        raise ValueError("Safe export requires a separate destination and recovery passphrase; use the evidence export API")
    destination = Path(destination)
    if destination.exists() or destination.resolve() == Path(source).resolve():
        raise ValueError("Destination must be new and different from the source")
    return destination


def _publish(temporary, target):
    """Never replace an existing destination; remove our own incomplete copy."""
    import shutil
    created = False
    try:
        with target.open("xb") as output:
            created = True
            with temporary.open("rb") as source:
                shutil.copyfileobj(source, output, CHUNK)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        if created:
            target.unlink(missing_ok=True)
        raise


def encrypt_file(file_path, destination=None, *, passphrase=None):
    with open(file_path, "rb") as source:
        target = _output(file_path, destination)
        before = os.fstat(source.fileno())
        salt, nonce = os.urandom(16), os.urandom(12)
        key = _key(passphrase, salt)
        metadata = {"version": 1, "cipher": "AES-256-GCM", "kdf": "scrypt-N32768-r8-p1", "salt": salt.hex(), "nonce": nonce.hex(),
                    "source_name": Path(file_path).name, "source_size": before.st_size, "source_mtime_ns": before.st_mtime_ns}
        header = json.dumps(metadata, ensure_ascii=False, sort_keys=True).encode("utf-8")
        aad = MAGIC + struct.pack(">I", len(header)) + header
        cipher = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
        cipher.authenticate_additional_data(aad)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
            temporary = Path(output.name)
            try:
                output.write(aad)
                while chunk := source.read(CHUNK):
                    output.write(cipher.update(chunk))
                output.write(cipher.finalize())
                output.write(cipher.tag)
                after = os.fstat(source.fileno())
                if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise RuntimeError("Source changed during export")
                output.flush()
                os.fsync(output.fileno())
            except BaseException:
                output.close()
                temporary.unlink(missing_ok=True)
                raise
    try:
        _publish(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {"action": "encrypt", "status": "success", "path": str(file_path), "artifact": str(target), "metadata": metadata, "message": "Encrypted copy exported; source unchanged"}


def decrypt_file(file_path, destination=None, *, passphrase=None):
    target = _output(file_path, destination)
    temporary = None
    try:
        with open(file_path, "rb") as source:
            prefix = source.read(len(MAGIC) + 4)
            if len(prefix) != len(MAGIC) + 4 or not prefix.startswith(MAGIC):
                raise ValueError("Unsupported encrypted artifact")
            length = struct.unpack(">I", prefix[-4:])[0]
            if length > 16384:
                raise ValueError("Invalid encryption header")
            header = source.read(length)
            metadata = json.loads(header)
            if metadata.get("version") != 1 or metadata.get("kdf") != "scrypt-N32768-r8-p1" or metadata.get("cipher") != "AES-256-GCM":
                raise ValueError("Unsupported encryption parameters")
            key = _key(passphrase, bytes.fromhex(metadata["salt"]))
            start = source.tell()
            size = os.fstat(source.fileno()).st_size
            remaining = size - start - 16
            if remaining < 0:
                raise ValueError("Truncated ciphertext")
            source.seek(size - 16)
            tag = source.read(16)
            source.seek(start)
            cipher = Cipher(algorithms.AES(key), modes.GCM(bytes.fromhex(metadata["nonce"]), tag)).decryptor()
            cipher.authenticate_additional_data(prefix + header)
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
                temporary = Path(output.name)
                while remaining:
                    chunk = source.read(min(CHUNK, remaining))
                    if not chunk:
                        raise ValueError("Truncated ciphertext")
                    output.write(cipher.update(chunk))
                    remaining -= len(chunk)
                output.write(cipher.finalize())
                output.flush()
                os.fsync(output.fileno())
        _publish(temporary, target)
        return {"status": "success", "artifact": str(target), "metadata": metadata}
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
