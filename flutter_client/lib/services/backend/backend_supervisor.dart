import 'dart:async';
import 'dart:io';
import 'dart:convert';

import '../../core/config/app_config.dart';
import '../../core/errors/failure.dart';
import '../api/jocky_api_client.dart';

/// Lifecycle phase of the local forensic engine, as observed by this client.
enum BackendPhase {
  /// Nothing attempted yet.
  idle,

  /// Looking for the packaged engine executable.
  resolving,

  /// Process spawned, waiting for `/health` to answer.
  starting,

  /// `/health` answered 200 and reported an online engine.
  ready,

  /// Reachable but not answering the way a JOCKY engine should.
  degraded,

  /// Not reachable.
  unavailable,

  /// Shutdown requested by this client.
  stopping,

  /// Process exited.
  stopped,
}

class BackendStatus {
  const BackendStatus({
    required this.phase,
    this.detail,
    this.failure,
    this.executablePath,
    this.processId,
    this.origin,
    this.lastHealthyAt,
    this.exitCode,
    this.managedByClient = false,
  });

  final BackendPhase phase;
  final String? detail;
  final JockyFailure? failure;
  final String? executablePath;
  final int? processId;
  final String? origin;
  final DateTime? lastHealthyAt;
  final int? exitCode;

  /// True only when this client spawned the process. When false the engine was
  /// started outside the app and must not be reported as client-managed.
  final bool managedByClient;

  bool get isReady => phase == BackendPhase.ready;

  static const unknown = BackendStatus(phase: BackendPhase.idle);

  BackendStatus copyWith({
    BackendPhase? phase,
    String? detail,
    JockyFailure? failure,
    bool clearFailure = false,
    String? executablePath,
    int? processId,
    String? origin,
    DateTime? lastHealthyAt,
    int? exitCode,
    bool? managedByClient,
  }) =>
      BackendStatus(
        phase: phase ?? this.phase,
        detail: detail ?? this.detail,
        failure: clearFailure ? null : (failure ?? this.failure),
        executablePath: executablePath ?? this.executablePath,
        processId: processId ?? this.processId,
        origin: origin ?? this.origin,
        lastHealthyAt: lastHealthyAt ?? this.lastHealthyAt,
        exitCode: exitCode ?? this.exitCode,
        managedByClient: managedByClient ?? this.managedByClient,
      );
}

/// Spawns processes. Extracted so supervisor behaviour is testable without
/// launching a real engine.
abstract class ProcessRunner {
  Future<ManagedProcess> start(
    String executable,
    List<String> arguments, {
    required Map<String, String> environment,
    String? workingDirectory,
  });
}

abstract class ManagedProcess {
  int get pid;
  Future<int> get exitCode;
  Stream<List<int>> get stdout;
  Stream<List<int>> get stderr;
  bool terminate();
  bool kill();
}

class _OsProcess implements ManagedProcess {
  _OsProcess(this._process);

  final Process _process;

  @override
  int get pid => _process.pid;
  @override
  Future<int> get exitCode => _process.exitCode;
  @override
  Stream<List<int>> get stdout => _process.stdout;
  @override
  Stream<List<int>> get stderr => _process.stderr;
  @override
  bool terminate() => _process.kill(ProcessSignal.sigterm);
  @override
  bool kill() => _process.kill(ProcessSignal.sigkill);
}

class OsProcessRunner implements ProcessRunner {
  const OsProcessRunner();

  @override
  Future<ManagedProcess> start(
    String executable,
    List<String> arguments, {
    required Map<String, String> environment,
    String? workingDirectory,
  }) async {
    final process = await Process.start(
      executable,
      arguments,
      environment: environment,
      workingDirectory: workingDirectory,
      runInShell: false,
    );
    return _OsProcess(process);
  }
}

/// Locates the packaged engine executable next to the Flutter bundle.
///
/// Linux: `<bundle>/data/flutter_assets/../backend/jocky-backend`
/// alongside `bundle/backend/jocky-backend`.
/// Windows: `<bundle>\backend\JOCKY-backend.exe`, matching the layout the
/// existing Electron packaging produces.
class BackendLocator {
  const BackendLocator({this.overridePath, this.resolveExecutableDir = _defaultDir});

  final String? overridePath;
  final String Function() resolveExecutableDir;

  static String _defaultDir() => File(Platform.resolvedExecutable).parent.path;

  static String get executableName =>
      Platform.isWindows ? 'JOCKY-backend.exe' : 'jocky-backend';

