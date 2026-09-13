import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/settings/workstation_settings.dart';
import 'providers.dart';

/// Application-wide preferences. Writes are persisted immediately; a failed
/// write leaves the in-memory value in place and is reported by [lastError]
/// rather than silently reverting the analyst's choice.
class SettingsController extends Notifier<WorkstationSettings> {
  String? lastError;

  @override
  WorkstationSettings build() => ref.watch(initialSettingsProvider);

  Future<void> update(
    WorkstationSettings Function(WorkstationSettings current) transform,
  ) async {
    final next = transform(state);
    state = next;
    try {
      await ref.read(settingsStoreProvider).save(next);
      lastError = null;
    } on Object catch (error) {
      lastError = '$error';
    }
  }

  Future<void> setEndpoint({required String host, required int port}) =>
      update((s) => s.copyWith(host: host, port: port));

  Future<void> setDisplayUtc(bool value) => update((s) => s.copyWith(displayUtc: value));

  Future<void> setTextScale(double value) =>
      update((s) => s.copyWith(textScale: value.clamp(0.8, 1.6)));

  Future<void> setDenseTables(bool value) => update((s) => s.copyWith(denseTables: value));

  Future<void> setExportDirectory(String? path) => update(
        (s) => path == null
            ? s.copyWith(clearExportDirectory: true)
            : s.copyWith(exportDirectory: path),
      );

  Future<void> setBackendExecutableOverride(String? path) => update(
        (s) => path == null || path.isEmpty
            ? s.copyWith(clearBackendOverride: true)
            : s.copyWith(backendExecutableOverride: path),
      );

  Future<void> setAutoStartBackend(bool value) =>
      update((s) => s.copyWith(autoStartBackend: value));

  Future<void> setRequestTimeout(int seconds) =>
      update((s) => s.copyWith(requestTimeoutSeconds: seconds.clamp(5, 300)));

  Future<void> restoreDefaults() => update((_) => WorkstationSettings.defaults);
}

final settingsControllerProvider =
    NotifierProvider<SettingsController, WorkstationSettings>(SettingsController.new);
