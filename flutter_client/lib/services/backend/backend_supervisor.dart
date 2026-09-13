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

/// Locates the packaged engine executable relative to the running application.
///
/// A release bundle carries the PyInstaller one-directory output at
/// `<bundle>/backend/`, put there by the `install()` rule in
/// `linux/CMakeLists.txt` and `windows/CMakeLists.txt` so that a plain
/// `flutter build` always produces a runnable application — the Linux install
/// step wipes the bundle on every build, so a copy made by a packaging script
/// alone does not survive the next build.
///
/// Developer runs fall back to the repository's `backend-dist/`, found by
/// walking up from the executable rather than by counting `../` segments: the
/// build directory sits at a different depth on Linux than on Windows, and the
/// hardcoded ascent this replaced pointed at a directory that never existed.
class BackendLocator {
  const BackendLocator({
    this.overridePath,
    this.resolveExecutableDir = _defaultDir,
    this.ancestorSearchDepth = 8,
  });

  final String? overridePath;
  final String Function() resolveExecutableDir;

  /// How far up from the executable the developer-layout search walks.
  final int ancestorSearchDepth;

  static String _defaultDir() => File(Platform.resolvedExecutable).parent.path;

  static String get executableName =>
      Platform.isWindows ? 'JOCKY-backend.exe' : 'jocky-backend';

  /// PyInstaller names its output directory after the executable, without the
  /// Windows extension.
  static String get distDirectoryName =>
      Platform.isWindows ? 'JOCKY-backend' : 'jocky-backend';

  static String _join(List<String> parts) => parts.join(Platform.pathSeparator);

  List<String> candidatePaths() {
    if (overridePath != null && overridePath!.isNotEmpty) return [overridePath!];
    final dir = resolveExecutableDir();
    final name = executableName;
    final candidates = <String>[
      // Release bundle: engine installed beside the Flutter executable.
      _join([dir, 'backend', name]),
      // The PyInstaller directory copied in whole rather than flattened.
      _join([dir, 'backend', distDirectoryName, name]),
      _join([dir, 'data', 'backend', name]),
    ];
    var ancestor = dir;
    for (var level = 0; level < ancestorSearchDepth; level++) {
      final parent = Directory(ancestor).parent.path;
      if (parent == ancestor) break;
      ancestor = parent;
      candidates.add(_join([ancestor, 'backend-dist', distDirectoryName, name]));
    }
    return candidates;
  }

  /// Returns the first candidate that is a runnable file, or null. Existence is
  /// checked through [exists] so tests do not need a real binary.
  String? resolve({bool Function(String path)? exists}) {
    final check = exists ?? isRunnable;
    for (final candidate in candidatePaths()) {
      if (check(candidate)) return candidate;
    }
    return null;
  }

  /// A file that exists but carries no execute bit is not the engine: launching
  /// it fails later with a much less obvious error, so reject it here where the
  /// reason can still be reported.
  static bool isRunnable(String path) {
    final file = File(path);
    if (!file.existsSync()) return false;
    if (Platform.isWindows) return true;
    return file.statSync().mode & 0x49 != 0;
  }

  /// Per-candidate verdict for the failure detail, so an operator is told why
  /// each location was rejected instead of only that nothing was found.
  String describeSearch() => candidatePaths().map((path) {
        if (Directory(path).existsSync()) return '$path (is a directory)';
        if (!File(path).existsSync()) return '$path (missing)';
        return isRunnable(path) ? '$path (found)' : '$path (not executable)';
      }).join('\n');
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

  /// Set when the engine reports `startup_error` over the bootstrap channel.
  /// Startup is then hopeless, so the readiness poll stops waiting for a health
  /// reply that will never come and reports the engine's own reason instead.
  String? _startupError;

  /// Last few stderr lines, used to explain an exit during startup. A crashing
  /// engine prints a traceback there and says nothing on the bootstrap channel.
  final List<String> _stderrTail = [];

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
    // The engine binds an OS-assigned port and announces it over the bootstrap
    // channel together with a per-process token, so without a session there is
    // no endpoint to probe and no credential to probe it with. Reporting a
    // connection failure against the placeholder origin would be a fabricated
    // error, and the periodic poll doing so is what buried the real startup
    // failure behind "No engine is listening on http://127.0.0.1:5000".
    if (!_api.hasSession) return _status;
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

