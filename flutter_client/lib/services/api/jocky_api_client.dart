import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import '../../core/config/app_config.dart';
import '../../core/errors/failure.dart';
import '../../core/networking/http_transport.dart';
import '../../core/utils/json.dart';
import '../../models/commands/command_reference.dart';
import '../../models/commands/command_response.dart';
import '../../models/health/backend_health.dart';
import '../../models/reports/report.dart';

/// Authenticated local API client. Python owns parsing, collection and results.
class JockyApiClient {
  JockyApiClient({required this._config, required this._transport});

  AppConfig _config;
  String? _token;
  String? _instance;
  String? activeCaseId;
  bool get hasSession => _token != null;

  void establishSession(int port, String token, String instance) {
    if (port < 1 || port > 65535 || token.length < 32 || instance.isEmpty) {
      throw const FormatException("Invalid backend bootstrap");
    }
    _config = _config.copyWith(host: "127.0.0.1", port: port);
    _token = token;
    _instance = instance;
  }

  /// Forgets the bootstrap session. The token and instance id belong to one
  /// engine process, so once that process is gone they must not be presented to
  /// its replacement, and a dead session must not be mistaken for an adoptable
  /// engine. The port is left in place purely as a diagnostic record of where
  /// the last engine was listening.
  void clearSession() {
    _token = null;
    _instance = null;
    activeCaseId = null;
  }
  final HttpTransport _transport;

  AppConfig get config => _config;

  Map<String, String> get _jsonHeaders => {
    'Content-Type': 'application/json; charset=utf-8',
    if (_token != null) 'Authorization': 'Bearer $_token',
    'X-Jocky-Instance': ?_instance,
  };

  Future<http.Response> request(String path, {Map<String, dynamic>? body}) async {
    final response = await _send(() => body == null
      ? _transport.get(_config.endpoint(path), headers: _jsonHeaders, timeout: _config.requestTimeout)
      : _transport.post(_config.endpoint(path), headers: _jsonHeaders, body: jsonEncode(body), timeout: const Duration(minutes: 2)), operation: path);
    if (response.statusCode >= 400) {
      final data = _decodeObject(response, operation: path);
      throw JockyFailure(kind: FailureKind.execution, message: data['error'] is Map ? '${data['error']['message']}' : '${data['error']}', httpStatus: response.statusCode);
    }
    return response;
  }

  Future<Map<String, dynamic>> jsonRequest(String path, {Map<String, dynamic>? body}) async =>
    _decodeObject(await request(path, body: body), operation: path);

  /// Probe used both by the readiness poll and by the supervisor's startup wait.
  Future<BackendHealth> health({Duration? timeout}) async {
    final response = await _send(
      () => _transport.get(
        _config.endpoint('/health'),
        headers: _jsonHeaders,
        timeout: timeout ?? _config.healthTimeout,
      ),
      operation: 'health',
    );
    final body = _decodeObject(response, operation: 'health');
    if (response.statusCode != 200) {
      throw JockyFailure(
        kind: FailureKind.backendUnavailable,
        message: 'The engine answered /health with HTTP ${response.statusCode}.',
        httpStatus: response.statusCode,
      );
    }
    if (_instance != null && body['instance_id'] != _instance) {
      throw const JockyFailure(kind: FailureKind.backendUnavailable, message: 'Health response belongs to an unexpected backend instance.');
    }
    return BackendHealth.fromJson(body);
  }

  /// The command reference is backend-owned; the client never hardcodes syntax.
  Future<CommandReference> commandReference() async {
    final response = await _send(
      () => _transport.get(_config.endpoint('/commands'), headers: _jsonHeaders, timeout: _config.requestTimeout),
      operation: 'commands',
    );
    if (response.statusCode != 200) {
      throw JockyFailure(
        kind: FailureKind.backendUnavailable,
        message: 'The engine answered /commands with HTTP ${response.statusCode}.',
        httpStatus: response.statusCode,
      );
    }
    return CommandReference.fromJson(_decodeObject(response, operation: 'commands'));
  }

