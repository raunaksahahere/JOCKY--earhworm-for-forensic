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
