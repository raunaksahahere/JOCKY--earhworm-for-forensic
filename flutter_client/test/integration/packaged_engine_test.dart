import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:jocky_client/core/config/app_config.dart';
import 'package:jocky_client/core/networking/http_transport.dart';
import 'package:jocky_client/services/api/jocky_api_client.dart';
import 'package:jocky_client/services/backend/backend_supervisor.dart';

/// Discovery and startup against the real release bundle, with no override.
///
/// This is the regression the shipped Linux build hit: the bundle contained no
/// `backend/` directory at all, so the supervisor resolved nothing, and the
/// periodic health poll then reported "No engine is listening on
/// http://127.0.0.1:5000" — an endpoint the engine never uses — which hid the
/// real cause. Everything here therefore runs unmocked: the locator walks the
/// real bundle, the real process is spawned, and readiness comes from a real
/// authenticated /health reply.
void main() {
  final bundle = Directory(
    Platform.environment['JOCKY_TEST_BUNDLE'] ?? 'build/linux/x64/release/bundle',
  );
  final skip = bundle.existsSync()
      ? null
      : 'No release bundle at ${bundle.path}; run flutter build linux --release first.';

  test('the release bundle starts its own engine and reports the assigned port', () async {
    final workspace = await Directory.systemTemp.createTemp('jocky packaged ');
    addTearDown(() => workspace.delete(recursive: true));

    final transport = HttpClientTransport();
    addTearDown(transport.close);
    // Deliberately the shipped default, so a supervisor that never learns the
    // real port would be caught rather than accidentally pointed at the engine.
    const config = AppConfig(startupTimeout: Duration(seconds: 45));
    final api = JockyApiClient(config: config, transport: transport);

    final supervisor = BackendSupervisor(
      config: config,
      api: api,
      // No overridePath: this is the discovery path the packaged app uses.
      locator: BackendLocator(resolveExecutableDir: () => bundle.absolute.path),
      workspace: workspace.path,
    );
    addTearDown(supervisor.dispose);

    final resolved = supervisor.status;
    expect(resolved.phase, BackendPhase.idle);

    final status = await supervisor.start();

    expect(status.phase, BackendPhase.ready,
        reason: 'failed with: ${status.failure?.message} / ${status.failure?.detail}');
    expect(status.managedByClient, isTrue);
    expect(status.executablePath, contains('backend'));
    expect(status.origin, isNotNull);
    expect(status.origin, isNot(contains(':${AppConfig.defaultPort}')),
        reason: 'the UI must show the OS-assigned port, not the placeholder');

    // A real authenticated call over the endpoint the engine chose.
    final health = await api.jsonRequest('/api/v1/health');
    expect(health['ready'], isTrue);
    expect(health['versions'], isNotNull);

    await supervisor.stop();
    expect(supervisor.status.phase, BackendPhase.stopped);
  }, timeout: const Timeout(Duration(minutes: 2)), skip: skip);

  test('a bundle without an engine names every location it searched', () async {
    final empty = await Directory.systemTemp.createTemp('jocky empty bundle ');
    addTearDown(() => empty.delete(recursive: true));

    final locator = BackendLocator(resolveExecutableDir: () => empty.path);

    expect(locator.resolve(), isNull);
    final description = locator.describeSearch();
    // Built the way the locator builds it: the separator and the engine name
    // both differ on Windows, and hardcoding the POSIX spelling would assert
    // the wrong thing there rather than find a bug.
    final expected = [
      empty.path,
      'backend',
      Platform.isWindows ? 'JOCKY-backend.exe' : 'jocky-backend',
    ].join(Platform.pathSeparator);
    expect(description, contains('$expected (missing)'));
    expect(description, contains('backend-dist'),
        reason: 'the developer layout is searched by walking up, not by a fixed ascent');
  });
}