  /// Submits raw command text. Parsing and validation belong to the backend;
  /// this method performs no syntax inspection of its own.
  ///
  /// [cancellation], when completed, abandons the client's wait. The backend
  /// has no cancellation endpoint, so the run may still finish server-side —
  /// callers must surface that, not claim the work was stopped.
  Future<CommandResponse> executeCommand(
    String commandText, {
    Duration? timeout,
    Future<void>? cancellation,
  }) async {
    final request = _send(
      () => _transport.post(
        _config.endpoint('/command'),
        headers: _jsonHeaders,
        body: jsonEncode({'command': commandText, if (activeCaseId != null) 'investigation_id': activeCaseId}),
        timeout: timeout ?? _config.requestTimeout,
      ),
      operation: 'command',
    );

    final http.Response response;
    if (cancellation == null) {
      response = await request;
    } else {
      final cancelled = cancellation.then((_) => null);
      final winner = await Future.any<http.Response?>([request, cancelled]);
      if (winner == null) {
        throw const JockyFailure(
          kind: FailureKind.cancelled,
          message: 'The request was abandoned by this client before the engine replied.',
        );
      }
      response = winner;
    }

    final body = _decodeObject(response, operation: 'command');
    final report = ForensicReport.fromJson(asMapOrNull(body['report']));

    if (response.statusCode == 200 && asStringOrNull(body['status']) == 'success') {
      return CommandResponse.fromJson(body);
    }
    throw _failureFromCommandBody(body, response.statusCode, report);
  }

  JockyFailure _failureFromCommandBody(
    Map<String, dynamic> body,
    int statusCode,
    ForensicReport? report,
  ) {
    final code = asStringOrNull(body['error_code']);
    final kindLabel = asStringOrNull(body['error_kind']);
    final message = asStringOrNull(body['error']) ??
        'The engine reported a failure without a message (HTTP $statusCode).';

    final kind = switch (kindLabel) {
      'parser' => FailureKind.commandSyntax,
      'validation' => FailureKind.commandValidation,
      'execution' => FailureKind.execution,
      'internal' => FailureKind.backendInternal,
      _ => statusCode >= 500 ? FailureKind.backendInternal : FailureKind.execution,
    };

    return JockyFailure(
      kind: kind,
      message: message,
      code: code,
      httpStatus: statusCode,
      report: report,
    );
  }

  Future<http.Response> _send(
    Future<http.Response> Function() action, {
    required String operation,
  }) async {
    try {
      return await action();
    } on TimeoutException {
      throw JockyFailure(
        kind: FailureKind.timeout,
        message: 'The engine did not answer /$operation within the configured deadline.',
        detail: 'endpoint=/$operation origin=${_config.displayOrigin}',
      );
    } on SocketException catch (error) {
      throw JockyFailure(
        kind: FailureKind.backendUnavailable,
        message: 'No engine is listening on ${_config.displayOrigin}.',
        detail: 'endpoint=/$operation os_error=${error.osError?.message ?? error.message}',
      );
    } on http.ClientException catch (error) {
      throw JockyFailure(
        kind: FailureKind.backendUnavailable,
        message: 'The connection to ${_config.displayOrigin} failed.',
        detail: 'endpoint=/$operation client_error=${error.message}',
      );
    }
  }

  Map<String, dynamic> _decodeObject(http.Response response, {required String operation}) {
    final Object? decoded;
    try {
      decoded = jsonDecode(utf8.decode(response.bodyBytes));
    } on FormatException catch (error) {
      throw JockyFailure(
        kind: FailureKind.malformedResponse,
        message: 'The engine response to /$operation was not valid JSON.',
        httpStatus: response.statusCode,
        detail: error.message,
      );
    }
    if (decoded is! Map) {
      throw JockyFailure(
        kind: FailureKind.malformedResponse,
        message: 'The engine response to /$operation was not a JSON object.',
        httpStatus: response.statusCode,
      );
    }
    return asMap(decoded);
  }
}
