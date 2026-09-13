import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jocky_client/core/errors/failure.dart';
import 'package:jocky_client/features/history/history_screen.dart';
import 'package:jocky_client/features/investigations/investigations_screen.dart';
import 'package:jocky_client/features/reports/report_detail_screen.dart';
import 'package:jocky_client/features/reports/reports_screen.dart';
import 'package:jocky_client/features/system_status/system_status_screen.dart';
import 'package:jocky_client/features/tools/tools_screen.dart';
import 'package:jocky_client/models/cases/investigation.dart';
import 'package:jocky_client/models/executions/execution_record.dart';
import 'package:jocky_client/models/reports/report.dart';
import 'package:jocky_client/services/storage/record_store.dart';

import '../support/fake_transport.dart';
import '../support/fixtures.dart';
import '../support/harness.dart';

ExecutionRecord recordFrom(
  String fixture, {
  required String id,
  ExecutionOutcome outcome = ExecutionOutcome.completed,
  String? caseId,
  String? failureCode,
  String? failureMessage,
}) {
  final body = loadFixture(fixture);
  return ExecutionRecord(
    id: id,
    submittedAt: DateTime.utc(2026, 9, 12, 17, 54),
    commandText: body['command'] as String,
    outcome: outcome,
    origin: ExecutionOrigin.commandCenter,
    caseId: caseId,
    clientElapsedMs: 31,
    report: ForensicReport.fromJson(body['report'] as Map<String, dynamic>),
    failureCode: failureCode,
    failureMessage: failureMessage,
  );
}

