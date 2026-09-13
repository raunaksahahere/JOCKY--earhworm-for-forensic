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
    transport.respondJson('$base/execution-events', {'items': telemetryAvailable
        ? [{'id': 'e1', 'source': 'systemd journal'}, {'id': 'e2', 'source': 'bash history'}]
        : []});
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
    expect(find.textContaining('2 (1 carry no timestamp)'), findsOneWidget);
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
    script(telemetryAvailable: true);

    await pump(tester);

    // Section headers carry the counts the engine actually returned. They sit
    // below the fold in a lazy list, so each one is scrolled into view.
    for (final label in [
      'Historical execution — HISTORICAL EVIDENCE (2)',
      'Event timeline — ordered by recorded time (1)',
      'Artifacts — observed files (1)',
      'Findings — INFERRED; requires review (1)',
      'Collection limitations (1)',
      'Unavailable telemetry (1)',
    ]) {
      await tester.scrollUntilVisible(find.textContaining(label), 200,
          scrollable: find.byType(Scrollable).first);
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
}
