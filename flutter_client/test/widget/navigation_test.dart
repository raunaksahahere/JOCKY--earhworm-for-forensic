import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jocky_client/app/app.dart';
import 'package:jocky_client/app/navigation.dart';
import 'package:jocky_client/models/settings/workstation_settings.dart';
import 'package:jocky_client/services/storage/record_store.dart';
import 'package:jocky_client/services/storage/settings_store.dart';
import 'package:jocky_client/state/providers.dart';

import '../support/fake_transport.dart';
import '../support/fixtures.dart';

void main() {
  late FakeTransport transport;

  setUp(() {
    transport = FakeTransport();
    transport.respondJson('/health', loadFixture('health'));
    transport.respondJson('/commands', loadFixture('commands'));
  });

  Future<void> pumpApp(
    WidgetTester tester, {
    Size size = const Size(1500, 950),
    WorkstationRecords records = WorkstationRecords.empty,
    String initialLocation = '/',
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          httpTransportProvider.overrideWithValue(transport),
          settingsStoreProvider.overrideWithValue(InMemorySettingsStore()),
          recordStoreProvider.overrideWithValue(InMemoryRecordStore(records)),
          initialSettingsProvider.overrideWithValue(
            // Auto-start is off so the test never tries to spawn a real engine.
            const WorkstationSettings(port: 5099, autoStartBackend: false),
          ),
          initialRecordsProvider.overrideWithValue((records, null)),
        ],
        child: JockyApp(initialLocation: initialLocation),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('the shell shows every primary destination', (tester) async {
    await pumpApp(tester);

    for (final destination in JockyDestination.values) {
      expect(find.text(destination.label), findsWidgets,
          reason: '${destination.label} must be reachable from the sidebar');
    }
  });

  testWidgets('opens on Overview with the engine adopted from the health probe',
      (tester) async {
    await pumpApp(tester);

    expect(find.text('Operations dashboard'), findsNothing);
    expect(find.text('Engine, case and recent activity'), findsOneWidget);
    expect(find.text('Engine ready'), findsWidgets);
  });

  testWidgets('clicking a destination routes to it', (tester) async {
    await pumpApp(tester);

    await tester.tap(find.text('Reports').first);
    await tester.pumpAndSettle();
    expect(find.text('Engine-issued report archive'), findsOneWidget);

    await tester.tap(find.text('History').first);
    await tester.pumpAndSettle();
    expect(find.text('Execution history'), findsOneWidget);

    await tester.tap(find.text('System Status').first);
    await tester.pumpAndSettle();
    expect(find.text('Backend readiness'), findsOneWidget);
  });

  testWidgets('Ctrl+2 jumps to the Command Center', (tester) async {
    await pumpApp(tester);

    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.digit2);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await tester.pumpAndSettle();

    expect(find.text('No command submitted yet'), findsOneWidget);
  });

  testWidgets('Ctrl+K opens the palette and loading a command does not execute it',
      (tester) async {
    await pumpApp(tester);

    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.keyK);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await tester.pumpAndSettle();

    expect(find.textContaining('Jump to a section'), findsOneWidget);
    expect(
      find.text('Selecting a command loads it into the editor. It is not executed.'),
      findsOneWidget,
    );

    await tester.enterText(find.byType(TextField).first, 'SYSTEM INFO');
    await tester.pumpAndSettle();
    await tester.tap(find.text('SYSTEM INFO').last);
    await tester.pumpAndSettle();

    // Landed in the Command Center with the text loaded, and nothing was sent.
    final editor = tester.widget<TextField>(find.byType(TextField).first);
    expect(editor.controller!.text, 'SYSTEM INFO');
    expect(transport.requests.where((r) => r.uri.path == '/command'), isEmpty);
  });

  testWidgets('the sidebar collapses to icons on a narrow window', (tester) async {
    await pumpApp(tester, size: const Size(900, 800));

    // Labels are gone from the rail; the destinations are still reachable.
    expect(find.text('Forensic workstation'), findsNothing);
    expect(find.byIcon(JockyDestination.commandCenter.icon), findsWidgets);
  });

  testWidgets('resizing from narrow back to wide restores the labelled rail',
      (tester) async {
    await pumpApp(tester, size: const Size(900, 800));
    expect(find.text('Forensic workstation'), findsNothing);

    tester.view.physicalSize = const Size(1500, 950);
    await tester.pumpAndSettle();

    expect(find.text('Forensic workstation'), findsOneWidget);
    expect(find.text('ACTIVE CASE'), findsOneWidget);
  });

  testWidgets('an unknown route reports itself instead of rendering blank', (tester) async {
    await pumpApp(tester, initialLocation: '/does-not-exist');

    expect(find.textContaining('No screen is registered'), findsOneWidget);
    expect(find.text('Back to Overview'), findsOneWidget);
  });

  testWidgets('the engine-offline state is visible in the shell', (tester) async {
    transport.fail('/health', const SocketException('refused'));
    await pumpApp(tester);

    expect(find.text('Engine offline'), findsWidgets);
  });
}