void main() {
  late FakeTransport transport;

  setUp(() {
    transport = FakeTransport();
    transport.respondJson('/health', loadFixture('health'));
    transport.respondJson('/commands', loadFixture('commands'));
  });

  Future<void> pump(
    WidgetTester tester,
    Widget screen, {
    WorkstationRecords records = WorkstationRecords.empty,
    JockyFailure? recordFailure,
    FakeFileSelection? fileSelection,
    Size size = const Size(1500, 1000),
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(harness(
      screen,
      transport: transport,
      records: records,
      recordFailure: recordFailure,
      fileSelection: fileSelection,
    ));
    await tester.pumpAndSettle();
  }

  group('Tools', () {
    testWidgets('offers only the actions the engine publishes', (tester) async {
      await pump(tester, const ToolsScreen());

      // Once in the action list, once as the selected form's title.
      expect(find.text('Hash a file'), findsNWidgets(2));
      expect(find.text('Search for a filename'), findsOneWidget);
      expect(find.text('Observe running processes'), findsOneWidget);
      expect(find.text('NOT PUBLISHED BY THIS ENGINE'), findsNothing);
    });

    testWidgets('hides a form when the engine does not publish that action',
        (tester) async {
      final trimmed = loadFixture('commands');
      final commands = (trimmed['commands'] as List)
          .where((entry) => (entry as Map)['name'] != 'PROCESSES')
          .toList();
      transport.respondJson('/commands', {...trimmed, 'commands': commands});

      await pump(tester, const ToolsScreen());

      expect(find.text('NOT PUBLISHED BY THIS ENGINE'), findsOneWidget);
      expect(find.text('Observe running processes'), findsOneWidget);
      // Listed as unavailable, never selectable as a form.
      await tester.tap(find.text('Observe running processes'));
      await tester.pumpAndSettle();
      expect(find.text('Run observation'), findsOneWidget);
      expect(find.text('Hash a file'), findsWidgets);
    });

    testWidgets('builds the exact command text before anything is submitted',
        (tester) async {
      final selection = FakeFileSelection(file: '/evidence/case 1/image.bin');
      await pump(tester, const ToolsScreen(), fileSelection: selection);

      expect(find.textContaining('Complete the fields above'), findsOneWidget);
      await tester.tap(find.text('Browse'));
      await tester.pumpAndSettle();

      expect(find.text('HASH FILE "/evidence/case 1/image.bin"'), findsOneWidget);
      expect(transport.requests.where((r) => r.uri.path == '/command'), isEmpty);
    });

    testWidgets('running a guided tool submits through the shared execution path',
        (tester) async {
      transport.respondJson('/command', loadFixture('system'));
      await pump(tester, const ToolsScreen());

      await tester.tap(find.text('Observe the host'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Run observation'));
      await tester.pumpAndSettle();

      expect(transport.requests.where((r) => r.uri.path == '/command'), hasLength(1));
      expect(find.text('Observation returned'), findsOneWidget);
    });

    testWidgets('destructive encryption is never offered as an observation', (tester) async {
      await pump(tester, const ToolsScreen());
      expect(find.text('Legacy in-place encryption'), findsNothing);
      expect(find.text('Overwrite this file?'), findsNothing);
      expect(transport.requests.where((r) => r.uri.path == '/command'), isEmpty);
    });
  });

  group('Reports', () {
    testWidgets('an empty archive explains the backend boundary', (tester) async {
      await pump(tester, const ReportsScreen());

      expect(find.text('No reports held yet'), findsOneWidget);
      expect(
        find.textContaining('Command reports are retained in backend SQLite'),
        findsOneWidget,
      );
    });

    testWidgets('lists held reports with their engine metadata', (tester) async {
      final records = WorkstationRecords(
        executions: [
          recordFrom('hash', id: 'EXEC-1'),
          recordFrom('notfound', id: 'EXEC-2', outcome: ExecutionOutcome.failed),
        ],
      );
      await pump(tester, const ReportsScreen(), records: records);

      expect(find.text('completed'), findsOneWidget);
      expect(find.text('failed'), findsOneWidget);
      expect(find.text('hash'), findsNWidgets(2));
      expect(find.textContaining('2 of 2 shown'), findsOneWidget);
    });

    testWidgets('search filters the archive', (tester) async {
      final records = WorkstationRecords(
        executions: [
          recordFrom('hash', id: 'EXEC-1'),
          recordFrom('system', id: 'EXEC-2'),
        ],
      );
      await pump(tester, const ReportsScreen(), records: records);

      await tester.enterText(find.byType(TextField).first, 'SYSTEM');
      await tester.pumpAndSettle();

      expect(find.textContaining('1 of 2 shown'), findsOneWidget);
    });
  });

  group('Report detail', () {
    testWidgets('renders the engine report, not a re-derived summary', (tester) async {
      final record = recordFrom('hash', id: 'EXEC-1');
      await pump(
        tester,
        const ReportDetailScreen(executionId: 'EXEC-1'),
        records: WorkstationRecords(executions: [record]),
      );

      // Shown in the header and again as the report id field.
      expect(find.text(record.reportId!), findsNWidgets(2));
      expect(find.text('Execution metadata'), findsOneWidget);
      expect(find.text('Export JSON'), findsOneWidget);
      expect(find.text('Export PDF'), findsOneWidget);
      // The raw timestamp with its offset stays visible alongside the formatted one.
      expect(find.textContaining('+00:00'), findsWidgets);
    });

    testWidgets('a missing execution says so instead of rendering blank', (tester) async {
      await pump(tester, const ReportDetailScreen(executionId: 'nope'));

      expect(
        find.textContaining('not in this workstation\'s records'),
        findsOneWidget,
      );
    });

    testWidgets('a failed execution shows the engine error and code', (tester) async {
      final record = recordFrom(
        'notfound',
        id: 'EXEC-9',
        outcome: ExecutionOutcome.failed,
        failureCode: 'not_found',
        failureMessage: 'Target not found: /nonexistent/zzz.bin',
      );
      await pump(
        tester,
        const ReportDetailScreen(executionId: 'EXEC-9'),
        records: WorkstationRecords(executions: [record]),
      );

      expect(find.text('Engine errors'), findsOneWidget);
      expect(find.textContaining('Target not found'), findsWidgets);
      expect(find.text('not_found'), findsOneWidget);
    });
  });

  group('History', () {
    testWidgets('an empty history offers the way to start', (tester) async {
      await pump(tester, const HistoryScreen());

      expect(find.text('No executions recorded'), findsOneWidget);
      expect(find.text('Open Command Center'), findsOneWidget);
    });

    testWidgets('shows outcome, summary and source for each execution', (tester) async {
      final records = WorkstationRecords(
        executions: [
          recordFrom('hash', id: 'EXEC-1'),
          recordFrom(
            'syntax_error',
            id: 'EXEC-2',
            outcome: ExecutionOutcome.failed,
            failureCode: 'invalid_syntax',
            failureMessage: 'Invalid command syntax at line 1, column 6.',
          ),
        ],
      );
      await pump(tester, const HistoryScreen(), records: records);

      expect(find.text('completed'), findsOneWidget);
      expect(find.text('failed'), findsOneWidget);
      expect(find.textContaining('Invalid command syntax'), findsWidgets);
    });

    testWidgets('selecting an execution opens a detail pane that never re-runs it',
        (tester) async {
      final records = WorkstationRecords(executions: [recordFrom('hash', id: 'EXEC-1')]);
      await pump(tester, const HistoryScreen(), records: records);

      await tester.tap(find.text('completed'));
      await tester.pumpAndSettle();

      expect(find.text('Execution detail'), findsOneWidget);
      expect(find.text('Load into editor'), findsOneWidget);
      expect(
        find.text('Loading places the command in the editor without executing it.'),
        findsOneWidget,
      );
      expect(transport.requests.where((r) => r.uri.path == '/command'), isEmpty);
    });

    testWidgets('a store failure is surfaced, not hidden', (tester) async {
      await pump(
        tester,
        const HistoryScreen(),
        recordFailure: const JockyFailure(
          kind: FailureKind.localStorage,
          message: 'The local record store is corrupt and was not loaded.',
        ),
      );

      expect(find.text('Local record store unavailable'), findsOneWidget);
      expect(find.textContaining('corrupt'), findsWidgets);
    });
  });

  group('Investigations', () {
    testWidgets('an empty workspace states the backend boundary', (tester) async {
      await pump(tester, const InvestigationsScreen());

      expect(find.text('No investigations recorded'), findsOneWidget);
      expect(
        find.textContaining('stored by the local backend in SQLite'),
        findsOneWidget,
      );
    });

    testWidgets('lists recorded cases with evidence and execution counts',
        (tester) async {
      final records = WorkstationRecords(
        activeCaseId: 'CASE-1',
        investigations: [
          Investigation(
            id: 'CASE-1',
            title: 'Seized laptop',
            openedAt: DateTime.utc(2026, 9, 1),
            reference: 'FIR/2026/0042',
            evidence: [
              EvidenceSource(
                id: 'EV-1',
                path: '/evidence/disk.img',
                isDirectory: false,
                addedAt: DateTime.utc(2026, 9, 1),
              ),
            ],
          ),
        ],
        executions: [recordFrom('hash', id: 'EXEC-1', caseId: 'CASE-1')],
      );
      await pump(tester, const InvestigationsScreen(), records: records);

      expect(find.text('Seized laptop'), findsOneWidget);
      expect(find.text('FIR/2026/0042'), findsOneWidget);
      expect(find.text('active'), findsOneWidget);
      expect(find.text('open'), findsOneWidget);
    });
  });

  group('System Status', () {
    testWidgets('separates backend, application and host, and admits what is unknown',
        (tester) async {
      await pump(tester, const SystemStatusScreen());

      expect(find.text('Backend readiness'), findsOneWidget);
      expect(find.text('Application status'), findsOneWidget);
      expect(find.text('Host observations'), findsOneWidget);
      // Values the backend genuinely does not publish are labelled, not faked.
      expect(find.text('not reported by backend'), findsWidgets);
      expect(find.text('No host observation collected'), findsOneWidget);
    });

    testWidgets('renders a held host observation with its collection time',
        (tester) async {
      final records = WorkstationRecords(executions: [recordFrom('system', id: 'EXEC-1')]);
      await pump(tester, const SystemStatusScreen(), records: records);

      expect(find.textContaining('These values describe that moment, not now.'),
          findsOneWidget);
      expect(find.text('HOST IDENTITY'), findsOneWidget);
    });

    testWidgets('an unreachable engine is reported with remediation', (tester) async {
      transport.fail('/health', const SocketException('Connection refused'));
      await pump(tester, const SystemStatusScreen());

      expect(find.text('Unreachable'), findsOneWidget);
      expect(find.textContaining('Start the engine from System Status'), findsWidgets);
    });
  });
}
