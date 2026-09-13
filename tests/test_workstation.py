from backend.versions import DATABASE_SCHEMA_VERSION, REPORT_SCHEMA_VERSION
import concurrent.futures
import errno
import io
import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from pypdf import PdfReader

from backend.api import create_app
from backend.paths import Paths
from backend.service import Workstation, ServiceError, TERMINAL
from backend.storage import Store, StorageError, encode, now, identifier
from backend.pdf_report import render_pdf


@pytest.fixture
def store(tmp_path):
    return Store(Paths.resolve(str(tmp_path / "portable workspace नमस्ते")))


@pytest.fixture
def service(store):
    service = Workstation(store)
    yield service
    service.close()


def wait(service, case_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        case = service.get_case(case_id)
        if case["status"] in TERMINAL:
            return case
        time.sleep(.02)
    pytest.fail("Collection did not reach terminal state")


def test_database_migration_restart_backup_rollback(store):
    with pytest.raises(RuntimeError):
        with store.transaction() as db:
            db.execute("INSERT INTO metadata VALUES ('rollback','true')")
            raise RuntimeError("rollback")
    assert not store.rows("SELECT * FROM metadata")
    with store.transaction() as db:
        db.execute("INSERT INTO metadata VALUES ('persist','true')")
    assert Store(store.paths).rows("SELECT value FROM metadata")[0]["value"] == "true"
    backup = store.backup()
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA user_version").fetchone()[0] == DATABASE_SCHEMA_VERSION
        assert db.execute("SELECT value FROM metadata").fetchone()[0] == "true"


def test_concurrent_hash_writes(store):
    def observe(index):
        return store.observe_hash("C:\\Evidence ü\\file", "sha256", f"{index:064x}", index)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(observe, range(24)))
    assert len(store.rows("SELECT * FROM hash_observations")) == 24


def test_foreign_keys(store):
    with pytest.raises(sqlite3.IntegrityError):
        with store.transaction() as db:
            db.execute("INSERT INTO evidence VALUES ('e','missing',NULL,'file','x','now','completed','{}')")


def test_corrupt_database_preserved(tmp_path):
    paths = Paths.resolve(str(tmp_path))
    paths.database.write_bytes(b"invalid database")
    with pytest.raises(StorageError): Store(paths)
    assert paths.database.read_bytes() == b"invalid database"


def test_newer_schema_rejected(store):
    with store.transaction() as db: db.execute("PRAGMA user_version=99")
    with pytest.raises(StorageError): Store(store.paths)


@pytest.mark.parametrize("invalid", [True, False])
def test_ledger_migration(store, tmp_path, invalid):
    source = tmp_path / "ledger.json"
    observation = {"algorithm": "SHA256", "hash": "a" * 64, "size_bytes": 3, "timestamp": "2025-01-01T00:00:00+00:00"}
    source.write_text(json.dumps({"C:\\Evidence Ω\\file": [observation if not invalid else {}]}))
    original = source.read_bytes()
    if invalid:
        with pytest.raises(StorageError): store.migrate_ledger(source)
        assert not store.rows("SELECT * FROM hash_observations")
    else:
        assert store.migrate_ledger(source)["imported"] == 1
        assert store.migrate_ledger(source)["already_imported"]
        row = store.rows("SELECT * FROM hash_observations")[0]
        assert row["timestamp"] == observation["timestamp"]
        assert row["digest"] == observation["hash"]
        assert Path(row["provenance"]).read_bytes() == original
    assert source.read_bytes() == original


def test_paths_windows_and_xdg(tmp_path):
    windows = Paths.resolve(platform="win32", env={"LOCALAPPDATA": str(tmp_path / "User Space")}, home=tmp_path)
    assert windows.data == tmp_path / "User Space" / "JOCKY"
    linux = Paths.resolve(platform="linux", env={"XDG_DATA_HOME": str(tmp_path / "数据")}, home=tmp_path)
    assert linux.data == tmp_path / "数据" / "jocky"
    with pytest.raises(ValueError): Paths.resolve("relative")
    with pytest.raises(ValueError): Paths.resolve(platform="linux", env={"XDG_DATA_HOME": "relative"})