  List<String> candidatePaths() {
    if (overridePath != null && overridePath!.isNotEmpty) return [overridePath!];
    final dir = resolveExecutableDir();
    final name = executableName;
    return [
      // Release bundle layouts.
      '$dir${Platform.pathSeparator}backend${Platform.pathSeparator}$name',
      '$dir${Platform.pathSeparator}data${Platform.pathSeparator}backend${Platform.pathSeparator}$name',
      // Developer layout: PyInstaller output inside the repository.
      '$dir${Platform.pathSeparator}..${Platform.pathSeparator}..${Platform.pathSeparator}..'
          '${Platform.pathSeparator}..${Platform.pathSeparator}desktop'
          '${Platform.pathSeparator}backend-dist${Platform.pathSeparator}$name',
    ];
  }

  /// Returns the first candidate that exists, or null. Existence is checked
  /// through [exists] so tests do not need a real binary.
  String? resolve({bool Function(String path)? exists}) {
    final check = exists ?? (path) => File(path).existsSync();
    for (final candidate in candidatePaths()) {
      if (check(candidate)) return candidate;
    }
    return null;
  }
}

/// SQLite-backed local workstation contract; see contracts/CLIENT.md.
class BackendSupervisor {
  BackendSupervisor({
    required this._config,
    required this._api,
    this._runner = const OsProcessRunner(),
    this._locator = const BackendLocator(),
    this._probeInterval = const Duration(milliseconds: 300),
    this.workspace,
  });

  final String? workspace;
  final AppConfig _config;
  final JockyApiClient _api;
  final ProcessRunner _runner;
  final BackendLocator _locator;
  final Duration _probeInterval;

  final _controller = StreamController<BackendStatus>.broadcast();
  final List<String> _diagnosticLog = [];

  ManagedProcess? _process;
  BackendStatus _status = BackendStatus.unknown;

  Stream<BackendStatus> get statusStream => _controller.stream;
  BackendStatus get status => _status;

  /// Captured engine output, newest last. Diagnostics only.
  List<String> get diagnosticLog => List.unmodifiable(_diagnosticLog);

  void _emit(BackendStatus next) {
    _status = next;
    if (!_controller.isClosed) _controller.add(next);
  }

  void _log(String line) {
    _diagnosticLog.add(line);
    if (_diagnosticLog.length > 500) _diagnosticLog.removeRange(0, 100);
  }

  /// Checks whether an engine is already answering, without spawning anything.
  /// Used at startup so an engine started outside the app is adopted rather
  /// than duplicated.
  Future<BackendStatus> probe() async {
    try {
      final health = await _api.health();
      if (!health.engineOnline) {
        _emit(_status.copyWith(
          phase: BackendPhase.degraded,
          origin: _api.config.displayOrigin,
          detail: 'The engine answered /health but reported "${health.engine}".',
          clearFailure: true,
        ));
        return _status;
      }
      _emit(_status.copyWith(
        phase: BackendPhase.ready,
        origin: _api.config.displayOrigin,
        lastHealthyAt: health.observedAt,
        detail: health.status,
        clearFailure: true,
      ));
    } on JockyFailure catch (failure) {
      _emit(_status.copyWith(
        phase: BackendPhase.unavailable,
        origin: _api.config.displayOrigin,
        failure: failure,
        detail: failure.message,
      ));
    }
    return _status;
  }

  /// Starts the packaged engine and waits for readiness.
  ///
  /// If an engine is already answering on the configured origin, this adopts it
  /// instead of spawning a second one.
  Future<BackendStatus> start() async {
    if (_process != null) return _status;

    final adopted = _api.hasSession ? await probe() : BackendStatus.unknown;
    if (adopted.isReady) {
      _emit(_status.copyWith(
        managedByClient: false,
        detail: 'Adopted an engine already listening on ${_config.displayOrigin}.',
      ));
      return _status;
    }

    _emit(_status.copyWith(phase: BackendPhase.resolving, clearFailure: true));
    final executable = _locator.resolve();
    if (executable == null) {
      final failure = JockyFailure(
        kind: FailureKind.backendUnavailable,
        message: 'The packaged forensic engine was not found next to this application.',
        detail: 'searched: ${_locator.candidatePaths().join(', ')}',
      );
      _emit(_status.copyWith(
        phase: BackendPhase.unavailable,
        failure: failure,
        detail: failure.message,
      ));
      return _status;
    }

    _emit(_status.copyWith(
      phase: BackendPhase.starting,
      executablePath: executable,
      origin: _api.config.displayOrigin,
    ));

    try {
      final process = await _runner.start(
        executable,
        [if (workspace != null) ...['--workspace', workspace!]],
        environment: {
          'JOCKY_HOST': '127.0.0.1',
        },
        workingDirectory: File(executable).parent.path,
      );
      _process = process;
      _attachDiagnostics(process);
      _emit(_status.copyWith(processId: process.pid, managedByClient: true));
    } on Object catch (error) {
      final failure = JockyFailure(
        kind: FailureKind.backendUnavailable,
        message: 'The forensic engine process could not be launched.',
        detail: '$error',
      );
      _emit(_status.copyWith(
        phase: BackendPhase.unavailable,
        failure: failure,
        detail: failure.message,
      ));
      return _status;
    }

    return waitForReady();
  }

