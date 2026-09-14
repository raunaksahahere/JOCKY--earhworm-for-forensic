"""Schema 1 to 2 upgrade: new entities added, existing investigations preserved."""
import sqlite3

import pytest

from backend.paths import Paths
from backend.storage import MIGRATIONS, Store, encode, identifier, now
from backend.versions import DATABASE_SCHEMA_VERSION


def build_v1(path):
    """Create a schema-1 database holding one investigation with a finding."""
    db = sqlite3.connect(path)
    for statement in MIGRATIONS[1]:
        db.execute(statement)
    db.execute("PRAGMA user_version=1")
    case = identifier()
    db.execute("INSERT INTO investigations(id,title,created_at,status) VALUES (?,?,?,?)",
               (case, "Legacy investigation", now(), "completed"))
    db.execute("INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?)",
               (identifier(), case, None, "PROCESSES", "psutil", now(), "completed", encode({})))
    db.execute("INSERT INTO findings VALUES (?,?,?,?,?,?,?,?)",
               (identifier(), case, None, "filename", "info", "Old finding", "explanation", "INFERRED"))
    db.commit()
    db.close()
    return case


@pytest.fixture
def upgraded(tmp_path):
    paths = Paths.resolve(str(tmp_path / "workspace"))
    paths.initialize()
    case = build_v1(paths.database)
    store = Store(paths)
    return store, case


def test_upgrade_reaches_the_current_version(upgraded):
    store, _case = upgraded

    assert store.rows("PRAGMA user_version")[0]["user_version"] == DATABASE_SCHEMA_VERSION


def test_existing_rows_survive_the_upgrade(upgraded):
    store, case = upgraded

    assert store.rows("SELECT title FROM investigations WHERE id=?", (case,))[0]["title"] == "Legacy investigation"
    assert len(store.rows("SELECT * FROM findings")) == 1
    assert len(store.rows("SELECT * FROM evidence")) == 1


def test_pre_existing_findings_get_a_default_confidence(upgraded):
    store, _case = upgraded

    finding = store.rows("SELECT confidence, detail FROM findings")[0]
    assert finding["confidence"] == "unqualified"
    assert finding["detail"] is None


def test_new_entities_exist_and_are_empty(upgraded):
    store, _case = upgraded

    for table in ("execution_events", "artifact_observations", "timeline_events",
                  "finding_evidence", "collection_limitations"):
        assert store.rows(f"SELECT * FROM {table}") == []


def test_upgrade_is_idempotent(upgraded):
    store, case = upgraded

    again = Store(store.paths)

    assert again.rows("PRAGMA user_version")[0]["user_version"] == DATABASE_SCHEMA_VERSION
    assert again.rows("SELECT id FROM investigations WHERE id=?", (case,))


def test_a_newer_database_is_refused_rather_than_downgraded(tmp_path):
    from backend.storage import StorageError
    paths = Paths.resolve(str(tmp_path / "future"))
    paths.initialize()
    build_v1(paths.database)
    db = sqlite3.connect(paths.database)
    db.execute(f"PRAGMA user_version={DATABASE_SCHEMA_VERSION + 1}")
    db.commit()
    db.close()

    with pytest.raises(StorageError, match="newer backend"):
        Store(paths)


# --- migrations 5 and 6: casework and endpoints ------------------------------

def build_v4(path):
    """A schema-4 database with an investigation and its execution events.

    Schema 4 is the version shipped before casework and endpoints existed, so
    this is what a real user's database looks like when they upgrade.
    """
    db = sqlite3.connect(path)
    for version in range(1, 5):
        for statement in MIGRATIONS[version]:
            db.execute(statement)
    db.execute("PRAGMA user_version=4")
    case = identifier()
    db.execute("INSERT INTO investigations(id,title,created_at,status) VALUES (?,?,?,?)",
               (case, "Existing investigation", now(), "completed"))
    evidence = identifier()
    db.execute("INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?)",
               (evidence, case, None, "EXECUTION HISTORY", "journal", now(), "completed",
                encode({})))
    for index in range(25):
        db.execute(
            "INSERT INTO execution_events (id,investigation_id,evidence_id,source,timestamp,"
            " process_name,classification,collection_status,payload)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (identifier(), case, evidence, "journal", now(), f"process-{index}",
             "HISTORICAL_EVIDENCE", "AVAILABLE", encode({"n": index})))
    db.commit()
    db.close()
    return case


@pytest.fixture
def upgraded_from_v4(tmp_path):
    paths = Paths.resolve(str(tmp_path / "v4"))
    paths.initialize()
    case = build_v4(paths.database)
    return Store(paths), case


def test_upgrading_from_v4_preserves_every_execution_event(upgraded_from_v4):
    """The regression that matters: an upgrade must not lose collected evidence."""
    store, case = upgraded_from_v4
    assert store.rows("PRAGMA user_version")[0]["user_version"] == DATABASE_SCHEMA_VERSION
    events = store.rows("SELECT id FROM execution_events WHERE investigation_id=?", (case,))
    assert len(events) == 25
    assert len(store.rows("SELECT id FROM evidence WHERE investigation_id=?", (case,))) == 1


def test_an_existing_investigation_belongs_to_no_case_after_upgrade(upgraded_from_v4):
    """Investigations predate cases; they must keep working without one."""
    store, case = upgraded_from_v4
    assert store.rows("SELECT case_id FROM investigations WHERE id=?", (case,))[0]["case_id"] is None


def test_casework_and_endpoint_tables_exist_and_are_empty(upgraded_from_v4):
    store, _case = upgraded_from_v4
    for table in ("cases", "evidence_sources", "evidence_integrity_events", "audit_events",
                  "notes", "investigation_programs", "endpoints", "enrollment_tokens",
                  "endpoint_tasks", "endpoint_events"):
        assert store.rows(f"SELECT * FROM {table}") == []


def test_casework_works_against_an_upgraded_database(upgraded_from_v4, tmp_path):
    """An upgrade that leaves the new features unusable is not an upgrade."""
    from backend.casework import Casework

    store, _case = upgraded_from_v4
    casework = Casework(store)
    evidence = tmp_path / "sample.bin"
    evidence.write_bytes(b"bytes")
    case = casework.create_case({"title": "After upgrade"})
    record = casework.register_evidence({"case_id": case["id"], "path": str(evidence)})
    assert casework.verify_evidence(record["id"])["verification_state"] == "VERIFIED"


def test_every_migration_step_is_reachable_in_order():
    """No gaps: each version must have a forward migration."""
    assert sorted(MIGRATIONS) == list(range(1, DATABASE_SCHEMA_VERSION + 1))