def test_collection_history_report_restart(service, store, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.service.process_snapshot", lambda *_, **__: {"status": "success", "processes": [{"pid": 1, "name": "python", "classification": "OBSERVED"}], "warnings": ["CURRENT OBSERVATION only"]})
    source = tmp_path / "résumé नमस्ते.pdf.exe"
    source.write_bytes(b"safe test fixture")
    case = service.create_case({"title": "Device Ω", "examiner": "Investigator"})
    service.collect(case["id"], {"paths": [str(source)]})
    assert wait(service, case["id"])["status"] == "completed"
    assert service.related(case["id"], "findings")
    reports = service.related(case["id"], "reports")
    assert len(reports) == 1
    report = reports[0]["payload"]
    assert report["status"] == "completed" and report["device"]["hostname"]
    assert report["schema_version"] == REPORT_SCHEMA_VERSION and report["evidence"]
    assert store.rows("SELECT * FROM hash_observations")
    assert source.read_bytes() == b"safe test fixture"
    service.close()
    restarted = Workstation(Store(store.paths))
    try:
        assert restarted.get_report(report["report_id"]) == report
        assert restarted.get_case(case["id"])["status"] == "completed"
    finally: restarted.close()


def test_partial_missing_file(service, tmp_path):
    case = service.create_case({})
    service.collect(case["id"], {"paths": [str(tmp_path / "missing")]})
    assert wait(service, case["id"])["status"] == "partially_completed"
    evidence = service.related(case["id"], "evidence")
    files = [record for record in evidence if record["type"] == "FILES"]
    assert files and files[-1]["status"] == "failed"
    assert files[-1]["payload"]["classification"] == "UNAVAILABLE"


def test_cancellation_and_duplicate(service, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def block():
        entered.set(); release.wait(3)
        return {"status": "success"}
    monkeypatch.setattr("backend.service.get_system_info", block)
    case = service.create_case({})
    service.collect(case["id"], {})
    assert entered.wait(2)
    with pytest.raises(ServiceError): service.collect(case["id"], {})
    assert service.cancel(case["id"])["cancellation_requested"]
    release.set()
    assert wait(service, case["id"])["status"] == "cancelled"


def test_restart_interrupted(store):
    with store.transaction() as db:
        db.execute("INSERT INTO investigations(id,title,created_at,status) VALUES ('i','Interrupted',?,'collecting')", (now(),))
    service = Workstation(store)
    try:
        assert service.get_case('i')["status"] == "interrupted"
        assert service.related('i', 'transitions')[-1]['state'] == 'interrupted'
    finally: service.close()


def test_auth_api_persistence_and_failed_command(service):
    app = create_app(service, 'token', 'instance')
    client = app.test_client()
    headers = {'Authorization': 'Bearer token', 'X-Jocky-Instance': 'instance'}
    assert client.get('/api/v1/health').status_code == 401
    assert client.get('/api/v1/health', headers={**headers, 'X-Jocky-Instance': 'wrong'}).status_code == 401
    assert client.get('/api/v1/health', headers={**headers, 'Authorization': 'Bearer wrong'}).status_code == 401
    assert client.get('/api/v1/health', headers={**headers, 'Origin': 'https://example.org'}).status_code == 403
    assert client.get('/api/v1/health', headers=headers).json['ready']
    case = client.post('/api/v1/investigations', json={'title': 'API'}, headers=headers).json
    result = client.post('/command', json={'command': 'INVALID', 'investigation_id': case['id']}, headers=headers)
    assert result.status_code == 400
    assert result.json['report']['status'] == 'failed'
    assert client.get('/api/v1/history', headers=headers).json['items'][0]['state'] == 'failed'
    assert client.get('/api/v1/investigations/missing', headers=headers).status_code == 404
    assert client.post('/api/v1/investigations', json=[], headers=headers).status_code == 400
    assert client.post('/api/v1/investigations/'+case['id']+'/report/export', json={'format':'pdf'}, headers=headers).status_code == 200


def test_pdf_unicode_and_persisted_content():
    data = {'report_id':'report-fixture', 'schema_version':2, 'status':'completed', 'investigation_id':'case-fixture', 'created_at': now(),
            'investigation': {'title':'Résumé Ω नमस्ते বাংলা', 'started_at': now()},
            'device': {'hostname':'test-host'}, 'evidence':[{'source': 'résumé file.txt', 'hash':'a'*64, 'status':'OBSERVED'}],
            'limitations':['Historical execution: UNAVAILABLE'], 'findings':[]}
    pdf = render_pdf(data)
    reader = PdfReader(io.BytesIO(pdf))
    text = '\n'.join(page.extract_text() for page in reader.pages)
    assert pdf.startswith(b'%PDF-')
    for value in ('JOCKY', 'report-fixture', 'test-host', 'UNAVAILABLE', 'résumé file.txt'):
        assert value in text


def test_storage_full_api_preserves_record(service, monkeypatch):
    case = service.create_case({'title':'Committed'})
    def full(_): raise OSError(errno.ENOSPC, 'No space left')
    monkeypatch.setattr(service, 'create_case', full)
    app = create_app(service, 'token', 'instance')
    result = app.test_client().post('/api/v1/investigations', json={}, headers={'Authorization':'Bearer token','X-Jocky-Instance':'instance'})
    assert result.status_code == 503
    assert service.get_case(case['id'])['title'] == 'Committed'


def test_process_unavailable(monkeypatch):
    import psutil
    from backend.collectors import process_snapshot
    class Process:
        pid = 12
        def name(self): return 'python'
        def exe(self): raise psutil.AccessDenied(12)
        def ppid(self): return 1
        def create_time(self): raise psutil.NoSuchProcess(12)
    monkeypatch.setattr(psutil, 'pids', lambda: [12])
    monkeypatch.setattr(psutil, 'Process', lambda pid: Process())
    snapshot = process_snapshot()
    row = snapshot['processes'][0]
    assert row['executable'] is None and row['started_at'] is None
    assert row['unavailable']['executable'] == 'permission_denied'
    assert row['unavailable']['started_at'] == 'process exited during collection'
    assert row['interpreter'] == 'python'
    assert snapshot['statistics']['permission_denied'] == 1
    assert snapshot['classification'] == 'CURRENT_OBSERVATION'


def test_sqlite_full_rolls_back_but_preserves_prior_commit(store):
    with store.transaction() as db:
        db.execute("INSERT INTO metadata VALUES ('committed','true')")
    with pytest.raises(sqlite3.OperationalError, match='full'):
        with store.transaction() as db:
            pages = db.execute('PRAGMA page_count').fetchone()[0]
            db.execute(f'PRAGMA max_page_count={pages}')
            db.execute("INSERT INTO metadata VALUES ('too_large',?)", ('x' * (1024 * 1024),))
    assert store.rows("SELECT * FROM metadata") == [{'key':'committed','value':'true'}]


def test_legacy_workstation_import_and_conflict_rollback(service, tmp_path):
    from backend.workstation_view import import_legacy
    report = {'report_id':'legacy-report','schema_version':1,'timestamp':now(),'result':{},'status':'failed'}
    data = {'store_version':1,'investigations':[{'id':'legacy-case','title':'Old case','opened_at':now()}],
            'executions':[{'id':'legacy-execution','case_id':'legacy-case','submitted_at':now(),'command_text':'INVALID','outcome':'failed','report':report}]}
    source = tmp_path / 'workstation_records.json'
    source.write_text(encode(data))
    original = source.read_bytes()
    result = import_legacy(service, source)
    assert result['executions_imported'] == 1
    assert Path(result['backup']).read_bytes() == original
    assert import_legacy(service, source)['already_imported']
    assert service.get_report('legacy-report') == report
    data['investigations'].append({'id':'new-case','title':'New case','opened_at':now()})
    source.write_text(encode(data))
    with pytest.raises(ServiceError): import_legacy(service, source)
    assert not service.store.rows("SELECT * FROM investigations WHERE id='new-case'")


@pytest.mark.parametrize('data', [{}, {'store_version':1,'investigations':[],'executions':[{}]}, {'store_version':99}])
def test_malformed_legacy_store_never_imports(service, tmp_path, data):
    from backend.workstation_view import import_legacy
    source = tmp_path/'invalid.json'; source.write_text(encode(data))
    with pytest.raises(ServiceError): import_legacy(service, source)
    assert not service.list_cases()


def test_failed_collector_gets_durable_report(service, monkeypatch):
    monkeypatch.setattr('backend.service.process_snapshot', lambda *_, **__: (_ for _ in ()).throw(KeyError('unexpected collector bug')))
    case = service.create_case({})
    service.collect(case['id'], {})
    assert wait(service, case['id'])['status'] == 'partially_completed'
    # The terminal state can precede the failure report transaction briefly.
    service.queue.join()
    report = service.related(case['id'], 'reports')[-1]['payload']
    assert report['status'] == 'partially_completed'
    assert any(execution['state'] == 'failed' for execution in report['executions'])
    processes = [record for record in report['evidence'] if record['type'] == 'PROCESSES']
    assert processes and processes[-1]['status'] == 'failed'


def test_report_final_state_matches_timeline(service, monkeypatch):
    monkeypatch.setattr('backend.service.process_snapshot', lambda *_, **__: {'status':'success','processes':[]})
    case = service.create_case({})
    service.collect(case['id'], {})
    wait(service, case['id']); service.queue.join()
    report = service.related(case['id'], 'reports')[-1]['payload']
    assert report['timeline'][-1]['state'] == report['status']
    assert report['timeline'][-1]['timestamp'] == report['investigation']['completed_at']


def test_pdf_generation_failure_does_not_change_report(service, monkeypatch):
    monkeypatch.setattr('backend.service.process_snapshot', lambda *_, **__: {'status':'success','processes':[]})
    case = service.create_case({}); service.collect(case['id'], {})
    wait(service, case['id']); service.queue.join()
    original = service.related(case['id'], 'reports')
    monkeypatch.setattr('backend.api.render_pdf', lambda _: (_ for _ in ()).throw(RuntimeError('font problem')))
    app = create_app(service,'token','instance')
    response = app.test_client().post(f"/api/v1/investigations/{case['id']}/report/export", json={}, headers={'Authorization':'Bearer token','X-Jocky-Instance':'instance'})
    assert response.status_code == 500
    assert service.related(case['id'], 'reports') == original
