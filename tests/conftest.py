import os

import pytest

from analysis import ledger

#: Tests that exercise POSIX mechanics rather than JOCKY's own behaviour: mode
#: bits, effective uid, birth time. They are not Windows gaps -- the behaviour
#: they check has a different shape there, and asserting the POSIX shape on
#: Windows would be asserting the wrong thing rather than finding a bug.
requires_posix = pytest.mark.skipif(
    os.name != "posix",
    reason="exercises POSIX file mechanics; the Windows equivalent is ACL-based and is a "
           "separate question this build has not answered")


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


@pytest.fixture
def stub_execution_history():
    """A deterministic historical-execution result.

    Shaped exactly like a real collection so the service, correlation and
    report paths are exercised, but fixed so workstation tests do not depend on
    whatever telemetry the machine running them happens to have.
    """
    from analysis.execution_history import finalize
    from analysis.execution_model import AVAILABLE, CollectionWindow, NOT_ENABLED
    from analysis import execution_linux
    from tests.fixtures.telemetry import journal_runner

    def build(**_kwargs):
        window = CollectionWindow.resolve(168)
        record, events = execution_linux.collect_journal(window, runner=journal_runner())
        unavailable = execution_linux.collect_process_accounting(
            window, paths=("/nonexistent/pacct",))[0]
        assert record["status"] == AVAILABLE and unavailable["status"] == NOT_ENABLED
        return finalize("Linux", window, [record, unavailable], events)

    return build


@pytest.fixture(autouse=True)
def deterministic_execution_history(request, monkeypatch, stub_execution_history):
    """Keep the real host's telemetry out of every test that does not ask for it.

    Reading the live journal would make assertions depend on the machine and
    would make each collection test as slow as a real forensic collection. Tests
    that exercise the real collectors opt in with @pytest.mark.real_telemetry.
    """
    if request.node.get_closest_marker("real_telemetry"):
        return
    import backend.service
    if hasattr(backend.service, "collect_execution_history"):
        monkeypatch.setattr(backend.service, "collect_execution_history",
                            lambda **kwargs: stub_execution_history(**kwargs))
