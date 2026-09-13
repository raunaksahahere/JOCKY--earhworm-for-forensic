/// Local session configuration. Production host/port come from authenticated bootstrap.
class AppConfig {
  const AppConfig({
    this.host = defaultHost,
    this.port = defaultPort,
    this.requestTimeout = const Duration(seconds: 20),
    this.healthTimeout = const Duration(seconds: 3),
    this.healthPollInterval = const Duration(seconds: 15),
    this.startupTimeout = const Duration(seconds: 30),
  });

  static const defaultHost = '127.0.0.1';
  static const defaultPort = 5000;

  /// Loopback only. The engine observes the local host; it is never a remote
  /// service, so the client refuses to be pointed at an arbitrary network host
  /// unless the operator changes it explicitly in Settings.
  final String host;
  final int port;
  final Duration requestTimeout;
  final Duration healthTimeout;
  final Duration healthPollInterval;
  final Duration startupTimeout;

  Uri get baseUri => Uri(scheme: 'http', host: host, port: port);

  Uri endpoint(String path) => baseUri.resolve(path);

  String get displayOrigin => 'http://$host:$port';

  AppConfig copyWith({String? host, int? port, Duration? requestTimeout}) => AppConfig(
        host: host ?? this.host,
        port: port ?? this.port,
        requestTimeout: requestTimeout ?? this.requestTimeout,
        healthTimeout: healthTimeout,
        healthPollInterval: healthPollInterval,
        startupTimeout: startupTimeout,
      );
}

/// Identity of this client build, shown in Settings and stamped into exports.
abstract final class ClientBuild {
  static const name = 'JOCKY Forensic Workstation';
  static const version = '0.3.0';

  /// Command schema this client was written against (`compiler/commands.py`).
  static const supportedCommandSchema = 1;

  /// Report schema this client renders (`reports/report.py`).
  static const supportedReportSchema = 1;
}
