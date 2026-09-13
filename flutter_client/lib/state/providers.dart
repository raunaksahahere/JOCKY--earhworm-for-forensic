import 'dart:io';
import '../services/storage/api_record_store.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/config/app_config.dart';
import '../core/errors/failure.dart';
import '../core/networking/http_transport.dart';
import '../models/settings/workstation_settings.dart';
import '../repositories/backend_repository.dart';
import '../repositories/command_repository.dart';
import '../repositories/records_repository.dart';
import '../services/api/jocky_api_client.dart';
import '../services/backend/backend_supervisor.dart';
import '../services/export/report_export_service.dart';
import '../services/file_selection/file_selection_service.dart';
import '../services/storage/record_store.dart';
import '../services/storage/settings_store.dart';
import 'backend_controller.dart';
import 'settings_controller.dart';

// Re-exported so feature code has one import for the whole provider graph.
export 'backend_controller.dart';
export 'execution_controller.dart';
export 'records_controller.dart';
export 'settings_controller.dart';

/// Injection seams. Every one of these is overridden in `main()` with a real
/// implementation, and in tests with a fake, so no widget ever constructs a
/// service itself.
final settingsStoreProvider = Provider<SettingsStore>(
  (ref) => throw UnimplementedError('settingsStoreProvider must be overridden'),
);

final recordStoreProvider = Provider<RecordStore>(
  (ref) => ApiRecordStore(ref.watch(apiClientProvider)),
);

/// Settings read from disk before the first frame, so the app never renders
/// against a placeholder configuration and then jumps.
final initialSettingsProvider = Provider<WorkstationSettings>(
  (ref) => WorkstationSettings.defaults,
);

/// Records read from disk before the first frame, with the failure that
/// occurred while reading them (if any) preserved rather than swallowed.
final initialRecordsProvider = Provider<(WorkstationRecords, JockyFailure?)>(
  (ref) => (WorkstationRecords.empty, null),
);

final httpTransportProvider = Provider<HttpTransport>((ref) {
  final transport = HttpClientTransport();
  ref.onDispose(transport.close);
  return transport;
});

final fileSelectionProvider = Provider<FileSelectionService>(
  (ref) => const NativeFileSelectionService(),
);

final reportExportProvider = Provider<ReportExportService>(
  (ref) => FileReportExportService(api: ref.read(apiClientProvider)),
);

final appConfigProvider = Provider<AppConfig>((ref) {
  final settings = ref.watch(settingsControllerProvider);
  return settings.toConfig();
});

final apiClientProvider = Provider<JockyApiClient>((ref) {
  return JockyApiClient(
    config: ref.read(appConfigProvider),
    transport: ref.watch(httpTransportProvider),
  );
});

final backendSupervisorProvider = Provider<BackendSupervisor>((ref) {
  final settings = ref.read(initialSettingsProvider);
  final supervisor = BackendSupervisor(
    config: ref.read(appConfigProvider),
    api: ref.watch(apiClientProvider),
    locator: BackendLocator(overridePath: settings.backendExecutableOverride ?? Platform.environment['JOCKY_BACKEND']),
    workspace: Platform.environment['JOCKY_WORKSPACE'] ?? ref.read(initialSettingsProvider).portableWorkspace,
  );
  ref.onDispose(supervisor.dispose);
  return supervisor;
});

final backendRepositoryProvider = Provider<BackendRepository>((ref) => BackendRepository(
      api: ref.watch(apiClientProvider),
      supervisor: ref.watch(backendSupervisorProvider),
    ));

final commandRepositoryProvider =
    Provider<CommandRepository>((ref) => CommandRepository(ref.watch(apiClientProvider)));

final recordsRepositoryProvider =
    Provider<RecordsRepository>((ref) => RecordsRepository(ref.watch(recordStoreProvider)));

/// Backend-owned command syntax. Kept as a future so the Command Center can
/// show a reference-unavailable state without blocking command submission.
final commandReferenceProvider = FutureProvider.autoDispose((ref) async {
  // Re-fetch whenever the engine becomes ready again.
  ref.watch(backendControllerProvider);
  return ref.watch(commandRepositoryProvider).referenceOrFailure();
});
