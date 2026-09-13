import 'dart:async';
import 'dart:io';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:jocky_client/core/config/app_config.dart';
import 'package:jocky_client/core/errors/failure.dart';
import 'package:jocky_client/services/api/jocky_api_client.dart';
import 'package:jocky_client/services/backend/backend_supervisor.dart';

import '../support/fake_transport.dart';
import '../support/fixtures.dart';

class FakeProcess implements ManagedProcess {
  FakeProcess({this.pid = 4242});

  @override
  final int pid;

  final exitCompleter = Completer<int>();
  final stdoutController = StreamController<List<int>>.broadcast();
  final stderrController = StreamController<List<int>>.broadcast();

  bool terminated = false;
  bool killed = false;

  @override
  Future<int> get exitCode => exitCompleter.future;

  @override
  Stream<List<int>> get stdout => stdoutController.stream;

  @override
  Stream<List<int>> get stderr => stderrController.stream;

  @override
  bool terminate() {
    terminated = true;
    return true;
  }

  @override
  bool kill() {
    killed = true;
    if (!exitCompleter.isCompleted) exitCompleter.complete(-9);
    return true;
  }

  void exitWith(int code) {
    if (!exitCompleter.isCompleted) exitCompleter.complete(code);
  }
}

class FakeRunner implements ProcessRunner {
  FakeRunner({this.process, this.error, this.bootstrap = _readyBootstrap});

  static const _readyBootstrap = {
    'protocol': 1, 'event': 'ready', 'port': 5099, 'token': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'instance_id': 'test-instance',
  };

  final FakeProcess? process;
  final Object? error;

  /// Bootstrap record the fake engine writes to stdout, or null to write none.
  final Map<String, Object?>? bootstrap;

  final List<({String executable, Map<String, String> environment, String? cwd})> starts = [];

  @override
  Future<ManagedProcess> start(
    String executable,
    List<String> arguments, {
    required Map<String, String> environment,
    String? workingDirectory,
  }) async {
    starts.add((executable: executable, environment: environment, cwd: workingDirectory));
    if (error != null) throw error!;
    if (bootstrap != null) {
      Timer(const Duration(milliseconds: 5),
          () => process!.stdoutController.add(utf8.encode('${jsonEncode(bootstrap)}\n')));
    }
    return process!;
  }
}

/// Locator whose candidate list is satisfied by an explicit set of paths, so
/// the test never needs a real binary on disk.
BackendLocator locatorFor(String? existing) => BackendLocator(
      overridePath: existing,
      resolveExecutableDir: () => '/opt/jocky',
    );

