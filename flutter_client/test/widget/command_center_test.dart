import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jocky_client/app/shortcuts.dart';
import 'package:jocky_client/features/command_center/command_center_screen.dart';

import '../support/fake_transport.dart';
import '../support/fixtures.dart';
import '../support/harness.dart';

void main() {
  late FakeTransport transport;

  setUp(() {
    transport = FakeTransport();
    transport.respondJson('/health', loadFixture('health'));
    transport.respondJson('/commands', loadFixture('commands'));
  });

  Future<void> pump(
    WidgetTester tester, {
    Size size = const Size(1440, 900),
    FakeFileSelection? fileSelection,
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(harness(
      // Shortcuts normally come from the app root; wire them for this screen.
      Shortcuts(
        shortcuts: globalShortcuts(),
        child: const CommandCenterScreen(),
      ),
      transport: transport,
      fileSelection: fileSelection,
    ));
    await tester.pumpAndSettle();
  }

  testWidgets('starts in an explicit empty state, not a blank panel', (tester) async {
    await pump(tester);

    expect(find.text('No command submitted yet'), findsOneWidget);
    expect(find.text('Execute'), findsOneWidget);
  });

  testWidgets('renders the engine-published command reference', (tester) async {
    await pump(tester);

    expect(find.text('HASH FILE <path>'), findsOneWidget);
    expect(find.textContaining('Schema v1'), findsOneWidget);
    expect(find.textContaining('6 actions'), findsOneWidget);

    // The rest of the catalogue is below the fold; scrolling reaches it.
    await tester.scrollUntilVisible(
      find.text('SEARCH FILE <name> IN <path>'),
      120,
      scrollable: find
          .descendant(
            of: find.byKey(const ValueKey('command-reference-list')),
            matching: find.byType(Scrollable),
          )
          .first,
    );
    expect(find.text('SEARCH FILE <name> IN <path>'), findsOneWidget);
  });

  testWidgets('a successful hash renders the digest and ledger comparison', (tester) async {
    transport.respondJson('/command', loadFixture('hash'));
    await pump(tester);

    await tester.enterText(find.byType(TextField).first, 'HASH FILE evidence.bin');
    await tester.tap(find.text('Execute'));
    await tester.pumpAndSettle();

    expect(find.text('SHA256'), findsWidgets);
    expect(find.text('Execution completed'), findsOneWidget);
    // The hash collector reports no `complete` field, so the UI must say the
    // completeness is unreported rather than implying a complete observation.
    expect(find.text('Completeness not reported'), findsOneWidget);
    expect(find.text('HASH LEDGER COMPARISON'), findsOneWidget);
  });

  testWidgets('a parser rejection shows the engine message and code, not a generic error',
      (tester) async {
    transport.respondJson('/command', loadFixture('syntax_error'), status: 400);
    await pump(tester);

    await tester.enterText(find.byType(TextField).first, 'HASH FIL x');
    await tester.tap(find.text('Execute'));
    await tester.pumpAndSettle();

    expect(find.text('Command rejected by parser'), findsOneWidget);
    expect(find.text('invalid_syntax'), findsOneWidget);
    expect(find.textContaining('line 1, column 6'), findsOneWidget);
    expect(find.textContaining('Something went wrong'), findsNothing);
  });

  testWidgets('an execution failure is distinguished from a command rejection',
      (tester) async {
    transport.respondJson('/command', loadFixture('notfound'), status: 400);
    await pump(tester);

    await tester.enterText(find.byType(TextField).first, 'HASH FILE /nonexistent/zzz.bin');
    await tester.tap(find.text('Execute'));
    await tester.pumpAndSettle();

    // Shown both as the execution state chip and as the failure headline.
    expect(find.text('Execution failed'), findsNWidgets(2));
    expect(find.text('not_found'), findsOneWidget);
    expect(find.textContaining('readable by the account running the engine'), findsOneWidget);
  });

  testWidgets('Ctrl+Enter submits the command', (tester) async {
    transport.respondJson('/command', loadFixture('system'));
    await pump(tester);

    await tester.enterText(find.byType(TextField).first, 'SYSTEM INFO');
    await tester.pump();
    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await tester.pumpAndSettle();

    expect(find.text('Execution completed'), findsOneWidget);
    expect(transport.requests.where((r) => r.uri.path == '/command'), hasLength(1));
  });

  testWidgets('Ctrl+O inserts a selected evidence path, quoting only when needed',
      (tester) async {
    final selection = FakeFileSelection(file: '/evidence/case 1/नमूना image.bin');
    await pump(tester, fileSelection: selection);

    await tester.enterText(find.byType(TextField).first, 'HASH FILE ');
    await tester.pump();
    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.keyO);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await tester.pumpAndSettle();

    expect(selection.fileCalls, 1);
    final field = tester.widget<TextField>(find.byType(TextField).first);
    expect(field.controller!.text, 'HASH FILE "/evidence/case 1/नमूना image.bin"');
  });

  testWidgets('a path without spaces is inserted unquoted', (tester) async {
    final selection = FakeFileSelection(file: '/evidence/image.bin');
    await pump(tester, fileSelection: selection);

    await tester.tap(find.text('Evidence file'));
    await tester.pumpAndSettle();

    final field = tester.widget<TextField>(find.byType(TextField).first);
    expect(field.controller!.text, '/evidence/image.bin');
  });

  testWidgets('the engine-offline boundary is shown when health fails', (tester) async {
    transport.fail('/health', const SocketException('Connection refused'));
    await pump(tester);

    expect(find.text('Engine offline'), findsOneWidget);
    expect(find.textContaining('not currently reachable'), findsOneWidget);
  });

  testWidgets('process results render null CPU as unavailable, never as zero',
      (tester) async {
    transport.respondJson('/command', loadFixture('processes'));
    // A tall viewport so the whole process table is laid out in one pass.
    await pump(tester, size: const Size(1440, 2400));

    await tester.enterText(find.byType(TextField).first, 'PROCESSES');
    await tester.tap(find.text('Execute'));
    await tester.pumpAndSettle();

    expect(find.text('PID'), findsOneWidget);
    // Unavailable measurements render as the explicit marker, with the reason
    // in the tooltip — never as a number.
    expect(
      find.byTooltip(
        'A single snapshot cannot establish an interval CPU percentage. '
        'The engine reports null rather than 0.',
      ),
      findsWidgets,
    );
    // Null must never be rendered as a zero measurement.
    expect(find.text('0.0%'), findsNothing);
    expect(find.text('0.00%'), findsNothing);
  });

  testWidgets('the reference panel collapses on a narrow window', (tester) async {
    await pump(tester, size: const Size(1000, 800));

    expect(find.text('Command reference'), findsNothing);
    // The editor itself stays usable at that width.
    expect(find.text('Execute'), findsOneWidget);
  });

  testWidgets('clearing resets the editor and the result panel', (tester) async {
    transport.respondJson('/command', loadFixture('system'));
    await pump(tester);
    await tester.enterText(find.byType(TextField).first, 'SYSTEM INFO');
    await tester.tap(find.text('Execute'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Clear'));
    await tester.pumpAndSettle();

    expect(find.text('No command submitted yet'), findsOneWidget);
    final field = tester.widget<TextField>(find.byType(TextField).first);
    expect(field.controller!.text, isEmpty);
  });
}
