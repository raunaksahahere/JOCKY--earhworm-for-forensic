import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:jocky_client/core/config/app_config.dart';
import 'package:jocky_client/core/errors/failure.dart';
import 'package:jocky_client/models/results/analysis_result.dart';
import 'package:jocky_client/models/results/integrity.dart';
import 'package:jocky_client/services/api/jocky_api_client.dart';

import '../support/fake_transport.dart';
import '../support/fixtures.dart';

void main() {
  late FakeTransport transport;
  late JockyApiClient api;

  setUp(() {
    transport = FakeTransport();
    api = JockyApiClient(
      config: const AppConfig(port: 5099, requestTimeout: Duration(milliseconds: 200)),
      transport: transport,
    );
  });

  group('GET /health', () {
    test('reports an online engine', () async {
      transport.respondJson('/health', loadFixture('health'));

      final health = await api.health();

      expect(health.engineOnline, isTrue);
      expect(health.status, 'JOCKY API is running');
      expect(transport.requests.single.uri.toString(), 'http://127.0.0.1:5099/health');
    });

    test('maps a refused connection to backendUnavailable', () async {
      transport.fail('/health', const SocketException('Connection refused'));

      final failure = await _failureOf(api.health());

      expect(failure.kind, FailureKind.backendUnavailable);
      expect(failure.message, contains('http://127.0.0.1:5099'));
    });

    test('maps a stalled engine to timeout', () async {
      transport.delay(
        '/health',
        const Duration(seconds: 5),
        http.Response('{}', 200),
      );

      final failure = await _failureOf(api.health(timeout: const Duration(milliseconds: 50)));

      expect(failure.kind, FailureKind.timeout);
    });

    test('treats a non-200 health reply as unavailable, not ready', () async {
      transport.respondJson('/health', {'status': 'down'}, status: 503);

      final failure = await _failureOf(api.health());

      expect(failure.kind, FailureKind.backendUnavailable);
      expect(failure.httpStatus, 503);
    });
  });

  group('GET /commands', () {
    test('parses the engine-published reference', () async {
      transport.respondJson('/commands', loadFixture('commands'));

      final reference = await api.commandReference();

      expect(reference.schemaVersion, 1);
      expect(reference.entries.map((e) => e.name),
          containsAll(['HASH', 'LIST FILES', 'SEARCH FILE', 'SYSTEM INFO', 'PROCESSES']));
      expect(reference.entries.first.syntax, 'HASH FILE <path>');
    });
  });

  group('POST /command — successful observations', () {
    test('hash result keeps nullable created and ledger comparison', () async {
      transport.respondJson('/command', loadFixture('hash'));

      final response = await api.executeCommand('HASH FILE x');
      final result = response.result;

      expect(result, isA<HashResult>());
      final hash = result as HashResult;
      expect(hash.algorithm, 'SHA256');
      expect(hash.digest, hasLength(64));
      // Linux ext4 exposes no birth time; the engine reports null and the model
      // must not substitute another timestamp.
      expect(hash.created, isNull);
      expect(hash.metadataChanged, isNotNull);
      expect(hash.integrityHistory.status, isA<LedgerComparison>());
      expect(response.report!.reportId, startsWith('JCK-'));
      expect(response.normalizedCommand!.action, 'hash');
    });

    test('unicode paths survive the round trip unchanged', () async {
      final fixture = loadFixture('hash');
      transport.respondJson('/command', fixture);

      final response = await api.executeCommand('HASH FILE "नमूना evidence.bin"');
      final hash = response.result! as HashResult;

      expect(hash.absolutePath, contains('नमूना'));
      expect(response.normalizedCommand!.path, contains('नमूना'));
      // The client sends the command text verbatim, UTF-8 encoded.
      expect(transport.requests.single.body, contains('नमूना'));
    });

    test('process observations never turn null into zero', () async {
      transport.respondJson('/command', loadFixture('processes'));

      final result = (await api.executeCommand('PROCESSES')).result! as ProcessesResult;

      expect(result.processes, isNotEmpty);
      // The snapshot collector samples no interval, so every CPU reading is null.
      expect(result.processes.every((p) => p.cpuPercent == null), isTrue);
      expect(result.complete, isFalse);
      expect(
        result.warnings,
        contains('Per-process CPU percentage was not sampled; null means unavailable.'),
      );
    });

    test('list results expose truncation and skip counts', () async {
      transport.respondJson('/command', loadFixture('list'));

      final result = (await api.executeCommand('LIST FILES .')).result! as ListResult;

      expect(result.entries, isNotEmpty);
      expect(result.entryCount, isNotNull);
      expect(result.truncated, isFalse);
      expect(result.skippedCount, 0);
    });

    test('search results record the scanned count', () async {
      transport.respondJson('/command', loadFixture('search'));

      final result = (await api.executeCommand('SEARCH FILE a IN .')).result! as SearchResult;

      expect(result.searchTarget, 'evidence');
      expect(result.entriesScanned, isNotNull);
    });

    test('system info exposes nullable extended metrics', () async {
      transport.respondJson('/command', loadFixture('system'));

      final result = (await api.executeCommand('SYSTEM INFO')).result! as SystemInfoResult;

      expect(result.hostname, isNotEmpty);
      expect(result.cpuLogicalCores, isNotNull);
      expect(result.pythonRuntime, isNotEmpty);
    });
  });

  group('POST /command — rejections and failures', () {
    test('parser rejection maps to commandSyntax and keeps the engine message', () async {
      final fixture = loadFixture('syntax_error');
      transport.respondJson('/command', fixture, status: 400);

      final failure = await _failureOf(api.executeCommand('HASH FIL x'));

      expect(failure.kind, FailureKind.commandSyntax);
      expect(failure.code, 'invalid_syntax');
      expect(failure.message, contains('line 1, column 6'));
      // The engine issues a report even for malformed input; it must be kept.
      expect(failure.report, isNotNull);
      expect(failure.report!.status, 'failed');
      expect(failure.report!.normalizedCommand, isNull);
    });

    test('missing evidence maps to execution failure with not_found', () async {
      transport.respondJson('/command', loadFixture('notfound'), status: 400);

      final failure = await _failureOf(api.executeCommand('HASH FILE /nonexistent/zzz.bin'));

      expect(failure.kind, FailureKind.execution);
      expect(failure.code, 'not_found');
      // A failed execution still retains the successfully parsed command.
      expect(failure.report!.normalizedCommand!.action, 'hash');
    });

    test('unreadable directory maps to permission_denied', () async {
      transport.respondJson('/command', loadFixture('permission'), status: 400);

      final failure = await _failureOf(api.executeCommand('LIST FILES /root'));

      expect(failure.kind, FailureKind.execution);
      expect(failure.code, 'permission_denied');
    });

    test('HTTP 500 maps to backendInternal', () async {
      transport.respondJson(
        '/command',
        {
          'status': 'error',
          'command': 'HASH FILE x',
          'result': null,
          'report': null,
          'error': 'Internal command execution error',
          'error_code': 'internal_error',
          'error_kind': 'internal',
          'normalized_command': null,
        },
        status: 500,
      );

      final failure = await _failureOf(api.executeCommand('HASH FILE x'));

      expect(failure.kind, FailureKind.backendInternal);
      expect(failure.httpStatus, 500);
    });

    test('a non-JSON reply is reported as malformed, not as success', () async {
      transport.respondRaw('/command', '<html>proxy error</html>');

      final failure = await _failureOf(api.executeCommand('SYSTEM INFO'));

      expect(failure.kind, FailureKind.malformedResponse);
    });

    test('a JSON array reply is rejected rather than coerced', () async {
      transport.respondRaw('/command', '[1,2,3]');

      final failure = await _failureOf(api.executeCommand('SYSTEM INFO'));

      expect(failure.kind, FailureKind.malformedResponse);
    });

    test('a slow observation times out without inventing a result', () async {
      transport.delay(
        '/command',
        const Duration(seconds: 5),
        http.Response('{}', 200),
      );

      final failure = await _failureOf(
        api.executeCommand('PROCESSES', timeout: const Duration(milliseconds: 50)),
      );

      expect(failure.kind, FailureKind.timeout);
    });

    test('cancellation abandons the wait and reports it as abandoned', () async {
      transport.delay(
        '/command',
        const Duration(seconds: 5),
        http.Response('{}', 200),
      );
      final cancellation = Completer<void>();

      final pending = api.executeCommand(
        'PROCESSES',
        timeout: const Duration(seconds: 30),
        cancellation: cancellation.future,
      );
      cancellation.complete();

      final failure = await _failureOf(pending);
      expect(failure.kind, FailureKind.cancelled);
      // The client never claims the engine stopped working.
      expect(failure.remediation, contains('may have completed it anyway'));
    });
  });
}

Future<JockyFailure> _failureOf(Future<Object?> future) async {
  try {
    await future;
  } on JockyFailure catch (failure) {
    return failure;
  }
  fail('Expected a JockyFailure but the call succeeded');
}