void main() {
  late FakeTransport transport;
  late JockyApiClient api;
  const config = AppConfig(
    port: 5099,
    healthTimeout: Duration(milliseconds: 100),
    startupTimeout: Duration(milliseconds: 600),
  );

  setUp(() {
    transport = FakeTransport();
    api = JockyApiClient(config: config, transport: transport);
  });

  BackendSupervisor supervisorWith({
    ProcessRunner? runner,
    BackendLocator? locator,
  }) =>
      BackendSupervisor(
        config: config,
        api: api,
        runner: runner ?? FakeRunner(process: FakeProcess()),
        locator: locator ?? locatorFor(null),
        probeInterval: const Duration(milliseconds: 20),
      );

  test('probe reports unavailable when nothing is listening', () async {
    api.establishSession(5099, 'a' * 43, 'test-instance');
    transport.fail('/health', const SocketException('Connection refused'));

    final status = await supervisorWith().probe();

    expect(status.phase, BackendPhase.unavailable);
    expect(status.failure!.kind, FailureKind.backendUnavailable);
    expect(status.managedByClient, isFalse);
  });

  test('probe without a bootstrap session never invents a connection error', () async {
    // The port is assigned by the OS and announced at startup, so before a
    // session there is nothing to probe. The periodic health poll used to
    // report "No engine is listening on http://127.0.0.1:5000" here, which
    // overwrote the real startup failure with a fabricated one.
    var requested = false;
    transport.handlers['/health'] = () {
      requested = true;
      throw const SocketException('refused');
    };
    final supervisor = supervisorWith();

    final status = await supervisor.probe();

    expect(requested, isFalse, reason: 'no endpoint is known yet');
    expect(status.phase, BackendPhase.idle);
    expect(status.failure, isNull);
  });

  test('the health poll does not overwrite a resolved startup failure', () async {
    transport.fail('/health', const SocketException('refused'));
    final supervisor = supervisorWith(locator: locatorFor(null));

    final failed = await supervisor.start();
    expect(failed.failure!.message, contains('was not found'));

    // What the periodic poll in BackendController does, every interval.
    final afterPoll = await supervisor.probe();

    expect(afterPoll.failure!.message, contains('was not found'),
        reason: 'the actionable cause must survive the readiness poll');
  });

  test('adopts only a session already authenticated by this client', () async {
    api.establishSession(5099, 'a' * 43, 'test-instance');
    transport.respondJson('/health', {...loadFixture('health'), 'instance_id': 'test-instance'});
    final runner = FakeRunner(process: FakeProcess());
    final supervisor = supervisorWith(runner: runner);

    final status = await supervisor.start();

    expect(status.phase, BackendPhase.ready);
    expect(status.managedByClient, isFalse,
        reason: 'an adopted engine must not be reported as client-owned');
    expect(runner.starts, isEmpty, reason: 'a second engine must not be launched');
  });

  test('start fails clearly when the packaged engine is missing', () async {
    transport.fail('/health', const SocketException('refused'));
    // No override and no file on disk at the default candidate paths.
    final supervisor = supervisorWith(locator: locatorFor(null));

    final status = await supervisor.start();

    expect(status.phase, BackendPhase.unavailable);
    expect(status.failure!.message, contains('was not found'));
    expect(status.failure!.detail, contains('/opt/jocky'));
    expect(status.failure!.detail, contains('(missing)'),
        reason: 'each rejected candidate is explained, not just listed');
  });

  test('start launches the engine with the bootstrap environment and waits for health',
      () async {
    // Unhealthy until the third probe, then ready — the documented contract is
    // "poll /health until it answers", not "assume ready after spawn".
    var probes = 0;
    transport.handlers['/health'] = () {
      probes++;
      if (probes < 3) throw const SocketException('refused');
      return _jsonResponse(jsonEncode({...loadFixture('health'), 'instance_id': 'test-instance'}));
    };

    final process = FakeProcess();
    final runner = FakeRunner(process: process);
    final supervisor = supervisorWith(
      runner: runner,
      locator: locatorFor(Platform.resolvedExecutable),
    );

    final status = await supervisor.start();

    expect(status.phase, BackendPhase.ready);
    expect(status.managedByClient, isTrue);
    expect(status.processId, 4242);
    expect(runner.starts.single.environment.containsKey('JOCKY_PORT'), isFalse);
    expect(api.hasSession, isTrue);
    expect(supervisor.diagnosticLog.join(), isNot(contains('a' * 43)));
    expect(runner.starts.single.environment['JOCKY_HOST'], '127.0.0.1');
    expect(probes, greaterThanOrEqualTo(3));
    expect(status.origin, 'http://127.0.0.1:5099',
        reason: 'the UI must show the assigned port, not the placeholder');
  });

  test('a startup_error is reported with the engine reason, not a timeout', () async {
    transport.fail('/health', const SocketException('refused'));
    final process = FakeProcess();
    final supervisor = supervisorWith(
      runner: FakeRunner(process: process, bootstrap: {
        'protocol': 1,
        'event': 'startup_error',
        'instance_id': 'test-instance',
        'error': {
          'code': 'startup_failed',
          'type': 'RuntimeError',
          'message': 'Workspace is already in use',
        },
      }),
      locator: locatorFor(Platform.resolvedExecutable),
    );

    final status = await supervisor.start();

    expect(status.phase, BackendPhase.unavailable);
    expect(status.failure!.message, contains('Workspace is already in use'));
    expect(status.failure!.kind, isNot(FailureKind.timeout));
  });

  test('an exit during startup reports the engine stderr, not only a code', () async {
    transport.fail('/health', const SocketException('refused'));
    final process = FakeProcess();
    final supervisor = supervisorWith(
      runner: FakeRunner(process: process, bootstrap: null),
      locator: locatorFor(Platform.resolvedExecutable),
    );

    final starting = supervisor.start();
    await Future<void>.delayed(const Duration(milliseconds: 10));
    process.stderrController.add(utf8.encode('ImportError: libffi.so.8 missing\n'));
    await Future<void>.delayed(const Duration(milliseconds: 10));
    process.exitWith(1);
    await starting;

    expect(supervisor.status.exitCode, 1);
    expect(supervisor.status.detail, contains('libffi.so.8'));
  });

  test('startup that never becomes healthy fails at the deadline', () async {
    transport.fail('/health', const SocketException('refused'));
    final supervisor = supervisorWith(
      locator: locatorFor(Platform.resolvedExecutable),
    );

    final status = await supervisor.start();

    expect(status.phase, BackendPhase.degraded);
    expect(status.failure, isNotNull);
  });

  test('an engine that answers /health but is not online is degraded, not ready', () async {
    api.establishSession(5099, 'a' * 43, 'test-instance');
    transport.respondJson('/health', {
      'status': 'starting', 'engine': 'initialising', 'instance_id': 'test-instance',
    });

    final status = await supervisorWith().probe();

    expect(status.phase, BackendPhase.degraded);
    expect(status.detail, contains('initialising'));
  });

  test('engine output is captured for diagnostics only', () async {
    transport.handlers['/health'] = () => _jsonResponse(jsonEncode({...loadFixture('health'), 'instance_id': 'test-instance'}));
    final process = FakeProcess();
    final supervisor = supervisorWith(
      runner: FakeRunner(process: process),
      locator: locatorFor(Platform.resolvedExecutable),
    );
    // Force a spawn by failing the adoption probe first.
    var first = true;
    transport.handlers['/health'] = () {
      if (first) {
        first = false;
        throw const SocketException('refused');
      }
      return _jsonResponse(jsonEncode({...loadFixture('health'), 'instance_id': 'test-instance'}));
    };

    await supervisor.start();
    process.stderrController.add(' * Running on http://127.0.0.1:5099\n'.codeUnits);
    await Future<void>.delayed(const Duration(milliseconds: 30));

    expect(supervisor.diagnosticLog.join('\n'), contains('Running on'));
    // Readiness came from /health, never from that line.
    expect(supervisor.status.phase, BackendPhase.ready);
  });

  test('stop requests termination and reports the exit code', () async {
    final process = FakeProcess();
    var first = true;
    transport.handlers['/health'] = () {
      if (first) {
        first = false;
        throw const SocketException('refused');
      }
      return _jsonResponse(jsonEncode({...loadFixture('health'), 'instance_id': 'test-instance'}));
    };
    final supervisor = supervisorWith(
      runner: FakeRunner(process: process),
      locator: locatorFor(Platform.resolvedExecutable),
    );
    await supervisor.start();

    final stopping = supervisor.stop(grace: const Duration(seconds: 1));
    await Future<void>.delayed(const Duration(milliseconds: 10));
    process.exitWith(0);
    await stopping;

    expect(process.terminated, isTrue);
    expect(process.killed, isFalse, reason: 'a cooperative exit must not be force-killed');
  });

  test('stop force-kills only after the grace period', () async {
    final process = FakeProcess();
    var first = true;
    transport.handlers['/health'] = () {
      if (first) {
        first = false;
        throw const SocketException('refused');
      }
      return _jsonResponse(jsonEncode({...loadFixture('health'), 'instance_id': 'test-instance'}));
    };
    final supervisor = supervisorWith(
      runner: FakeRunner(process: process),
      locator: locatorFor(Platform.resolvedExecutable),
    );
    await supervisor.start();

    await supervisor.stop(grace: const Duration(milliseconds: 40));

    expect(process.terminated, isTrue);
    expect(process.killed, isTrue);
  });

  test('restart refuses to kill an engine this client does not own', () async {
    api.establishSession(5099, 'a' * 43, 'test-instance');
    transport.respondJson('/health', {...loadFixture('health'), 'instance_id': 'test-instance'});
    final runner = FakeRunner(process: FakeProcess());
    final supervisor = supervisorWith(runner: runner);
    await supervisor.start();

    final status = await supervisor.restart();

    expect(status.failure!.kind, FailureKind.unsupportedCapability);
    expect(runner.starts, isEmpty);
  });

  test('an unexpected engine exit is surfaced, not hidden', () async {
    final process = FakeProcess();
    var first = true;
    transport.handlers['/health'] = () {
      if (first) {
        first = false;
        throw const SocketException('refused');
      }
      return _jsonResponse(jsonEncode({...loadFixture('health'), 'instance_id': 'test-instance'}));
    };
    final supervisor = supervisorWith(
      runner: FakeRunner(process: process),
      locator: locatorFor(Platform.resolvedExecutable),
    );
    await supervisor.start();

    process.exitWith(3);
    await Future<void>.delayed(const Duration(milliseconds: 20));

    expect(supervisor.status.phase, BackendPhase.stopped);
    expect(supervisor.status.exitCode, 3);
    expect(supervisor.status.detail, contains('exited unexpectedly'));
  });

  test('a launch failure is reported without a phantom process', () async {
    transport.fail('/health', const SocketException('refused'));
    final supervisor = supervisorWith(
      runner: FakeRunner(error: const ProcessException('jocky-backend', [], 'EACCES')),
      locator: locatorFor(Platform.resolvedExecutable),
    );

    final status = await supervisor.start();

    expect(status.phase, BackendPhase.unavailable);
    expect(status.failure!.message, contains('could not be launched'));
    expect(status.processId, isNull);
  });

  group('BackendLocator', () {
    test('searches bundle-relative paths for the platform executable name', () {
      final locator = locatorFor(null);
      final candidates = locator.candidatePaths();

      expect(candidates, isNotEmpty);
      expect(candidates.first, contains('/opt/jocky'));
      expect(
        candidates.first,
        endsWith(Platform.isWindows ? 'JOCKY-backend.exe' : 'jocky-backend'),
      );
    });

    test('an explicit override takes precedence over discovery', () {
      final locator = locatorFor('/custom/engine/jocky-backend');

      expect(locator.candidatePaths(), ['/custom/engine/jocky-backend']);
      expect(locator.resolve(exists: (path) => path == '/custom/engine/jocky-backend'),
          '/custom/engine/jocky-backend');
    });

    test('resolve returns null when no candidate exists', () {
      expect(locatorFor(null).resolve(exists: (_) => false), isNull);
    });
  });
}

http.Response _jsonResponse(String body) => http.Response(
      body,
      200,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );
