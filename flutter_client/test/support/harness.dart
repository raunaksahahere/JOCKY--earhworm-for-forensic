import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:jocky_client/core/config/app_config.dart';
import 'package:jocky_client/core/errors/failure.dart';
import 'package:jocky_client/core/theme/app_theme.dart';
import 'package:jocky_client/models/settings/workstation_settings.dart';
import 'package:jocky_client/services/api/jocky_api_client.dart';
import 'package:jocky_client/services/file_selection/file_selection_service.dart';
import 'package:jocky_client/services/storage/record_store.dart';
import 'package:jocky_client/services/storage/settings_store.dart';
import 'package:jocky_client/state/providers.dart';

import 'fake_transport.dart';

/// File selection that returns scripted paths instead of opening a native
/// dialog, so path handling can be tested without a desktop session.
class FakeFileSelection implements FileSelectionService {
  FakeFileSelection({this.file, this.directory, this.saveLocation});

  String? file;
  String? directory;
  String? saveLocation;

  int fileCalls = 0;
  int directoryCalls = 0;

  @override
  Future<String?> pickFile({String? confirmButtonText}) async {
    fileCalls++;
    return file;
  }

  @override
  Future<String?> pickDirectory({String? confirmButtonText}) async {
    directoryCalls++;
    return directory;
  }

  @override
  Future<String?> pickSaveLocation({
    required String suggestedName,
    required String extension,
  }) async =>
      saveLocation;
}

/// Identity of the engine the fake transport represents. The bootstrap token
/// has to clear the client's 32-character minimum.
const testInstanceId = 'test-instance';
const testToken = 'test-bootstrap-token-0123456789abcdefghij';

/// An API client that has already completed the bootstrap handshake.
///
/// Production code cannot reach the engine any other way: the engine binds an
/// OS-assigned port and mints a per-process token, both announced over the
/// bootstrap channel, and every route including `/health` requires that token.
/// A test that exercises the readiness probe therefore has to start from a
/// bootstrapped session, exactly as the running application does.
JockyApiClient bootstrappedApi(FakeTransport transport) =>
    JockyApiClient(config: testConfig, transport: transport)
      ..establishSession(testConfig.port, testToken, testInstanceId);

/// A provider scope wired entirely to fakes.
///
/// Only the transport and the two stores are replaced; every controller,
/// repository and the API client itself run their real code, so the tests
/// exercise the actual request/response path rather than a stand-in for it.
ProviderContainer testContainer({
  required FakeTransport transport,
  WorkstationRecords records = WorkstationRecords.empty,
  JockyFailure? recordFailure,
  WorkstationSettings? settings,
  FileSelectionService? fileSelection,
  RecordStore? recordStore,
}) {
  final container = ProviderContainer(
    overrides: [
      httpTransportProvider.overrideWithValue(transport),
      apiClientProvider.overrideWith((ref) => bootstrappedApi(transport)),
      settingsStoreProvider.overrideWithValue(InMemorySettingsStore()),
      recordStoreProvider.overrideWithValue(recordStore ?? InMemoryRecordStore(records)),
      initialSettingsProvider.overrideWithValue(
        settings ?? const WorkstationSettings(port: 5099),
      ),
      initialRecordsProvider.overrideWithValue((records, recordFailure)),
      if (fileSelection != null) fileSelectionProvider.overrideWithValue(fileSelection),
    ],
  );
  addTearDownDispose(container);
  return container;
}

// Kept separate so widget tests can also register the teardown.
void Function(ProviderContainer container) addTearDownDispose = (_) {};

/// Wraps a screen in the real theme and provider scope for widget tests.
Widget harness(
  Widget child, {
  required FakeTransport transport,
  WorkstationRecords records = WorkstationRecords.empty,
  JockyFailure? recordFailure,
  WorkstationSettings? settings,
  FileSelectionService? fileSelection,
  Size size = const Size(1440, 900),
}) {
  return ProviderScope(
    overrides: [
      httpTransportProvider.overrideWithValue(transport),
      apiClientProvider.overrideWith((ref) => bootstrappedApi(transport)),
      settingsStoreProvider.overrideWithValue(InMemorySettingsStore()),
      recordStoreProvider.overrideWithValue(InMemoryRecordStore(records)),
      initialSettingsProvider.overrideWithValue(
        settings ?? const WorkstationSettings(port: 5099),
      ),
      initialRecordsProvider.overrideWithValue((records, recordFailure)),
      if (fileSelection != null) fileSelectionProvider.overrideWithValue(fileSelection),
    ],
    child: MaterialApp(
      theme: buildJockyTheme(),
      home: Scaffold(body: child),
    ),
  );
}

const testConfig = AppConfig(port: 5099);
