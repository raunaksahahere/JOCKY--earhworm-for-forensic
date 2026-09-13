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
        stop(process, session)
        process, session = start(command, workspace)
        saved = request(session, '/api/v1/investigations/'+case['id'])
        assert saved['status'] == case['status']
        pdf = request(session, '/api/v1/investigations/'+case['id']+'/report/export', {'format':'pdf'})
        assert pdf.startswith(b'%PDF-')
        (workspace / 'smoke-report.pdf').write_bytes(pdf)
        assert request(session, '/api/v1/history')['items']
        stop(process, session)
        print(json.dumps({'result':'passed','investigation_id':case['id'],'status':case['status'],'pdf_bytes':len(pdf),'workspace':str(workspace)}))
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
