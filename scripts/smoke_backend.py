"""Real process integration: bootstrap/auth/collection/restart/PDF/clean shutdown."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def start(command, workspace):
    process = subprocess.Popen([*command, '--workspace', str(workspace)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
    for _ in range(10):
        line = process.stdout.readline()
        if not line: raise RuntimeError('Backend exited during bootstrap: ' + process.stderr.read())
        message = json.loads(line)
        if message['event'] == 'startup_error': raise RuntimeError(str(message['error']))
        if message['event'] == 'ready': return process, message
    raise RuntimeError('No readiness record')


def request(session, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{session['port']}{path}", data=data,
        headers={'Authorization': 'Bearer '+session['token'], 'X-Jocky-Instance': session['instance_id'], 'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=60) as response:
        payload = response.read()
        return payload if response.headers['Content-Type'].startswith('application/pdf') else json.loads(payload)


def stop(process, session):
    request(session, '/api/v1/shutdown', {})
    process.wait(timeout=15)
    assert process.returncode == 0, process.stderr.read()
    process.stdin.close()


def smoke(command, workspace):
    process, session = start(command, workspace)
    try:
        assert request(session, '/api/v1/health')['ready']
        source = workspace / 'Unicode नमस्ते space.txt'
        source.write_text('Forensic test fixture Ω', encoding='utf-8')
        case = request(session, '/api/v1/investigations', {'title':'Smoke investigation नमस्ते', 'examiner':'Integration test'})
        request(session, f"/api/v1/investigations/{case['id']}/collect", {'paths':[str(source)]})
        for _ in range(100):
            case = request(session, '/api/v1/investigations/'+case['id'])
            if case['status'] in ('completed','partially_completed','failed'): break
            time.sleep(.1)
        assert case['status'] in ('completed','partially_completed'), case
        # Historical execution evidence, artifacts, findings and the merged
        # timeline must be produced by the frozen engine, not only by source.
        history = request(session, f"/api/v1/investigations/{case['id']}/execution-events")['items']
        artifacts = request(session, f"/api/v1/investigations/{case['id']}/artifacts")['items']
        findings = request(session, f"/api/v1/investigations/{case['id']}/findings")['items']
        event_timeline = request(session, f"/api/v1/investigations/{case['id']}/event-timeline")['items']
        stored = request(session, f"/api/v1/investigations/{case['id']}/reports")['items'][-1]['payload']
        assert stored['schema_version'] == 4, stored['schema_version']
        assert stored['collection_window']['bounded'] is True
        assert stored['appendix_process_listing'], 'the process listing must survive in the appendix'
        # Counts must be named for what they are, and command history must never
        # be reported as confirmed execution.
        counts = stored['record_counts']
        assert set(counts) >= {'execution_source_records', 'command_history_records', 'session_records'}
        kinds = {event['evidence_kind'] for event in history}
        assert kinds <= {'EXECUTION_EVIDENCE', 'COMMAND_HISTORY', 'SESSION_EVENT'}, kinds
        for event in history:
            if event['evidence_kind'] == 'COMMAND_HISTORY':
                assert event['execution_confirmed'] is False, event['reference']
            assert event['reference'], 'every record needs a citable identifier'
        # Where a source recorded the whole command, it must be preserved whole.
        with_commands = [event for event in history if event['full_command_line']]
        assert all(event['command_reconstruction_status'] in ('EXACT', 'PARTIAL')
                   for event in with_commands)
        triage = stored['triage']['counts']
        assert set(triage) == {'POTENTIALLY_HARMFUL', 'NEEDS_REVIEW',
                               'NOT_HARMFUL_ON_AVAILABLE_EVIDENCE'}
        sources = stored['historical_execution']['sources']
        assert sources, 'every telemetry source must be reported, available or not'
        assert all(source['status'] in ('AVAILABLE','NOT_AVAILABLE','NOT_ENABLED','PERMISSION_DENIED')
                   for source in sources), sources
        assert all(event['classification'] == 'HISTORICAL_EVIDENCE' for event in history)
        assert findings, 'an investigation with evidence must not end with zero findings'
        telemetry = stored['historical_execution']['telemetry_available']
        stop(process, session)
        process, session = start(command, workspace)
        saved = request(session, '/api/v1/investigations/'+case['id'])
        assert saved['status'] == case['status']
        pdf = request(session, '/api/v1/investigations/'+case['id']+'/report/export', {'format':'pdf'})
        assert pdf.startswith(b'%PDF-')
        (workspace / 'smoke-report.pdf').write_bytes(pdf)
        assert request(session, '/api/v1/history')['items']
        # The analysis must survive the restart, not be rebuilt on demand.
        assert len(request(session, f"/api/v1/investigations/{case['id']}/execution-events")['items']) == len(history)
        stop(process, session)
        print(json.dumps({'result':'passed','investigation_id':case['id'],'status':case['status'],
                          'pdf_bytes':len(pdf),'historical_telemetry':telemetry,
                          'execution_events':len(history),'artifacts':len(artifacts),
                          'findings':len(findings),'timeline_entries':len(event_timeline),
                          'record_counts':counts,'triage':triage,
                          'longest_command':max((len(e['full_command_line'] or '') for e in history), default=0),
                          'sources':{source['name']: source['status'] for source in sources},
                          'workspace':str(workspace)}))
    finally:
        if process.poll() is None: process.kill(); process.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--executable')
    parser.add_argument('--workspace')
    args = parser.parse_args()
    command = [str(Path(args.executable).resolve())] if args.executable else [sys.executable, '-m', 'backend.runtime']
    if args.workspace:
        workspace = Path(args.workspace).resolve(); workspace.mkdir(parents=True, exist_ok=True)
        smoke(command, workspace)
    else:
        with tempfile.TemporaryDirectory(prefix='jocky smoke ') as directory: smoke(command, Path(directory))
