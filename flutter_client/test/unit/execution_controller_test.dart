import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:jocky_client/core/errors/failure.dart';
import 'package:jocky_client/models/cases/investigation.dart';
import 'package:jocky_client/models/executions/execution_record.dart';
import 'package:jocky_client/services/storage/record_store.dart';
import 'package:jocky_client/state/providers.dart';

import '../support/fake_transport.dart';
import '../support/fixtures.dart';
import '../support/harness.dart';

void main() {
  late FakeTransport transport;

  setUp(() {
    transport = FakeTransport();
    addTearDownDispose = (container) => addTearDown(container.dispose);
  });

  ProviderContainer containerWith({WorkstationRecords records = WorkstationRecords.empty}) =>
      testContainer(transport: transport, records: records);

  test('a successful command records a completed execution with its report', () async {
    transport.respondJson('/command', loadFixture('hash'));
    final container = containerWith();

    final record = await container
        .read(executionControllerProvider.notifier)
        .execute('HASH FILE "नमूना evidence.bin"');

    expect(record!.outcome, ExecutionOutcome.completed);
    expect(record.reportId, startsWith('JCK-'));
    expect(record.engineElapsedMs, isNotNull);
    expect(container.read(executionControllerProvider).phase, ExecutionPhase.completed);
    expect(container.read(executionHistoryProvider).single.id, record.id);
  });

  test('a parser rejection is recorded as failed and keeps the engine report', () async {
    transport.respondJson('/command', loadFixture('syntax_error'), status: 400);
    final container = containerWith();

    final record =
        await container.read(executionControllerProvider.notifier).execute('HASH FIL x');

    expect(record!.outcome, ExecutionOutcome.failed);
    expect(record.failureKind, FailureKind.commandSyntax);
    expect(record.failureCode, 'invalid_syntax');
    expect(record.report, isNotNull, reason: 'the engine reports malformed input too');
    expect(record.summary, contains('line 1, column 6'));
    expect(container.read(executionControllerProvider).phase, ExecutionPhase.failed);
  });

  test('an execution failure keeps the parsed action for the archive', () async {
    transport.respondJson('/command', loadFixture('notfound'), status: 400);
    final container = containerWith();

    final record = await container
        .read(executionControllerProvider.notifier)
        .execute('HASH FILE /nonexistent/zzz.bin');

    expect(record!.failureCode, 'not_found');
    expect(record.action, 'hash');
  });

  test('an unreachable engine records the failure without inventing a result', () async {
    transport.fail('/command', const SocketException('Connection refused'));
    final container = containerWith();

    final record =
        await container.read(executionControllerProvider.notifier).execute('SYSTEM INFO');

    expect(record!.outcome, ExecutionOutcome.failed);
    expect(record.failureKind, FailureKind.backendUnavailable);
    expect(record.report, isNull);
    expect(container.read(executionControllerProvider).response, isNull);
  });

  test('abandoning marks the execution abandoned, not cancelled on the engine', () async {
    transport.delay('/command', const Duration(seconds: 5), http.Response('{}', 200));
    final container = containerWith();
    final controller = container.read(executionControllerProvider.notifier);

    final pending = controller.execute('PROCESSES');
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(container.read(executionControllerProvider).isRunning, isTrue);
    controller.abandon();
    final record = await pending;

    expect(record!.outcome, ExecutionOutcome.abandoned);
    expect(record.summary, contains('abandoned by this client'));
    expect(container.read(executionControllerProvider).phase, ExecutionPhase.abandoned);
  });

  test('a second command is refused while one is in flight', () async {
    transport.delay('/command', const Duration(milliseconds: 200), http.Response('{}', 200));
    final container = containerWith();
    final controller = container.read(executionControllerProvider.notifier);

    final first = controller.execute('PROCESSES');
    await Future<void>.delayed(const Duration(milliseconds: 10));
    final second = await controller.execute('SYSTEM INFO');

    expect(second, isNull, reason: 'the dispatcher is synchronous; one command at a time');
    controller.abandon();
    await first;
  });

  test('executions are attributed to the active case', () async {
    transport.respondJson('/command', loadFixture('system'));
    final container = containerWith(
      records: WorkstationRecords(
        activeCaseId: 'CASE-7',
        investigations: [
          Investigation(id: 'CASE-7', title: 'Seized laptop', openedAt: DateTime.utc(2026)),
        ],
      ),
    );

    final record =
        await container.read(executionControllerProvider.notifier).execute('SYSTEM INFO');

    expect(record!.caseId, 'CASE-7');
  });

  test('with no active case the execution is recorded as unattributed', () async {
    transport.respondJson('/command', loadFixture('system'));
    final container = containerWith();

    final record =
        await container.read(executionControllerProvider.notifier).execute('SYSTEM INFO');

    expect(record!.caseId, isNull);
  });

  test('the command text is submitted verbatim', () async {
    transport.respondJson('/command', loadFixture('hash'));
    final container = containerWith();
    const command = 'HASH FILE "C:\\Case Files\\नमूना.bin"';

    await container.read(executionControllerProvider.notifier).execute(command);

    expect(transport.requests.where((r) => r.uri.path == '/command').single.body, contains(r'C:\\Case Files\\नमूना.bin'));
  });

  test('the report archive holds only executions that produced a report', () async {
    transport.respondJson('/command', loadFixture('system'));
    final container = containerWith();
    await container.read(executionControllerProvider.notifier).execute('SYSTEM INFO');

    transport.fail('/command', const SocketException('Connection refused'));
    await container.read(executionControllerProvider.notifier).execute('PROCESSES');

    expect(container.read(executionHistoryProvider), hasLength(2));
    expect(container.read(reportArchiveProvider), hasLength(1));
  });
}
