import 'package:flutter_test/flutter_test.dart';
import 'package:jocky_client/services/storage/api_record_store.dart';
import 'package:jocky_client/services/storage/record_store.dart';

import '../support/fake_transport.dart';
import '../support/harness.dart';

/// Clearing history must reach the engine.
///
/// The original defect: the controller committed a record with an empty
/// execution list, but `save` sends case metadata only — the engine owns the
/// execution record — so nothing was deleted and the next refresh brought every
/// execution back. The button appeared to do nothing at all.
void main() {
  late FakeTransport transport;
  late ApiRecordStore store;

  Map<String, dynamic> workstation({int executions = 3}) => {
        'store_version': 1,
        'investigations': const [],
        'active_case_id': null,
        'executions': [
          for (var index = 0; index < executions; index++)
            {
              'id': 'EXEC-$index',
              'submitted_at': '2026-09-13T12:00:00+00:00',
              'command_text': 'SYSTEM INFO',
              'outcome': 'completed',
              'origin': 'command_center',
            },
        ],
      };

  setUp(() {
    transport = FakeTransport();
    store = ApiRecordStore(bootstrappedApi(transport));
  });

  test('clearing asks the engine instead of saving an empty record', () async {
    transport.respondJson('/api/v1/history/clear', {
      'deleted': 3,
      'retained': 0,
      'retained_reason': null,
    });

    final clearance = await store.clearExecutionHistory();

    expect(clearance.deleted, 3);
    final paths = transport.requests.map((request) => request.uri.path).toList();
    expect(paths, contains('/api/v1/history/clear'));
    expect(
      paths,
      isNot(contains('/api/v1/workstation')),
      reason: 'saving case metadata never deleted an execution and never will',
    );
  });

  test('retained evidence is reported, not presented as a failure', () async {
    transport.respondJson('/api/v1/history/clear', {
      'deleted': 2,
      'retained': 5,
      'retained_reason': 'Executions belonging to an investigation are forensic records.',
    });

    final clearance = await store.clearExecutionHistory();

    expect(clearance.retained, 5);
    expect(clearance.summary, contains('2 execution records deleted'));
    expect(clearance.summary, contains('5 kept'));
    expect(clearance.summary, contains('forensic records'));
  });

  test('a clearance that removed nothing still says so', () async {
    transport.respondJson('/api/v1/history/clear', {'deleted': 0, 'retained': 0});

    final clearance = await store.clearExecutionHistory();

    expect(clearance.summary, '0 execution records deleted.');
  });

  test('save still sends only case metadata', () async {
    transport.respondJson('/api/v1/workstation', workstation());

    await store.save(WorkstationRecords.empty);

    final body = transport.requests.last.body as String;
    expect(body, contains('investigations'));
    expect(body, isNot(contains('executions')),
        reason: 'the engine is authoritative for executions');
  });

  test('an in-memory store clears its own records', () async {
    final memory = InMemoryRecordStore(
      WorkstationRecords.fromJson(workstation(executions: 4)),
    );

    final clearance = await memory.clearExecutionHistory();

    expect(clearance.deleted, 4);
    expect((await memory.load()).executions, isEmpty);
  });
}
