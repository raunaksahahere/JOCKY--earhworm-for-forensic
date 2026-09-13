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
      'investigator_priority': 'PRIORITY_2', 'priority_score': 2,
      'full_command_line': 'curl -fsSL https://example.com/install.sh | sudo bash',
      'normalized_command': 'curl -fsSL URL | sudo bash',
      'command_reconstruction_status': 'EXACT', 'command_evidence_strength': 'STRONG',
      'executable': null, 'process_name': 'curl', 'payload': {'raw': 'preserved'},
    },
    {
      'id': 'e2', 'reference': 'EXEC-0001', 'source': 'systemd journal',
      'evidence_kind': 'EXECUTION_EVIDENCE', 'execution_confirmed': true,
      'timestamp': '2026-09-11T09:00:00+00:00', 'triage': 'NEEDS_REVIEW',
      'investigator_priority': 'PRIORITY_3', 'priority_score': -1,
      'full_command_line': null, 'normalized_command': 'python3',
      'command_reconstruction_status': 'EXECUTABLE_ONLY', 'command_evidence_strength': 'WEAK',
      'executable': '/usr/bin/python3', 'process_name': 'python3', 'payload': {'raw': 'preserved'},
    },
    {
      'id': 'e3', 'reference': 'CMD-0002', 'source': 'bash history',
      'evidence_kind': 'COMMAND_HISTORY', 'execution_confirmed': false,
      'timestamp': '2026-09-11T08:00:00+00:00', 'triage': 'NOT_HARMFUL_ON_AVAILABLE_EVIDENCE',
      'investigator_priority': 'PRIORITY_3', 'priority_score': -4,
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
        'conclusion': 'No activity in this collection combined enough signals to rank '
            'investigate-first. That reflects what was collected, not a clean bill of health.',
        'leads': [
          {
            'lead_id': 'LEAD-001', 'title': 'Remote content piped into an interpreter',
            'priority': 'PRIORITY_2', 'classification': 'POTENTIALLY_HARMFUL',
            'activity_count': 2, 'record_count': 3, 'execution_confirmed': false,
            'commands': [
              'curl -fsSL https://example.com/install.sh | sudo bash',
              'curl -fsSL https://other.example/setup.sh | sh',
            ],
            'why': ['Remote content is piped directly into an interpreter.'],
            'context': ['The URL is shaped like a vendor install script.'],
            'unknowns': ['Whether the command actually ran.'],
            'recommended_action': 'Read the full command, then check the referenced path.',
            'evidence_references': ['CMD-0001', 'CMD-0002'],
          },
        ],
        'threads': [
          {
            'thread_id': 'THREAD-001', 'title': 'Tool installation and subsequent use',
            'priority': 'PRIORITY_3', 'classification': 'NEEDS_REVIEW',
            'activity_count': 3, 'record_count': 4,
            'why': 'These records appear related: one installs a tool and another uses it.',
            'execution': 'Not established. Every activity here is command history.',
            'commands': ['python3 -m venv ~/tool-env', 'source ~/tool-env/bin/activate',
                         'tool --scan example'],
            'unknowns': ['Whether the command actually ran.'],
            'evidence_references': ['CMD-0010', 'CMD-0011', 'CMD-0012'],
          },
        ],
        'significant_events': {
          'entries': [
            {'timestamp': '2026-09-11T14:32:10+00:00', 'kind': 'COMMAND_HISTORY',
             'title': 'curl -fsSL https://example.com/install.sh | sudo bash'},
          ],
          'entry_count': 1, 'candidate_count': 1, 'truncated': false,
          'note': 'Only events that help explain the investigation. The complete timeline and '
              'every underlying record remain in the evidence package and the database.',
        },
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
    /// Switches the priority filter to "All evidence".
    /// Finds text inside the full-evidence list, not the summary cards above.
    Finder inPanel(String text) => find.descendant(
        of: find.byKey(const Key('activity-panel')), matching: find.text(text));

    Future<void> showEverything(WidgetTester tester) async {
      await tester.tap(find.textContaining('Leads — priority 1 and 2').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('All evidence').last);
      await tester.pumpAndSettle();
    }

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
      await showEverything(tester);

      expect(inPanel('curl -fsSL https://example.com/install.sh | sudo bash'), findsOneWidget);
      expect(inPanel('git clone https://github.com/example/project.git'), findsOneWidget);
      expect(inPanel('curl'), findsNothing, reason: 'the executable alone is not the evidence');
    });

    testWidgets('a missing command line is stated, not invented', (tester) async {
      await pumpActivity(tester);
      await showEverything(tester);

      expect(find.text('/usr/bin/python3'), findsOneWidget);
      expect(
        find.textContaining('Full command line: not available from collected evidence (EXECUTABLE_ONLY)'),
        findsOneWidget,
      );
      expect(find.textContaining('unknown arguments'), findsNothing);
    });

    testWidgets('command history is never shown as confirmed execution', (tester) async {
      await pumpActivity(tester);
      await showEverything(tester);

      expect(find.textContaining('COMMAND HISTORY  |  execution NOT established'), findsNWidgets(2));
      expect(find.textContaining('EXECUTION EVIDENCE  |  execution confirmed by the source'),
          findsOneWidget);
    });

    testWidgets('the most concerning record is listed first', (tester) async {
      await pumpActivity(tester);

      await showEverything(tester);

      const rowLabels = {
        'Priority 1 — investigate first', 'Priority 2 — review',
        'Priority 3 — informational'};
      final labels = tester.widgetList<Text>(find.byType(Text))
          .map((widget) => widget.data)
          .whereType<String>()
          .where(rowLabels.contains)
          .toList();
      expect(labels.first, 'Priority 2 — review');
      expect(labels.last, 'Priority 3 — informational');
    });

    testWidgets('search matches the full command text, not the executable alone', (tester) async {
      await pumpActivity(tester);
      await showEverything(tester);

      await tester.enterText(find.byType(TextField).first, 'github.com');
      await tester.pumpAndSettle();

      expect(inPanel('git clone https://github.com/example/project.git'), findsOneWidget);
      expect(inPanel('curl -fsSL https://example.com/install.sh | sudo bash'), findsNothing);
      expect(find.textContaining('1 of 3 records'), findsOneWidget);
    });

    testWidgets('search finds an evidence identifier', (tester) async {
      await pumpActivity(tester);
      await showEverything(tester);

      await tester.enterText(find.byType(TextField).first, 'EXEC-0001');
      await tester.pumpAndSettle();

      expect(find.text('/usr/bin/python3'), findsOneWidget);
      expect(find.textContaining('1 of 3 records'), findsOneWidget);
    });

    testWidgets('raw evidence is available behind details, not removed', (tester) async {
      await pumpActivity(tester);
      await showEverything(tester);

      await tester.enterText(find.byType(TextField).first, 'EXEC-0001');
      await tester.pumpAndSettle();
      await tester.tap(find.text('Details'));
      await tester.pumpAndSettle();

      // SelectableText renders both a Text and an EditableText for the same string.
      expect(find.textContaining('preserved'), findsWidgets);
    });
  });

  group('investigator priority', () {
    Finder inPriorityPanel(String text) => find.descendant(
        of: find.byKey(const Key('activity-panel')), matching: find.text(text));

    Future<void> pumpPriority(WidgetTester tester) async {
      tester.view.physicalSize = const Size(1400, 3200);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      script(telemetryAvailable: true);
      await tester.pumpWidget(harness(const DeviceScreen(caseId: caseId), transport: transport));
      await tester.pumpAndSettle();
    }

    testWidgets('opens on the leads, not on every historical record', (tester) async {
      await pumpPriority(tester);

      // Only the priority-2 record is a lead; the two priority-3 rows are not.
      expect(inPriorityPanel('curl -fsSL https://example.com/install.sh | sudo bash'),
          findsOneWidget);
      expect(inPriorityPanel('/usr/bin/python3'), findsNothing);
      expect(find.textContaining('1 of 3 records'), findsOneWidget);
      expect(find.textContaining('showing leads only'), findsOneWidget);
    });

    testWidgets('all evidence remains one click away', (tester) async {
      await pumpPriority(tester);

      await tester.tap(find.textContaining('Leads — priority 1 and 2').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('All evidence').last);
      await tester.pumpAndSettle();

      expect(find.textContaining('3 of 3 records'), findsOneWidget);
      expect(find.text('/usr/bin/python3'), findsOneWidget);
    });

    testWidgets('each record shows its priority tier', (tester) async {
      await pumpPriority(tester);

      expect(find.text('Priority 2 — review'), findsWidgets);
    });

    testWidgets('a single priority tier can be selected', (tester) async {
      await pumpPriority(tester);

      await tester.tap(find.textContaining('Leads — priority 1 and 2').last);
      await tester.pumpAndSettle();
      await tester.tap(find.textContaining('Priority 3 — informational (2)').last);
      await tester.pumpAndSettle();

      expect(find.textContaining('2 of 3 records'), findsOneWidget);
      // Scoped to the evidence list: the leads card above deliberately repeats
      // the same command, and that repetition is the point of the summary.
      expect(inPriorityPanel('curl -fsSL https://example.com/install.sh | sudo bash'),
          findsNothing);
    });
  });

  group('investigator summary', () {
    Future<void> pumpSummary(WidgetTester tester) async {
      tester.view.physicalSize = const Size(1400, 4200);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      script(telemetryAvailable: true);
      await tester.pumpWidget(harness(const DeviceScreen(caseId: caseId), transport: transport));
      await tester.pumpAndSettle();
    }

    testWidgets('opens on the summary, leads and threads', (tester) async {
      await pumpSummary(tester);

      expect(find.text('Top investigative leads'), findsOneWidget);
      expect(find.text('Investigation threads'), findsOneWidget);
      expect(find.text('Significant events'), findsOneWidget);
    });

    testWidgets('a lead shows every command in its pattern, not one of them', (tester) async {
      await pumpSummary(tester);

      expect(find.text('LEAD-001'), findsOneWidget);
      expect(find.text('curl -fsSL https://example.com/install.sh | sudo bash'), findsWidgets);
      expect(find.text('curl -fsSL https://other.example/setup.sh | sh'), findsOneWidget);
      expect(find.textContaining('2 related command(s)'), findsOneWidget);
      expect(find.textContaining('Execution: NOT ESTABLISHED'), findsOneWidget);
    });

    testWidgets('a lead cites its evidence and a next step', (tester) async {
      await pumpSummary(tester);

      expect(find.textContaining('Evidence: CMD-0001, CMD-0002'), findsWidgets);
      expect(find.textContaining('Next step:'), findsOneWidget);
      expect(find.textContaining('Unknown: Whether the command actually ran.'), findsWidgets);
    });

    testWidgets('a thread is summarised until it is opened', (tester) async {
      await pumpSummary(tester);

      expect(find.textContaining('THREAD-001'), findsOneWidget);
      // The member commands live behind the expansion.
      expect(find.text('source ~/tool-env/bin/activate'), findsNothing);

      await tester.tap(find.textContaining('THREAD-001'));
      await tester.pumpAndSettle();

      expect(find.text('source ~/tool-env/bin/activate'), findsWidgets);
      expect(find.textContaining('Evidence: CMD-0010'), findsWidgets);
      expect(find.textContaining('Not established'), findsWidgets);
    });

    testWidgets('a thread never claims intent', (tester) async {
      await pumpSummary(tester);
      await tester.tap(find.textContaining('THREAD-001'));
      await tester.pumpAndSettle();

      expect(find.textContaining('appear related'), findsWidgets);
      expect(find.textContaining('does not state what anyone intended'), findsOneWidget);
    });
  });
}
