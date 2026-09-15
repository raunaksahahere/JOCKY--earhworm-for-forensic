import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jocky_client/features/device/artifact_exports.dart';

import '../support/fake_transport.dart';
import '../support/fixtures.dart';
import '../support/harness.dart';

/// What the investigator is offered after a collection finishes.
///
/// The thing under test is that the default result is an eight-page report, not
/// a seventy-page one, and that the page counts shown are the engine's rather
/// than the client's guesses.
void main() {
  late FakeTransport transport;
  const caseId = 'case-9';
  const base = '/api/v1/investigations/$caseId';

  Map<String, dynamic> available({int investigatorPages = 8, int routinePages = 4}) => {
        'investigator_report': {
          'name': 'JOCKY_Investigator_Report_$caseId.pdf',
          'pages': investigatorPages,
          'bytes': 34311,
          'description': 'The investigator-facing narrative. No raw evidence.',
        },
        'routine_activity': {
          'name': 'jocky-routine-$caseId.pdf',
          'pages': routinePages,
          'bytes': 21358,
          'groups': 9,
          'records': 1278,
          'description': "Activity the machine's own records account for, grouped. Optional, "
              'and never the primary report.',
        },
        'evidence_package': {
          'name': 'JOCKY_Evidence_Package_$caseId.zip',
          'records': 1947,
          'record_counts': const {'artifacts': 71},
          'description': 'Everything collected, with a manifest and a digest for every file. '
              'Nothing was removed from it to shorten the report.',
        },
        'review_briefs': {
          'generated': 2,
          'description': 'One or two pages about a single artifact, finding, activity, lead '
              'or thread. Generated on request.',
        },
        'note': 'Three documents, each answering a different question: what do I need to know, '
            'tell me about this one thing, show me everything.',
      };

  setUp(() {
    transport = FakeTransport();
    transport.respondJson('/health', loadFixture('health'));
    transport.respondJson('$base/artifacts-available', available());
  });

  Future<void> pump(WidgetTester tester) async {
    tester.view.physicalSize = const Size(1400, 1400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(harness(const ArtifactExports(caseId: caseId), transport: transport));
    await tester.pumpAndSettle();
  }

  testWidgets('the four artifacts are offered', (tester) async {
    await pump(tester);
    expect(find.text('Investigator report'), findsOneWidget);
    expect(find.text('Review brief'), findsOneWidget);
    expect(find.text('Evidence package'), findsOneWidget);
    expect(find.text('Routine activity report'), findsOneWidget);
  });

  testWidgets('each one is introduced by the question it answers', (tester) async {
    await pump(tester);
    expect(find.text('WHAT DO I NEED TO KNOW?'), findsOneWidget);
    expect(find.text('TELL ME ABOUT THIS ONE THING.'), findsOneWidget);
    expect(find.text('SHOW ME EVERYTHING.'), findsOneWidget);
  });

  testWidgets('page counts come from the engine, before anything is generated', (tester) async {
    await pump(tester);
    expect(find.textContaining('8 pages'), findsOneWidget);
    expect(find.textContaining('4 pages'), findsOneWidget);
    expect(find.textContaining('1947 records'), findsOneWidget);
  });

  testWidgets('the default result is never presented as a long report', (tester) async {
    await pump(tester);
    // The long document exists and is offered last, described as what it is.
    expect(find.textContaining('grows with the evidence collected'), findsOneWidget);
    expect(find.textContaining('Rarely wanted'.toUpperCase()), findsOneWidget);
  });

  testWidgets('the package states that nothing was removed to shorten the report',
      (tester) async {
    await pump(tester);
    expect(find.textContaining('Nothing was removed from it to shorten the report'),
        findsOneWidget);
  });

  testWidgets('the routine report is marked optional and never primary', (tester) async {
    await pump(tester);
    expect(find.text('OPTIONAL'), findsOneWidget);
    expect(find.textContaining('never the primary report'), findsOneWidget);
  });

  testWidgets('the routine report is never described as safe', (tester) async {
    await pump(tester);
    final routine = tester
        .widgetList<Text>(find.byType(Text))
        .map((widget) => widget.data ?? '')
        .join(' ')
        .toLowerCase();
    expect(routine.contains('safe activity'), isFalse);
    expect(routine.contains('routine'), isTrue);
  });

  testWidgets('a review brief is not offered as a bulk export', (tester) async {
    await pump(tester);
    expect(find.textContaining('2 generated so far'), findsOneWidget);
    expect(find.textContaining('Open any record, finding or thread'), findsOneWidget);
  });

  testWidgets('generating the investigator report asks the engine for it', (tester) async {
    final selection = FakeFileSelection(saveLocation: '/tmp/report.pdf');
    tester.view.physicalSize = const Size(1400, 1400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    transport.respondRaw('$base/report/export', '%PDF-1.4 fake');
    await tester.pumpWidget(harness(const ArtifactExports(caseId: caseId),
        transport: transport, fileSelection: selection));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('artifact-investigator-report')));
    await tester.pumpAndSettle();

    final exported = transport.requests
        .where((request) => request.uri.path.endsWith('/report/export'))
        .toList();
    expect(exported, isNotEmpty);
    expect('${exported.last.body}', contains('pdf'));
    expect('${exported.last.body}', isNot(contains('detailed')),
        reason: 'the default export must be the short report');
  });

  testWidgets('the full report is an explicit request', (tester) async {
    final selection = FakeFileSelection(saveLocation: '/tmp/full.pdf');
    tester.view.physicalSize = const Size(1400, 1400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    transport.respondRaw('$base/report/export', '%PDF-1.4 fake');
    await tester.pumpWidget(harness(const ArtifactExports(caseId: caseId),
        transport: transport, fileSelection: selection));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('artifact-full-report')));
    await tester.pumpAndSettle();

    final exported = transport.requests
        .where((request) => request.uri.path.endsWith('/report/export'))
        .toList();
    expect('${exported.last.body}', contains('detailed'));
  });

  testWidgets('a failure is reported rather than leaving an empty panel', (tester) async {
    transport.respondJson('$base/artifacts-available',
        {'error': {'message': 'engine starting'}}, status: 503);
    await pump(tester);
    expect(find.text('Try again'), findsOneWidget);
  });
}
