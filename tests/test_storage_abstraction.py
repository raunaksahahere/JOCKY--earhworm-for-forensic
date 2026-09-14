"""The boundary that makes the move off SQLite cheap.

The scale-out path documented in docs/Architecture.md rests on one claim: that
only the storage layer knows it is SQLite, and the domain and service layers
reach the database through a small interface. A claim like that rots silently --
one `sqlite3.connect` in a service, and the documented migration stops being a
migration and starts being a rewrite.

So these tests check it rather than trusting it.
"""
import importlib
import inspect
import pkgutil
import re

import pytest

import analysis
import backend
from backend.casework import Casework
from backend.fleet import Fleet
from backend.memory_workflow import MemoryWorkflow
from backend.paths import Paths
from backend.service import Workstation
from backend.storage import Store

#: Modules allowed to know what the database actually is.
STORAGE_MODULES = {"backend.storage", "backend.paths", "backend.workstation_view"}

#: The whole interface the service layer uses to reach storage. A replacement
#: backend has to provide these and nothing else.
STORE_INTERFACE = ("rows", "transaction", "backup")


def _modules(package):
    for info in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
        if info.name.endswith("__pycache__"):
            continue
        try:
            yield info.name, importlib.import_module(info.name)
        except ImportError:  # optional dependency
            continue


#: analysis/browser.py opens SQLite, and that is not a violation: it is reading
#: a browser's own history database as *evidence*, having copied it aside first.
#: Reading an evidence file that happens to be SQLite has nothing to do with
#: where JOCKY keeps its records, and a rule that conflated the two would force
#: the collector to be rewritten for no reason during a database migration.
EVIDENCE_READERS = {"analysis.browser"}


def test_the_analysis_layer_never_reads_jockys_own_store():
    """Analysis takes evidence and returns evidence.

    That is what lets the same functions run over a live collection, a fixture
    and a synthetic scenario -- and it is what means a change of database
    touches none of them.
    """
    offenders = {}
    for name, module in _modules(analysis):
        source = inspect.getsource(module)
        hits = [line.strip() for line in source.splitlines()
                if re.search(r"\b(import\s+backend\.storage|from\s+backend\.storage|"
                             r"from\s+backend\s+import\s+storage)\b", line)]
        if name not in EVIDENCE_READERS:
            hits += [line.strip() for line in source.splitlines()
                     if re.search(r"\bsqlite3\b", line)]
        if hits:
            offenders[name] = hits
    assert not offenders, f"analysis modules reached for JOCKY's store: {offenders}"


def test_an_evidence_reader_opens_only_a_copy_read_only():
    """The exception above is safe only because of how it opens the file."""
    import analysis.browser

    source = inspect.getsource(analysis.browser)
    assert "shutil.copy2(database, copy)" in source, (
        "the browser collector must copy the profile database before opening it")
    assert "mode=ro" in source, "the copy must be opened read-only"


def test_only_the_storage_layer_knows_it_is_sqlite():
    offenders = {}
    for name, module in _modules(backend):
        if name in STORAGE_MODULES:
            continue
        try:
            source = inspect.getsource(module)
        except OSError:
            continue
        hits = [line.strip() for line in source.splitlines()
                if re.search(r"sqlite3\.(connect|Connection|Cursor)", line)]
        if hits:
            offenders[name] = hits
    assert not offenders, (
        f"these modules open the database directly, which the documented migration path "
        f"depends on them not doing: {offenders}")


@pytest.mark.parametrize("service_class", [Casework, Fleet, MemoryWorkflow])
def test_a_service_reaches_storage_only_through_the_store_interface(service_class):
    source = inspect.getsource(service_class)
    used = set(re.findall(r"(?:self\.)?store\.(\w+)", source))
    unexpected = used - set(STORE_INTERFACE) - {"paths"}
    assert not unexpected, (
        f"{service_class.__name__} uses store.{unexpected}, which a replacement backend would "
        "also have to provide. Keep the interface small or document the addition.")


def test_the_store_interface_is_what_the_documentation_claims():
    for name in STORE_INTERFACE:
        assert callable(getattr(Store, name, None)), f"Store has no {name}()"


def test_a_service_runs_against_a_substitute_store(tmp_path):
    """The proof, rather than the argument.

    A stand-in that records what was asked of it, wrapping a real Store. If a
    service reached past the interface, this would not work.
    """
    class RecordingStore:
        """Everything a replacement backend would have to implement."""

        def __init__(self, inner):
            self.inner, self.calls = inner, []
            self.paths = inner.paths

        def rows(self, query, args=()):
            self.calls.append(("rows", query.split()[0].upper()))
            return self.inner.rows(query, args)

        def transaction(self):
            self.calls.append(("transaction", None))
            return self.inner.transaction()

        def backup(self):
            self.calls.append(("backup", None))
            return self.inner.backup()

    inner = Store(Paths.resolve(str(tmp_path / "workspace")))
    substitute = RecordingStore(inner)

    casework = Casework(substitute)
    case = casework.create_case({"title": "Substitute store"})
    evidence = tmp_path / "sample.bin"
    evidence.write_bytes(b"bytes")
    record = casework.register_evidence({"case_id": case["id"], "path": str(evidence)})
    assert casework.verify_evidence(record["id"])["verification_state"] == "VERIFIED"

    fleet = Fleet(substitute, casework)
    issued = fleet.issue_enrollment_token({"endpoint_name": "lab-1",
                                           "authorization_reference": "W/1"})
    identity = fleet.enroll({"enrollment_token": issued["enrollment_token"],
                             "endpoint_name": "lab-1"})
    assert fleet.get_endpoint(identity["endpoint_id"])["name"] == "lab-1"

    verbs = {call[0] for call in substitute.calls}
    assert verbs <= set(STORE_INTERFACE), f"a service used {verbs - set(STORE_INTERFACE)}"


def test_every_sql_statement_lives_where_it_can_be_ported(tmp_path):
    """Count where SQL is written, so a move off SQLite has a known surface."""
    holders = {}
    for name, module in _modules(backend):
        try:
            source = inspect.getsource(module)
        except OSError:
            continue
        statements = re.findall(r"\b(SELECT|INSERT INTO|UPDATE|DELETE FROM|CREATE TABLE)\b", source)
        if statements:
            holders[name] = len(statements)
    # Kept deliberately small: these are the files a port would touch.
    assert set(holders) <= {
        "backend.storage", "backend.service", "backend.casework", "backend.fleet",
        "backend.memory_workflow", "backend.api", "backend.workstation_view",
    }, f"SQL appeared somewhere new: {sorted(set(holders))}"


def test_the_domain_model_is_plain_data():
    """Analysis passes dictionaries, so nothing is bound to a database row."""
    from analysis.correlation import correlate
    from analysis.triage import classify_event

    finding = correlate(execution={"events": []}, artifacts={"artifacts": []}, processes={})
    assert isinstance(finding, dict)
    classification = classify_event({"evidence_kind": "EXECUTION_EVIDENCE"})
    assert isinstance(classification.to_dict(), dict)


def test_the_workstation_service_exposes_its_store(tmp_path):
    """The seam a replacement backend is injected at."""
    service = Workstation(Store(Paths.resolve(str(tmp_path / "workspace"))))
    try:
        assert hasattr(service, "store")
        assert inspect.signature(Workstation.__init__).parameters["store"]
    finally:
        service.close()
