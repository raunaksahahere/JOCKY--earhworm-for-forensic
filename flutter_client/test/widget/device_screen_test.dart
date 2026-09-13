import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jocky_client/features/device/device_screen.dart';

import '../support/fake_transport.dart';
import '../support/harness.dart';

/// The investigation workspace must report exactly what the engine recorded:
/// how much historical evidence there is, and what could not be collected.
void main() {
  late FakeTransport transport;

  const caseId = 'case-1';
  const base = '/api/v1/investigations/$caseId';

  // Two records that must never be confused: a typed command, and a process a
  // source recorded actually running.
  final activityRows = [
    {
      'id': 'e1', 'reference': 'CMD-0001', 'source': 'bash history',
      'evidence_kind': 'COMMAND_HISTORY', 'execution_confirmed': false,
      'timestamp': '2026-09-11T14:32:10+00:00', 'triage': 'POTENTIALLY_HARMFUL',
      'full_command_line': 'curl -fsSL https://example.com/install.sh | sudo bash',
      'normalized_command': 'curl -fsSL URL | sudo bash',
      'command_reconstruction_status': 'EXACT', 'command_evidence_strength': 'STRONG',
      'executable': null, 'process_name': 'curl', 'payload': {'raw': 'preserved'},
    },
    {
      'id': 'e2', 'reference': 'EXEC-0001', 'source': 'systemd journal',
      'evidence_kind': 'EXECUTION_EVIDENCE', 'execution_confirmed': true,
      'timestamp': '2026-09-11T09:00:00+00:00', 'triage': 'NEEDS_REVIEW',
      'full_command_line': null, 'normalized_command': 'python3',
      'command_reconstruction_status': 'EXECUTABLE_ONLY', 'command_evidence_strength': 'WEAK',
      'executable': '/usr/bin/python3', 'process_name': 'python3', 'payload': {'raw': 'preserved'},
    },
    {
      'id': 'e3', 'reference': 'CMD-0002', 'source': 'bash history',
      'evidence_kind': 'COMMAND_HISTORY', 'execution_confirmed': false,
      'timestamp': '2026-09-11T08:00:00+00:00', 'triage': 'NOT_HARMFUL_ON_AVAILABLE_EVIDENCE',
      'full_command_line': 'git clone https://github.com/example/project.git',
      'normalized_command': 'git clone URL',
      'command_reconstruction_status': 'EXACT', 'command_evidence_strength': 'STRONG',
      'executable': null, 'process_name': 'git', 'payload': {'raw': 'preserved'},
    },
  ];


  Map<String, dynamic> report({required bool telemetryAvailable}) => {
        'schema_version': 3,
        'collection_window': {
          'start': '2026-09-06T12:00:00+00:00',
          'end': '2026-09-13T12:00:00+00:00',
          'requested_hours': 168,
          'bounded': true,
        },
        'historical_execution': {
          'telemetry_available': telemetryAvailable,
          'platform': 'Linux',
          'event_count': telemetryAvailable ? 2 : 0,
          'undated_event_count': telemetryAvailable ? 1 : 0,
        },
        'current_process_snapshot': {
          'statistics': {'processes_recorded': 385, 'processes_present': 385},
        },
        'limitations': ['A hash compares bytes; it does not prove authenticity.'],
        'unavailable_telemetry': telemetryAvailable
            ? [{'source': 'kernel audit log', 'status': 'NOT_AVAILABLE', 'detail': 'absent'}]
            : [
                {'source': 'systemd journal', 'status': 'NOT_ENABLED', 'detail': 'off'},
                {'source': 'kernel audit log', 'status': 'NOT_AVAILABLE', 'detail': 'absent'},
              ],
      };

  void script({required bool telemetryAvailable}) {
    transport.respondJson('/health', {'engine': 'online', 'status': 'ready', 'instance_id': testInstanceId});
    transport.respondJson(base, {'id': caseId, 'title': 'Device analysis', 'status': 'completed', 'device': {}});
    transport.respondJson('$base/evidence', {'items': []});
    transport.respondJson('$base/findings', {'items': [
      {'id': 'f1', 'title': 'Execution evidence names a missing executable', 'severity': 'medium'},
    ]});
    transport.respondJson('$base/timeline', {'items': []});
    transport.respondJson('$base/reports', {'items': [
      {'id': 'r1', 'payload': report(telemetryAvailable: telemetryAvailable)},
    ]});
    transport.respondJson('$base/execution-events', {'items': telemetryAvailable ? activityRows : []});
    transport.respondJson('$base/artifacts', {'items': [{'id': 'a1', 'path': '/usr/bin/curl'}]});
    transport.respondJson('$base/event-timeline', {'items': [{'id': 1, 'kind': 'EXECUTION_EVENT'}]});
  }

  setUp(() => transport = FakeTransport());

  Future<void> pump(WidgetTester tester) async {
    await tester.pumpWidget(harness(const DeviceScreen(caseId: caseId), transport: transport));
    await tester.pumpAndSettle();
  }

  testWidgets('the summary reports available telemetry and the collection window', (tester) async {
    script(telemetryAvailable: true);

    await pump(tester);

    expect(find.text('Collection summary'), findsOneWidget);
    expect(find.text('AVAILABLE'), findsOneWidget);
    expect(find.textContaining('2026-09-06T12:00:00+00:00'), findsOneWidget);
    expect(find.textContaining('Execution-source records:'), findsOneWidget);
    expect(find.textContaining('execution not established by these'), findsOneWidget);
    expect(find.textContaining('385 of 385 present'), findsOneWidget);
  });

  testWidgets('absent telemetry is stated plainly, not left blank', (tester) async {
    script(telemetryAvailable: false);

    await pump(tester);

    expect(find.text('NOT AVAILABLE'), findsOneWidget);
    expect(
      find.textContaining('cannot establish what ran before it'),
      findsOneWidget,
      reason: 'the UI must not let a reader mistake no evidence for no activity',
    );
  });

  testWidgets('counts come from the engine, never from the client', (tester) async {
    // A tall viewport so the whole lazy list is built; these assertions are
    // about what the engine's numbers render as.
    tester.view.physicalSize = const Size(1400, 4000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    script(telemetryAvailable: true);

    await pump(tester);

    for (final label in [
      'Historical execution — HISTORICAL EVIDENCE (3)',
      'Event timeline — ordered by recorded time (1)',
      'Artifacts — observed files (1)',
      'Findings — INFERRED; requires review (1)',
      'Collection limitations (1)',
      'Unavailable telemetry (1)',
    ]) {
      expect(find.textContaining(label), findsOneWidget, reason: label);
    }
  });

  testWidgets('no report yet means no summary numbers are invented', (tester) async {
    script(telemetryAvailable: true);
    transport.respondJson('$base/reports', {'items': []});

    await pump(tester);

    expect(find.textContaining('No report has been issued yet'), findsOneWidget);
    expect(find.text('AVAILABLE'), findsNothing);
  });

  group('investigator activity view', () {
    Future<void> pumpActivity(WidgetTester tester) async {
      // Tall enough that the whole activity panel is built: the list is lazy,
      // and these assertions are about what it renders.
      tester.view.physicalSize = const Size(1400, 3200);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      script(telemetryAvailable: true);
      await tester.pumpWidget(harness(const DeviceScreen(caseId: caseId), transport: transport));
      await tester.pumpAndSettle();
    }

    testWidgets('shows the full command, never only the executable', (tester) async {
      await pumpActivity(tester);

      expect(find.text('curl -fsSL https://example.com/install.sh | sudo bash'), findsOneWidget);
      expect(find.text('git clone https://github.com/example/project.git'), findsOneWidget);
      expect(find.text('curl'), findsNothing, reason: 'the executable alone is not the evidence');
    });

    testWidgets('a missing command line is stated, not invented', (tester) async {
      await pumpActivity(tester);

      expect(find.text('/usr/bin/python3'), findsOneWidget);
      expect(
        find.textContaining('Full command line: not available from collected evidence (EXECUTABLE_ONLY)'),
        findsOneWidget,
      );
      expect(find.textContaining('unknown arguments'), findsNothing);
    });

    testWidgets('command history is never shown as confirmed execution', (tester) async {
      await pumpActivity(tester);

      expect(find.textContaining('COMMAND HISTORY  |  execution NOT established'), findsNWidgets(2));
      expect(find.textContaining('EXECUTION EVIDENCE  |  execution confirmed by the source'),
          findsOneWidget);
    });

    testWidgets('the most concerning record is listed first', (tester) async {
      await pumpActivity(tester);

      // Exact labels only: the summary block above uses the same words with a
      // trailing colon, and those are counts rather than records.
      const rowLabels = {
        'POTENTIALLY HARMFUL', 'NOT SURE / NEEDS REVIEW', 'NOT HARMFUL ON AVAILABLE EVIDENCE'};
      final labels = tester.widgetList<Text>(find.byType(Text))
          .map((widget) => widget.data)
          .whereType<String>()
          .where(rowLabels.contains)
          .toList();
      expect(labels.first, 'POTENTIALLY HARMFUL');
      expect(labels.last, 'NOT HARMFUL ON AVAILABLE EVIDENCE');
    });

    testWidgets('search matches the full command text, not the executable alone', (tester) async {
      await pumpActivity(tester);

      await tester.enterText(find.byType(TextField).first, 'github.com');
      await tester.pumpAndSettle();

      expect(find.text('git clone https://github.com/example/project.git'), findsOneWidget);
      expect(find.text('curl -fsSL https://example.com/install.sh | sudo bash'), findsNothing);
      expect(find.textContaining('1 of 3 records'), findsOneWidget);
    });

    testWidgets('search finds an evidence identifier', (tester) async {
      await pumpActivity(tester);

      await tester.enterText(find.byType(TextField).first, 'EXEC-0001');
      await tester.pumpAndSettle();

      expect(find.text('/usr/bin/python3'), findsOneWidget);
      expect(find.textContaining('1 of 3 records'), findsOneWidget);
    });

    testWidgets('raw evidence is available behind details, not removed', (tester) async {
      await pumpActivity(tester);

      await tester.enterText(find.byType(TextField).first, 'EXEC-0001');
      await tester.pumpAndSettle();
      await tester.tap(find.text('Details'));
      await tester.pumpAndSettle();

      // SelectableText renders both a Text and an EditableText for the same string.
      expect(find.textContaining('preserved'), findsWidgets);
    });
  });
}