    _startupError = null;
    _stderrTail.clear();
    _emit(_status.copyWith(phase: BackendPhase.resolving, clearFailure: true));
    final executable = _locator.resolve();
    if (executable == null) {
      final failure = JockyFailure(
        kind: FailureKind.backendUnavailable,
        message: 'The packaged forensic engine was not found next to this application. '
            'This build is incomplete: the bundle should contain '
            'backend/${BackendLocator.executableName}.',
        detail: 'searched:\n${_locator.describeSearch()}',
      );
      _emit(_status.copyWith(
        phase: BackendPhase.unavailable,
        failure: failure,
        detail: failure.message,
      ));
      return _status;
    }

    // No origin yet: the port is assigned by the OS at bind time and is only
    // known once the engine announces it, so claiming one here would be a guess.
    _emit(_status.copyWith(phase: BackendPhase.starting, executablePath: executable));

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
    process.stdout.transform(utf8.decoder).transform(const LineSplitter()).listen((line) {
      try {
        final message = jsonDecode(line) as Map<String, dynamic>;
        if (message['protocol'] != 1) throw const FormatException('Unsupported bootstrap protocol');
        if (message['event'] == 'ready') {
          _api.establishSession(int.parse('${message['port']}'), message['token'] as String, message['instance_id'] as String);
          _log('[lifecycle] authenticated bootstrap received; engine listening on ${_api.config.displayOrigin}');
        } else if (message['event'] == 'startup_error') {
          _startupError = _describeStartupError(message['error']);
          _log('[lifecycle] startup_error: $_startupError');
        }
      } on Object {
        _log('[lifecycle] invalid bootstrap message');
      }
    });

    process.stderr.transform(utf8.decoder).transform(const LineSplitter()).listen(
      (line) {
        if (line.trim().isEmpty) return;
        _log('[err] $line');
        _stderrTail.add(line);
        if (_stderrTail.length > 12) _stderrTail.removeAt(0);
      },
      onError: (Object error) => _log('[err] stream error: $error'),
      cancelOnError: false,
    );

    unawaited(process.exitCode.then((code) {
      _log('[lifecycle] engine exited with code $code');
      _process = null;
      // The token belonged to that process; presenting it to the next one would
      // only produce 401s, and adopting a dead session would hide the exit.
      _api.clearSession();
      if (_status.phase == BackendPhase.stopping) {
        _emit(_status.copyWith(phase: BackendPhase.stopped, exitCode: code));
        return;
      }
      final reason = _startupError ??
          (_stderrTail.isEmpty ? null : _stderrTail.last);
      _emit(_status.copyWith(
        phase: BackendPhase.stopped,
        exitCode: code,
        failure: JockyFailure(
          kind: FailureKind.backendUnavailable,
          message: 'The engine process exited unexpectedly with code $code.',
          detail: reason,
        ),
        detail: reason == null
            ? 'The engine process exited unexpectedly with code $code.'
            : 'The engine process exited unexpectedly with code $code: $reason',
      ));
    }));
  }

  /// The engine reports a structured error object; fall back to its raw form
  /// rather than dropping a cause we cannot parse.
  static String _describeStartupError(Object? error) {
    if (error is Map) {
      final message = error['message'];
      final type = error['type'];
      if (message != null) return type == null ? '$message' : '$message ($type)';
    }
    return error == null ? 'the engine reported a startup failure' : '$error';
  }

  /// Polls `/health` until the engine is ready or the startup deadline passes.
  Future<BackendStatus> waitForReady({Duration? timeout}) async {
    final deadline = DateTime.now().add(timeout ?? _config.startupTimeout);
    JockyFailure? last;

    while (DateTime.now().isBefore(deadline)) {
      if (_status.phase == BackendPhase.stopped && _process == null && _status.managedByClient) {
        // The engine exited; the exit handler already recorded the code and the
        // reason it printed. Falling through to the deadline below would
        // replace that precise cause with a vague "did not become ready".
        return _status;
      }
      // The engine said it cannot start. Waiting out the deadline would only
      // replace its specific reason with a generic timeout.
      if (_startupError != null) {
        final failure = JockyFailure(
          kind: FailureKind.backendUnavailable,
          message: 'The forensic engine could not start: $_startupError',
          detail: _stderrTail.isEmpty ? null : _stderrTail.join('\n'),
        );
        _emit(_status.copyWith(
          phase: BackendPhase.unavailable,
          failure: failure,
          detail: failure.message,
        ));
        return _status;
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
            // Only now is the endpoint known: the engine chose the port and
            // announced it, so this is where the UI learns the real origin.
            origin: _api.config.displayOrigin,
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
          detail: _stderrTail.isEmpty ? null : _stderrTail.join('\n'),
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
    _api.clearSession();
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
