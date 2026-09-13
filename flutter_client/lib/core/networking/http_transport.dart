import 'dart:async';

import 'package:http/http.dart' as http;

/// Minimal transport seam so the API client can be driven by fixtures in tests
/// without mocking away request construction, status handling or decoding.
abstract class HttpTransport {
  Future<http.Response> get(Uri uri, {Map<String, String>? headers, Duration? timeout});

  Future<http.Response> post(
    Uri uri, {
    Map<String, String>? headers,
    Object? body,
    Duration? timeout,
  });

  void close();
}

class HttpClientTransport implements HttpTransport {
  HttpClientTransport([http.Client? client]) : _client = client ?? http.Client();

  final http.Client _client;

  @override
  Future<http.Response> get(Uri uri, {Map<String, String>? headers, Duration? timeout}) {
    final request = _client.get(uri, headers: headers);
    return timeout == null ? request : request.timeout(timeout);
  }

  @override
  Future<http.Response> post(
    Uri uri, {
    Map<String, String>? headers,
    Object? body,
    Duration? timeout,
  }) {
    final request = _client.post(uri, headers: headers, body: body);
    return timeout == null ? request : request.timeout(timeout);
  }

  @override
  void close() => _client.close();
}
