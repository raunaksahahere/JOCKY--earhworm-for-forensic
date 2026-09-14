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
        # Binary responses come back as bytes; everything else is JSON. Keyed on
        # the declared type rather than on trying to decode and hoping.
        content_type = response.headers['Content-Type'] or ''
        binary = content_type.startswith(('application/pdf', 'application/zip',
                                          'application/octet-stream'))
        return payload if binary else json.loads(payload)


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
        # Program-selected sources as well as the baseline: each of these reads
        # data the frozen bundle has to carry, and a missing data file makes the
        # module fail to import rather than degrade. That is how the packaged
        # engine was found to be shipping without the investigation grammar and
        # the driver reference.
        request(session, f"/api/v1/investigations/{case['id']}/collect",
                {'paths':[str(source)], 'sources':['NETWORK','USB','DRIVERS','SERVICES']})
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            case = request(session, '/api/v1/investigations/'+case['id'])
            if case['status'] in ('completed','partially_completed','failed'): break
            time.sleep(.5)
        assert case['status'] in ('completed','partially_completed'), (
            f"collection did not finish: status {case['status']}")
        # Every selected source must have produced an evidence record, whether
        # it succeeded or not. A source that simply vanishes is the failure this
        # checks for.
        evidence = {row['type'] for row in request(
            session, f"/api/v1/investigations/{case['id']}/evidence")['items']}
        missing = {'NETWORK','USB','DRIVERS','SERVICES'} - evidence
        assert not missing, f"selected sources produced no evidence record: {sorted(missing)}"
        # The investigation program is what makes the run reproducible.
        programs = request(session, f"/api/v1/investigations/{case['id']}/program")['items']
        assert programs and programs[0]['plan']['platform'] == 'linux', programs
        # Historical execution evidence, artifacts, findings and the merged
        # timeline must be produced by the frozen engine, not only by source.
        history = request(session, f"/api/v1/investigations/{case['id']}/execution-events")['items']
        artifacts = request(session, f"/api/v1/investigations/{case['id']}/artifacts")['items']
        findings = request(session, f"/api/v1/investigations/{case['id']}/findings")['items']
        event_timeline = request(session, f"/api/v1/investigations/{case['id']}/event-timeline")['items']
        stored = request(session, f"/api/v1/investigations/{case['id']}/reports")['items'][-1]['payload']
        assert stored['schema_version'] >= 4, stored['schema_version']
        # Priority must be present, explainable and separate from classification.
        priorities = stored['triage']['priorities']
        assert set(priorities) == {'PRIORITY_1', 'PRIORITY_2', 'PRIORITY_3'}, priorities
        for lead in stored['leads']:
            assert lead['priority'] in ('PRIORITY_1', 'PRIORITY_2'), lead['priority']
            assert lead['why'], 'a lead must say why it matters'
            assert lead['evidence_references'], 'a lead must cite the records behind it'
            assert lead['commands'], 'a lead must show the commands it covers'
        # Threads group related activity without losing individual records.
        for thread in stored['threads']:
            assert thread['thread_id'] and thread['evidence_references']
            assert thread['activity_count'] >= 2, 'a single activity is not a thread'
            assert 'does not state what anyone intended' in thread['note']
        # The short timeline is bounded; the full one is not discarded.
        significant = stored['significant_events']
        assert significant['entry_count'] <= 40
        assert 'remain in the evidence package' in significant['note']
        assert stored['conclusion'], 'the overview must interpret the numbers'
        # Missing arguments are a limitation, never a concern signal.
        for group in stored['activity']['groups']:
            if group['command_reconstruction_status'] in ('EXECUTABLE_ONLY', 'NOT_AVAILABLE'):
                assert all(signal['weight'] <= 0 or not signal['name'].startswith(('remote_', 'download_'))
                           for signal in group['classification']['signals'])
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

        # --- what an investigator actually does with a finished collection ---
        # Recognition must have run and been stored, not recomputed on demand.
        recognition = stored['recognition']
        assert recognition['artifacts_recognized'] > 0, (
            'the packaged engine recognized nothing; check the reference data is bundled')
        assert 'not a statement that the file is safe' in recognition['note']

        # A review brief for the highest-priority thing in the collection.
        subject = (stored['leads'][0]['evidence_references'][0] if stored['leads']
                   else history[0]['reference'])
        brief = request(session, f"/api/v1/investigations/{case['id']}/briefs",
                        {'subject_type': 'activity', 'subject_id': subject})
        assert brief['evidence_ids'], 'a brief must cite the evidence it rests on'
        assert brief['unknown'], 'a brief must state what it does not know'
        assert 'not a malware verdict' in brief['disclaimer']
        brief_pdf = request(session, f"/api/v1/investigations/{case['id']}/briefs/export",
                            {'subject_type': 'activity', 'subject_id': subject})
        assert brief_pdf.startswith(b'%PDF-')
        (workspace / 'smoke-brief.pdf').write_bytes(brief_pdf)

        # An artifact brief, which is the other half of the workload question.
        artifact_brief = request(session, f"/api/v1/investigations/{case['id']}/briefs",
                                 {'subject_type': 'artifact',
                                  'subject_id': artifacts[0]['reference']})
        assert artifact_brief['recognition']['state'] in ('RECOGNIZED', 'UNKNOWN')

        # The routine report must be separate, grouped, and never called safe.
        routine = request(session, f"/api/v1/investigations/{case['id']}/routine")
        assert routine['groups'], 'nothing was presented as routine'
        assert routine['totals']['records'] > routine['group_count'], (
            'the routine report is not grouping anything')
        for group in routine['groups']:
            assert group['evidence_references'], 'a group with no evidence cannot be checked'
        assert 'not a guarantee' in routine['note']
        routine_pdf = request(session, f"/api/v1/investigations/{case['id']}/routine/export", {})
        assert routine_pdf.startswith(b'%PDF-')
        (workspace / 'smoke-routine.pdf').write_bytes(routine_pdf)

        # Search must reach past the command line.
        recognized_name = recognition['software'][0]['name']
        found = request(session,
                        f"/api/v1/investigations/{case['id']}/search?q={recognized_name}")
        assert found['total'] > 0, f'search found nothing for {recognized_name}'

        # The generated summary, with the evidence behind each sentence.
        summary = request(session, f"/api/v1/investigations/{case['id']}/summary")
        assert summary['statements'], 'no case summary was generated'
        assert 'not a verdict' in summary['closing']
        assert request(session, f"/api/v1/investigations/{case['id']}/narrative")['items']

        # The evidence package, and its own manifest.
        package = request(session, f"/api/v1/investigations/{case['id']}/package", {})
        (workspace / 'smoke-package.zip').write_bytes(package)
        import io as _io, json as _json, zipfile as _zipfile
        with _zipfile.ZipFile(_io.BytesIO(package)) as archive:
            manifest = _json.loads(archive.read('MANIFEST.json'))
            names = set(archive.namelist())
        assert manifest['versions']['application'], 'the package must name the version'
        assert manifest['files'], 'the manifest lists no files'
        assert {'report.json', 'README.txt', 'investigator-report.pdf'} <= names
        import hashlib as _hashlib
        with _zipfile.ZipFile(_io.BytesIO(package)) as archive:
            for entry in manifest['files']:
                digest = _hashlib.sha256(archive.read(entry['name'])).hexdigest()
                assert digest == entry['sha256'], f"{entry['name']} does not match its digest"
        assert request(session, '/api/v1/history')['items']
        # The analysis must survive the restart, not be rebuilt on demand.
        assert len(request(session, f"/api/v1/investigations/{case['id']}/execution-events")['items']) == len(history)
        stop(process, session)
        print(json.dumps({'result':'passed','investigation_id':case['id'],'status':case['status'],
                          'pdf_bytes':len(pdf),'brief_pdf_bytes':len(brief_pdf),
                          'routine_pdf_bytes':len(routine_pdf),'package_bytes':len(package),
                          'package_files':len(manifest['files']),
                          'recognized_artifacts':recognition['artifacts_recognized'],
                          'routine_groups':routine['group_count'],
                          'summary_statements':len(summary['statements']),
                          'historical_telemetry':telemetry,
                          'execution_events':len(history),'artifacts':len(artifacts),
                          'findings':len(findings),'timeline_entries':len(event_timeline),
                          'record_counts':counts,'triage':triage,'priorities':priorities,
                          'leads':[{'lead':lead.get('lead_id'),'priority':lead['priority'],
                                    'title':lead['title'],'activities':lead['activity_count']}
                                   for lead in stored['leads']],
                          'threads':len(stored['threads']),
                          'significant_events':significant['entry_count'],
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
