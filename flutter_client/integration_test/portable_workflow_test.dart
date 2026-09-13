import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:integration_test/integration_test.dart';
import 'package:jocky_client/app/app.dart';
import 'package:jocky_client/models/settings/workstation_settings.dart';
import 'package:jocky_client/services/storage/settings_store.dart';
import 'package:jocky_client/state/providers.dart';
import '../test/support/harness.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('portable collect, restart, reopen and offline PDF export', (tester) async {
    final workspace = await Directory.systemTemp.createTemp('jocky flutter integration ');
    final executable = Platform.environment['JOCKY_TEST_BACKEND'];
    expect(executable, isNotNull, reason: 'Set JOCKY_TEST_BACKEND to the frozen backend executable');
    final export = '${workspace.path}/investigation.pdf';
    final settings = WorkstationSettings(backendExecutableOverride: executable, portableWorkspace: workspace.path);
    final container = ProviderContainer(overrides: [
      settingsStoreProvider.overrideWithValue(InMemorySettingsStore(settings)),
      initialSettingsProvider.overrideWithValue(settings),
      fileSelectionProvider.overrideWithValue(FakeFileSelection(saveLocation: export)),
    ]);
    await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const JockyApp(initialLocation: '/device')));
    for (var i=0; i<100 && !container.read(backendReadyProvider); i++) {
      await tester.pump(const Duration(milliseconds: 200));
    }
    expect(container.read(backendReadyProvider), isTrue);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('analyze-device')));
    for (var i=0; i<150 && find.byKey(const Key('export-investigation-pdf')).evaluate().isEmpty; i++) {
      await tester.pump(const Duration(milliseconds: 200));
    }
    expect(find.byKey(const Key('export-investigation-pdf')), findsOneWidget);
    final api = container.read(apiClientProvider);
    final cases = await api.jsonRequest('/api/v1/investigations');
    final id = cases['items'][0]['id'];

    // Historical execution evidence, the artifacts it names, the correlation
    // findings and the merged timeline must all be persisted by the real
    // engine on this host -- not merely rendered.
    final history = await api.jsonRequest('/api/v1/investigations/$id/execution-events');
    final artifacts = await api.jsonRequest('/api/v1/investigations/$id/artifacts');
    final findings = await api.jsonRequest('/api/v1/investigations/$id/findings');
    final eventTimeline = await api.jsonRequest('/api/v1/investigations/$id/event-timeline');
    expect((history['items'] as List), isNotEmpty,
        reason: 'this Linux host exposes the systemd journal; historical evidence must be collected');
    expect((artifacts['items'] as List), isNotEmpty);
    expect((findings['items'] as List), isNotEmpty,
        reason: 'an investigation with evidence must not end with zero findings');
    expect((eventTimeline['items'] as List), isNotEmpty);

    final stored = await api.jsonRequest('/api/v1/investigations/$id/reports');
    final report = (stored['items'] as List).last['payload'] as Map<String, dynamic>;
    expect(report['schema_version'], 3);
    expect(report['collection_window']['bounded'], isTrue);
    expect(report['historical_execution']['telemetry_available'], isTrue);
    expect(report['appendix_process_listing'], isNotEmpty,
        reason: 'the raw process listing moves to an appendix, it is not discarded');
    // Sources that were absent or disabled must be named, not omitted.
    expect(report['unavailable_telemetry'], isNotEmpty);
    for (final event in history['items'] as List) {
      expect(event['classification'], 'HISTORICAL_EVIDENCE');
      expect(event['source'], isNotNull);
    }

    final supervisor = container.read(backendSupervisorProvider);
    await supervisor.stop();
    await supervisor.start();
    final saved = await api.jsonRequest('/api/v1/investigations/$id');
    expect(['completed', 'partially_completed'], contains(saved['status']));
    // Everything the analysis produced must still be there after the restart.
    final afterRestart = await api.jsonRequest('/api/v1/investigations/$id/execution-events');
    expect((afterRestart['items'] as List).length, (history['items'] as List).length);
    await tester.tap(find.text('All investigations'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Local device investigation').last);
    for (var i=0; i<50 && find.byKey(const Key('export-investigation-pdf')).evaluate().isEmpty; i++) {
      await tester.pump(const Duration(milliseconds: 200));
    }
    await tester.tap(find.byKey(const Key('export-investigation-pdf')));
    for (var i=0; i<150 && !File(export).existsSync(); i++) {
      await tester.pump(const Duration(milliseconds: 200));
    }
    expect(File(export).existsSync(), isTrue);
    expect(await File(export).readAsBytes().then((bytes) => String.fromCharCodes(bytes.take(5))), '%PDF-');
    await supervisor.stop();
    await tester.pumpWidget(const SizedBox.shrink());
    container.dispose();
  });
}
