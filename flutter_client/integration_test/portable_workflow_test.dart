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
    // Version-agnostic: the guarantees below are what matter, not the number.
    expect(report['schema_version'], greaterThanOrEqualTo(4));
    // Priority is present, three-tiered, and separate from classification.
    final priorities = report['triage']['priorities'] as Map;
    expect(priorities.keys.toSet(), {'PRIORITY_1', 'PRIORITY_2', 'PRIORITY_3'});
    // Leads are deduplicated by pattern: one lead can cover several commands,
    // and every one of them keeps its own evidence identifier.
    for (final lead in report['leads'] as List) {
      expect(['PRIORITY_1', 'PRIORITY_2'], contains(lead['priority']));
      expect(lead['why'], isNotEmpty, reason: 'a lead must say why it matters');
      expect(lead['commands'], isNotEmpty);
      expect(lead['evidence_references'], isNotEmpty);
    }
    // Threads group related activity without claiming intent.
    for (final thread in report['threads'] as List) {
      expect(thread['thread_id'], isNotNull);
      expect(thread['activity_count'], greaterThanOrEqualTo(2));
      expect(thread['note'], contains('does not state what anyone intended'));
    }
    // The short timeline is bounded and says where the rest lives.
    expect(report['significant_events']['entry_count'], lessThanOrEqualTo(40));
    expect(report['conclusion'], isNotEmpty);
    // Missing arguments are a limitation, never a concern signal.
    for (final group in report['activity']['groups'] as List) {
      if (group['command_reconstruction_status'] == 'EXECUTABLE_ONLY') {
        for (final signal in group['classification']['signals'] as List) {
          expect(signal['name'], isNot(startsWith('remote_')));
          expect(signal['name'], isNot(startsWith('download_')));
        }
      }
    }
    // Counts must be named for what they are, never one blurred total.
    final counts = report['record_counts'] as Map<String, dynamic>;
    expect(counts.containsKey('execution_source_records'), isTrue);
    expect(counts.containsKey('command_history_records'), isTrue);
    expect(counts.containsKey('session_records'), isTrue);
    expect(counts.containsKey('events'), isFalse);
    // Triage is present and three-way.
    expect((report['triage']['counts'] as Map).keys.toSet(), {
      'POTENTIALLY_HARMFUL', 'NEEDS_REVIEW', 'NOT_HARMFUL_ON_AVAILABLE_EVIDENCE'});
    // Collection limitations are kept apart from activity findings.
    final findingCategories =
        (report['findings'] as List).map((item) => item['category']).toSet();
    expect(findingCategories.contains('telemetry_unavailable'), isFalse,
        reason: 'a disabled telemetry source is a limitation, not an activity finding');
    expect(report['collection_limitations'], isNotEmpty);
    // Command history is never reported as confirmed execution, and where the
    // source recorded a whole command it survives whole.
    for (final group in report['activity']['groups'] as List) {
      if (group['evidence_kind'] == 'COMMAND_HISTORY') {
        expect(group['execution_confirmed'], isFalse);
      }
      for (final record in group['records'] as List) {
        expect(record['reference'], isNotNull);
      }
    }
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
