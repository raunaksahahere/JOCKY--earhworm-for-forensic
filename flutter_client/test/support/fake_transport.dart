import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:jocky_client/core/networking/http_transport.dart';

/// Scriptable transport. Requests are recorded so tests can assert what the
/// client actually sent, and responses are supplied per endpoint.
class FakeTransport implements HttpTransport {
  FakeTransport();

  final List<({String method, Uri uri, Object? body})> requests = [];

  /// Endpoint path -> response builder. The builder may throw to simulate
  /// transport failures (SocketException, TimeoutException).
  final Map<String, FutureOr<http.Response> Function()> handlers = {};

  bool closed = false;

  void respondJson(String path, Map<String, dynamic> body, {int status = 200}) {
    handlers[path] = () => http.Response(
          jsonEncode(body),
          status,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
  }

  void respondRaw(String path, String body, {int status = 200}) {
    handlers[path] = () => http.Response(body, status);
  }

  void fail(String path, Object error) {
    handlers[path] = () => throw error;
  }

  void delay(String path, Duration duration, http.Response response) {
    handlers[path] = () => Future.delayed(duration, () => response);
  }

  @override
  Future<http.Response> get(Uri uri, {Map<String, String>? headers, Duration? timeout}) =>
      _dispatch('GET', uri, null, timeout);

  @override
  Future<http.Response> post(
    Uri uri, {
    Map<String, String>? headers,
    Object? body,
    Duration? timeout,
  }) =>
      _dispatch('POST', uri, body, timeout);

  Future<http.Response> _dispatch(
    String method,
    Uri uri,
    Object? body,
    Duration? timeout,
  ) {
    requests.add((method: method, uri: uri, body: body));
    final handler = handlers[uri.path];
    if (handler == null) {
      return Future.value(http.Response('{"error":"no handler"}', 404));
    }
    final result = Future<http.Response>.sync(handler);
    return timeout == null ? result : result.timeout(timeout);
  }

  @override
  void close() => closed = true;
}
