import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:jocky_client/core/errors/failure.dart';
import 'package:jocky_client/models/cases/investigation.dart';
import 'package:jocky_client/models/executions/execution_record.dart';
import 'package:jocky_client/models/reports/report.dart';
import 'package:jocky_client/services/storage/record_store.dart';

import '../support/fixtures.dart';

void main() {
  late Directory temp;
  late FileRecordStore store;

  setUp(() async {
    temp = await Directory.systemTemp.createTemp('jocky-records-');
    store = FileRecordStore(directoryResolver: () async => temp);
  });

  tearDown(() async {
    if (temp.existsSync()) await temp.delete(recursive: true);
  });

  test('an absent store loads as empty rather than failing', () async {
    expect((await store.load()).executions, isEmpty);
  });

  test('records survive a save/load round trip with their engine report intact', () async {
    final report = ForensicReport.fromJson(
      loadFixture('hash')['report'] as Map<String, dynamic>,
    )!;
    final execution = ExecutionRecord(
      id: 'EXEC-1',
      submittedAt: DateTime.utc(2026, 9, 12, 17, 54, 54),
      commandText: 'HASH FILE "नमूना evidence.bin"',
      outcome: ExecutionOutcome.completed,
      origin: ExecutionOrigin.guidedTool,
      caseId: 'CASE-1',
      clientElapsedMs: 42,
      report: report,
    );
    final investigation = Investigation(
      id: 'CASE-1',
      title: ' Операция «Тест»',
      openedAt: DateTime.utc(2026, 9, 12),
      reference: 'FIR/2026/0042',
      notes: 'Multi-line\nnotes with unicode: नमूना',
      evidence: [
        EvidenceSource(
          id: 'EV-1',
          path: r'C:\Case Files\नमूना evidence.bin',
          isDirectory: false,
          addedAt: DateTime.utc(2026, 9, 12),
        ),
      ],
    );

    await store.save(WorkstationRecords(
      investigations: [investigation],
      executions: [execution],
      activeCaseId: 'CASE-1',
    ));
    final loaded = await store.load();

    expect(loaded.activeCaseId, 'CASE-1');
    expect(loaded.investigations.single.title, ' Операция «Тест»');
    expect(loaded.investigations.single.evidence.single.path,
        r'C:\Case Files\नमूना evidence.bin');
    expect(loaded.executions.single.commandText, contains('नमूना'));
    // The engine's report must round trip byte-equivalently, not be re-derived.
    expect(
      jsonEncode(loaded.executions.single.report!.toJson()),
      jsonEncode(report.toJson()),
    );
  });

  test('a Windows-style long path is stored without truncation or rewriting', () async {
    // Windows extended-length path, well past MAX_PATH.
    final segments = 'deep_directory_segment\\' * 12;
    final longPath = r'\\?\C:\Case Files\' '$segments' 'evidence.bin';
    final investigation = Investigation(
      id: 'CASE-L',
      title: 'Long path case',
      openedAt: DateTime.utc(2026),
      evidence: [
        EvidenceSource(
          id: 'EV-L',
          path: longPath,
          isDirectory: false,
          addedAt: DateTime.utc(2026),
        ),
      ],
    );

    await store.save(WorkstationRecords(investigations: [investigation]));
    final loaded = await store.load();

    expect(loaded.investigations.single.evidence.single.path, longPath);
    expect(loaded.investigations.single.evidence.single.path.length, greaterThan(200));
  });

  test('a corrupt store is reported and left untouched, never silently reset', () async {
    final file = File('${temp.path}/${RecordStore.fileName}');
    await file.writeAsString('{not valid json');

    await expectLater(
      store.load(),
      throwsA(
        isA<JockyFailure>()
            .having((f) => f.kind, 'kind', FailureKind.localStorage)
            .having((f) => f.message, 'message', contains('corrupt')),
      ),
    );
    // The analyst's file is still on disk for manual recovery.
    expect(await file.readAsString(), '{not valid json');
  });

  test('a store whose root is not an object is rejected', () async {
    await File('${temp.path}/${RecordStore.fileName}').writeAsString('[]');

    await expectLater(store.load(), throwsA(isA<JockyFailure>()));
  });

  test('unparseable individual entries are dropped without losing the rest', () async {
    await File('${temp.path}/${RecordStore.fileName}').writeAsString(jsonEncode({
      'store_version': 1,
      'investigations': [
        {'id': 'CASE-OK', 'title': 'Kept', 'opened_at': '2026-09-12T00:00:00Z'},
        {'title': 'No id, no timestamp'},
      ],
      'executions': [],
    }));

    final loaded = await store.load();

    expect(loaded.investigations, hasLength(1));
    expect(loaded.investigations.single.id, 'CASE-OK');
  });

  test('saving writes atomically and leaves no temp file behind', () async {
    await store.save(const WorkstationRecords());

    final files = temp.listSync().map((e) => e.path.split('/').last).toList();
    expect(files, contains(RecordStore.fileName));
    expect(files.where((name) => name.endsWith('.tmp')), isEmpty);
  });
}
