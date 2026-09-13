import pytest

from analysis import ledger


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "_DATA_DIR", str(tmp_path / "ledger"))
    monkeypatch.setattr(ledger, "_LEDGER_PATH", str(tmp_path / "ledger" / "hash_ledger.json"))
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def evidence(tmp_path):
    path = tmp_path / "evidence नमूना file.bin"
    path.write_bytes(b"abc")
    return path


@pytest.fixture
def client():
    from communication.server import app
    app.config.update(TESTING=True)
    return app.test_client()