  void _attachDiagnostics(ManagedProcess process) {
    void consume(Stream<List<int>> stream, String channel) {
      stream.listen(
        (chunk) {
          final text = String.fromCharCodes(chunk).trimRight();
          if (text.isNotEmpty) _log('[$channel] $text');
        },
        onError: (Object error) => _log('[$channel] stream error: $error'),
        cancelOnError: false,
      );
    }

    process.stdout.transform(utf8.decoder).transform(const LineSplitter()).listen((line) {
      try {
        final message = jsonDecode(line) as Map<String, dynamic>;
        if (message['protocol'] != 1) throw const FormatException('Unsupported bootstrap protocol');
        if (message['event'] == 'ready') {
          _api.establishSession(int.parse('${message['port']}'), message['token'] as String, message['instance_id'] as String);
          _log('[lifecycle] authenticated bootstrap received');
        } else if (message['event'] == 'startup_error') {
          _log('[lifecycle] startup failed; check workspace permissions, storage and active sessions');
        }
      } on Object {
        _log('[lifecycle] invalid bootstrap message');
      }
    });
    consume(process.stderr, 'err');

    unawaited(process.exitCode.then((code) {
      _log('[lifecycle] engine exited with code $code');
      _process = null;
      if (_status.phase != BackendPhase.stopping) {
        _emit(_status.copyWith(
          phase: BackendPhase.stopped,
          exitCode: code,
          detail: 'The engine process exited unexpectedly with code $code.',
        ));
      } else {
        _emit(_status.copyWith(phase: BackendPhase.stopped, exitCode: code));
      }
    }));
  }

  /// Polls `/health` until the engine is ready or the startup deadline passes.
  Future<BackendStatus> waitForReady({Duration? timeout}) async {
    final deadline = DateTime.now().add(timeout ?? _config.startupTimeout);
    JockyFailure? last;

    while (DateTime.now().isBefore(deadline)) {
      if (_status.phase == BackendPhase.stopped && _process == null && _status.managedByClient) {
        break;
      }
      try {
        if (!_api.hasSession) {
          await Future<void>.delayed(_probeInterval);
          continue;
        }
        final health = await _api.health();
        if (health.engineOnline) {
          _emit(_status.copyWith(
            phase: BackendPhase.ready,
            lastHealthyAt: health.observedAt,
            detail: health.status,
            clearFailure: true,
          ));
          return _status;
        }
        last = JockyFailure(
          kind: FailureKind.backendUnavailable,
          message: 'The engine reported status "${health.engine}" instead of online.',
        );
      } on JockyFailure catch (failure) {
        last = failure;
      }
      await Future<void>.delayed(_probeInterval);
    }

    final failure = last ??
        JockyFailure(
          kind: FailureKind.timeout,
          message: 'The engine did not become ready within '
              '${(timeout ?? _config.startupTimeout).inSeconds}s.',
        );
    _emit(_status.copyWith(
      phase: _process == null ? BackendPhase.unavailable : BackendPhase.degraded,
      failure: failure,
      detail: failure.message,
    ));
    return _status;
  }

  /// Graceful shutdown: request termination, then force-kill only if the
  /// process is still alive after [grace]. Avoids orphaned engines.
  Future<void> stop({Duration grace = const Duration(seconds: 5)}) async {
    final process = _process;
    if (process == null) {
      if (_status.managedByClient) _emit(_status.copyWith(phase: BackendPhase.stopped));
      return;
    }
    _emit(_status.copyWith(phase: BackendPhase.stopping));
    try {
      await _api.jsonRequest('/api/v1/shutdown', body: {});
    } on Object {
      process.terminate();
    }
    try {
      await process.exitCode.timeout(grace);
    } on TimeoutException {
      _log('[lifecycle] engine did not exit within ${grace.inSeconds}s; forcing');
      process.kill();
      await process.exitCode;
    }
    _process = null;
  }

  /// Restart after a controlled failure. Refuses to restart an engine this
  /// client does not own, since killing an externally started engine would
  /// destroy another operator's session.
  Future<BackendStatus> restart() async {
    if (!_status.managedByClient && _process == null) {
      final failure = JockyFailure(
        kind: FailureKind.unsupportedCapability,
        message: 'This engine was not started by the application and will not be restarted by it.',
      );
      _emit(_status.copyWith(failure: failure, detail: failure.message));
      return _status;
    }
    await stop();
    _emit(BackendStatus(
      phase: BackendPhase.idle,
      executablePath: _status.executablePath,
      origin: _status.origin,
    ));
    return start();
  }

  Future<void> dispose() async {
    await stop();
    await _controller.close();
  }
}
