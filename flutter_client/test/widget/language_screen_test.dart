import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jocky_client/app/app.dart';
import 'package:jocky_client/features/language/language_examples.dart';
import 'package:jocky_client/models/settings/workstation_settings.dart';
import 'package:jocky_client/services/storage/record_store.dart';
import 'package:jocky_client/services/storage/settings_store.dart';
import 'package:jocky_client/state/providers.dart';

import '../support/fake_transport.dart';
import '../support/fixtures.dart';
import '../support/harness.dart';

/// The JOCKY .x editor.
///
/// The property these tests exist to protect is that the client never
/// interprets the language itself: the IR, the plan and every rejection come
/// from the engine, so the editor cannot tell an investigator that a program is
/// valid when a collection would refuse it.
void main() {
  late FakeTransport transport;

  setUp(() {
    transport = FakeTransport();
    transport.respondJson('/health', loadFixture('health'));
    transport.respondJson('/commands', loadFixture('commands'));
  });

  Future<void> pumpEditor(WidgetTester tester) async {
    tester.view.physicalSize = const Size(1600, 1000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          httpTransportProvider.overrideWithValue(transport),
          apiClientProvider.overrideWith((ref) => bootstrappedApi(transport)),
          settingsStoreProvider.overrideWithValue(InMemorySettingsStore()),
          recordStoreProvider.overrideWithValue(
              InMemoryRecordStore(WorkstationRecords.empty)),
          initialSettingsProvider.overrideWithValue(
            const WorkstationSettings(port: 5099, autoStartBackend: false),
          ),
          initialRecordsProvider.overrideWithValue((WorkstationRecords.empty, null)),
        ],
        child: const JockyApp(initialLocation: '/language'),
      ),
    );
    await tester.pumpAndSettle();
  }

  void respondCompiled({
    List<Map<String, dynamic>> conditionalSkips = const [],
    List<Map<String, dynamic>> unsupported = const [],
    bool platformValidated = true,
  }) {
    transport.respondJson('/api/v1/programs/compile', {
      'ir': {
        'ir_version': 2,
        'collections': [
          {'id': 'COL-001', 'source': 'PROCESSES'},
        ],
        'playbooks': ['triage'],
      },
      'plan': {
        'plan_version': 2,
        'platform': 'linux',
        'platform_validated': platformValidated,
        'ready_task_count': 1,
        'tasks': [
          {'collection_id': 'COL-001', 'source': 'PROCESSES', 'status': 'READY'},
        ],
        'unsupported': unsupported,
        'conditional_skips': conditionalSkips,
      },
      'explanation': 'JOCKY IR v2\n  collect   COL-001 PROCESSES',
      'plan_explanation': 'JOCKY execution plan v2 for linux',
    });
  }

  testWidgets('opens with an example program already loaded', (tester) async {
    await pumpEditor(tester);

    expect(find.text('JOCKY .x Investigation'), findsOneWidget);
    expect(find.text('examples/basic.x'), findsOneWidget);
    final field = tester.widget<TextField>(find.byType(TextField).first);
    expect(field.controller!.text, jockyExamples.first.source);
  });

  testWidgets('shows nothing about a program until it is compiled', (tester) async {
    await pumpEditor(tester);

    expect(find.text('Not compiled yet'), findsOneWidget);
    expect(find.textContaining('JOCKY IR v2'), findsNothing);
  });

  testWidgets('compiling sends the program to the engine and shows its IR and plan',
      (tester) async {
    respondCompiled();
    await pumpEditor(tester);

    await tester.tap(find.text('Compile'));
    await tester.pumpAndSettle();

    final sent = transport.requests
        .firstWhere((request) => request.uri.path == '/api/v1/programs/compile');
    final body = jsonDecode('${sent.body}') as Map<String, dynamic>;
    expect(body['program'], jockyExamples.first.source,
        reason: 'the editor must compile what is on screen, not a cached copy');
    expect(body['platform'], 'linux');

    expect(find.text('Compiled'), findsOneWidget);
    expect(find.text('Semantics validated'), findsOneWidget);
    expect(find.text('IR v2'), findsOneWidget);
    expect(find.text('playbook triage'), findsOneWidget);
    expect(find.textContaining('JOCKY IR v2'), findsOneWidget);
    expect(find.textContaining('JOCKY execution plan v2 for linux'), findsOneWidget);
  });

  testWidgets('a program the compiler rejects is reported in the engine\'s own words',
      (tester) async {
    transport.respondJson(
      '/api/v1/programs/compile',
      {
        'error': {
          'code': 'program_error',
          'message': "RUN names playbook 'missing', which this program does not DEFINE.",
        }
      },
      status: 400,
    );
    await pumpEditor(tester);

    await tester.tap(find.text('Compile'));
    await tester.pumpAndSettle();

    expect(find.text('Compilation failed'), findsOneWidget);
    expect(find.textContaining('does not DEFINE'), findsWidgets);
    expect(find.text('Compiled'), findsNothing,
        reason: 'a failed compile must not leave an earlier success on screen');
  });

  testWidgets('an investigation cannot be run before the program compiles',
      (tester) async {
    await pumpEditor(tester);

    final button = tester.widget<OutlinedButton>(
        find.widgetWithText(OutlinedButton, 'Run investigation'));
    expect(button.onPressed, isNull,
        reason: 'running an unchecked program is how a syntax error is found '
            'halfway through a collection');
  });

  testWidgets('a source the program guarded away is distinguished from one the '
      'platform cannot collect', (tester) async {
    respondCompiled(
      conditionalSkips: [
        {
          'collection_id': 'COL-002',
          'source': 'USB',
          'detail': 'The program guarded this collection with PLATFORM IS linux, '
              'which is not true on windows.',
        }
      ],
      unsupported: [
        {
          'collection_id': 'COL-003',
          'source': 'SERVICES',
          'detail': 'windows has no collector for SERVICES in this build.',
        }
      ],
    );
    await pumpEditor(tester);

    await tester.tap(find.text('Compile'));
    await tester.pumpAndSettle();

    expect(find.text('Skipped by the program'), findsOneWidget);
    expect(find.text('Not available on linux'), findsOneWidget);
    expect(find.textContaining('guarded this collection'), findsOneWidget);
    expect(find.textContaining('no collector for SERVICES'), findsOneWidget);
  });

  testWidgets('an unvalidated platform is stated on the plan', (tester) async {
    respondCompiled(platformValidated: false);
    await pumpEditor(tester);

    await tester.tap(find.text('Compile'));
    await tester.pumpAndSettle();

    expect(find.textContaining('NOT VALIDATED'), findsOneWidget);
  });

  testWidgets('running a compiled program starts a collection driven by the program',
      (tester) async {
    respondCompiled();
    transport.respondJson('/api/v1/investigations', {'id': 'INV-1'});
    transport.respondJson('/api/v1/investigations/INV-1/collect', {'status': 'queued'});
    await pumpEditor(tester);

    await tester.tap(find.text('Compile'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Run investigation'));
    await tester.pumpAndSettle();

    final collect = transport.requests
        .firstWhere((request) => request.uri.path == '/api/v1/investigations/INV-1/collect');
    final body = jsonDecode('${collect.body}') as Map<String, dynamic>;
    expect(body['program'], jockyExamples.first.source,
        reason: 'the collection must be driven by the program, not by a source list');
    expect(body.containsKey('sources'), isFalse);
    expect(find.text('Investigation started'), findsOneWidget);
  });

  testWidgets('every shipped example can be loaded into the editor', (tester) async {
    await pumpEditor(tester);

    for (final example in jockyExamples.skip(1)) {
      await tester.tap(find.text('Examples'));
      await tester.pumpAndSettle();
      await tester.tap(find.textContaining('${example.name}.x').last);
      await tester.pumpAndSettle();

      expect(find.text('examples/${example.name}.x'), findsOneWidget);
      final field = tester.widget<TextField>(find.byType(TextField).first);
      expect(field.controller!.text, example.source);
    }
  });
}
