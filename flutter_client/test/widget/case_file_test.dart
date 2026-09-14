import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jocky_client/features/casefile/case_file_screen.dart';

import '../support/fake_transport.dart';
import '../support/fixtures.dart';
import '../support/harness.dart';

Map<String, dynamic> _case({
  String id = 'CASE-0001',
  String title = 'Suspected data staging',
  String status = 'open',
}) =>
    {
      'id': id,
      'title': title,
      'status': status,
      'created_at': '2026-03-14T09:00:00+00:00',
      'examiner': 'R. Saha',
      'reference': 'SIH-2026/1',
      'investigation_count': 2,
      'evidence_source_count': 1,
    };

Map<String, dynamic> _evidence({
  String id = 'EV-0001',
  String verification = 'VERIFIED',
  String? supersedes,
}) =>
    {
      'id': id,
      'reference': id,
      'source_type': 'file',
      'acquisition_status': 'HASHED',
      'verification_state': verification,
      'registered_at': '2026-03-14T09:05:00+00:00',
      'original_path': '/evidence/disk.raw',
      'sha256': 'a' * 64,
      'size_bytes': 4096,
      'supersedes': supersedes,
      'integrity_events': const [],
    };

Map<String, dynamic> _endpoint({
  String id = 'EP-0001',
  String name = 'lab-1',
  String health = 'healthy',
  String status = 'enrolled',
}) =>
    {
      'id': id,
      'name': name,
      'status': status,
      'enrolled_at': '2026-03-14T09:00:00+00:00',
      'platform': 'Linux',
      'capabilities': const ['NETWORK', 'USB', 'DRIVERS'],
      'authorization_reference': 'WARRANT-2026/11',
      'health': {'state': health, 'detail': 'seen recently'},
      'tasks': const {'succeeded': 3},
    };

void main() {
  late FakeTransport transport;

  setUp(() {
    transport = FakeTransport();
    transport.respondJson('/health', loadFixture('health'));
    transport.respondJson('/commands', loadFixture('commands'));
    transport.respondJson('/api/v1/cases', {'items': [_case()]});
    transport.respondJson('/api/v1/evidence-sources', {'items': [_evidence()]});
    transport.respondJson('/api/v1/endpoints', {'items': [_endpoint()], 'stale_after_seconds': 300});
    transport.respondJson('/api/v1/audit', {
      'items': [
        {
          'timestamp': '2026-03-14T09:05:00+00:00',
          'actor': 'examiner@workstation',
          'action': 'evidence.registered',
          'outcome': 'success',
          'object_type': 'evidence_source',
          'object_id': 'EV-0001',
        }
      ],
      'note': 'The audit trail records what JOCKY and the investigator did. It is not '
          'evidence about the examined host.',
    });
  });

  Future<void> pump(WidgetTester tester, {int tab = 0}) async {
    tester.view.physicalSize = const Size(1500, 1000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(harness(CaseFileScreen(initialTab: tab), transport: transport));
    await tester.pumpAndSettle();
  }

  testWidgets('the case list shows what a case holds', (tester) async {
    await pump(tester);
    expect(find.text('Suspected data staging'), findsOneWidget);
    expect(find.text('CASE-0001'), findsOneWidget);
    expect(find.text('R. Saha'), findsOneWidget);
  });

  testWidgets('an empty case list explains what a case is for', (tester) async {
    transport.respondJson('/api/v1/cases', {'items': const []});
    await pump(tester);
    expect(find.text('No cases yet'), findsOneWidget);
  });

  testWidgets('evidence integrity state is shown per source', (tester) async {
    await pump(tester, tab: 1);
    expect(find.text('VERIFIED'), findsOneWidget);
    expect(find.text('/evidence/disk.raw'), findsOneWidget);
  });

  testWidgets('a digest that no longer matches is shown as a mismatch', (tester) async {
    transport.respondJson('/api/v1/evidence-sources', {
      'items': [_evidence(verification: 'MISMATCH', supersedes: 'EV-0000')]
    });
    await pump(tester, tab: 1);
    expect(find.text('MISMATCH'), findsOneWidget);
    expect(find.text('EV-0000'), findsOneWidget);
  });

  testWidgets('the evidence panel states that a source is never overwritten', (tester) async {
    await pump(tester, tab: 1);
    expect(
      find.textContaining('records a further acquisition rather than replacing the first'),
      findsOneWidget,
    );
  });

  testWidgets('endpoints show their authority and contact state', (tester) async {
    await pump(tester, tab: 2);
    expect(find.text('lab-1'), findsOneWidget);
    expect(find.text('healthy'), findsOneWidget);
    expect(find.text('WARRANT-2026/11'), findsOneWidget);
  });

  testWidgets('the endpoints panel states that no remote command is sent', (tester) async {
    await pump(tester, tab: 2);
    expect(find.textContaining('There is no remote command'), findsOneWidget);
  });

  testWidgets('a silent endpoint reads as stale, not absent', (tester) async {
    transport.respondJson('/api/v1/endpoints', {
      'items': [_endpoint(health: 'stale')],
      'stale_after_seconds': 300,
    });
    await pump(tester, tab: 2);
    expect(find.text('stale'), findsOneWidget);
  });

  testWidgets('a revoked endpoint offers no revoke action', (tester) async {
    transport.respondJson('/api/v1/endpoints', {
      'items': [_endpoint(status: 'revoked', health: 'revoked')],
      'stale_after_seconds': 300,
    });
    await pump(tester, tab: 2);
    expect(find.widgetWithText(TextButton, 'Revoke'), findsNothing);
  });

  testWidgets('the audit trail says it is not evidence about the host', (tester) async {
    await pump(tester, tab: 3);
    expect(find.text('evidence.registered'), findsOneWidget);
    expect(
      find.textContaining('not evidence about the examined host'),
      findsOneWidget,
    );
  });

  testWidgets('authorizing an endpoint requires a stated authority', (tester) async {
    await pump(tester, tab: 2);
    await tester.tap(find.byKey(const Key('authorize-endpoint')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('endpoint-authority')), findsOneWidget);
    expect(find.textContaining('The warrant, ticket or written consent'), findsOneWidget);
  });

  testWidgets('a failed listing offers a retry rather than an empty table', (tester) async {
    transport.respondJson('/api/v1/cases', {'error': {'message': 'engine starting'}}, status: 503);
    await pump(tester);
    expect(find.text('Retry'), findsOneWidget);
  });
}
