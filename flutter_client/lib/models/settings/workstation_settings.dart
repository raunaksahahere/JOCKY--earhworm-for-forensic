import '../../core/config/app_config.dart';
import '../../core/utils/json.dart';

/// Desktop client preferences. Nothing here reconfigures the engine's forensic
/// behaviour — only how this workstation connects to it and displays results.
class WorkstationSettings {
  const WorkstationSettings({
    this.portableWorkspace,
    this.host = AppConfig.defaultHost,
    this.port = AppConfig.defaultPort,
    this.displayUtc = true,
    this.textScale = 1.0,
    this.requestTimeoutSeconds = 20,
    this.healthPollSeconds = 15,
    this.exportDirectory,
    this.backendExecutableOverride,
    this.autoStartBackend = true,
    this.denseTables = true,
  });

  final String? portableWorkspace;
  final String host;
  final int port;

  /// Forensic timestamps default to UTC. Local time is opt-in and always
  /// labelled with its offset.
  final bool displayUtc;
  final double textScale;
  final int requestTimeoutSeconds;
  final int healthPollSeconds;
  final String? exportDirectory;

  /// Explicit path to the packaged engine, for non-standard deployments.
  final String? backendExecutableOverride;
  final bool autoStartBackend;
  final bool denseTables;

  static const defaults = WorkstationSettings();

  AppConfig toConfig() => AppConfig(
        host: host,
        port: port,
        requestTimeout: Duration(seconds: requestTimeoutSeconds),
        healthPollInterval: Duration(seconds: healthPollSeconds),
      );

  WorkstationSettings copyWith({
    String? portableWorkspace,
    bool clearPortableWorkspace = false,
    String? host,
    int? port,
    bool? displayUtc,
    double? textScale,
    int? requestTimeoutSeconds,
    int? healthPollSeconds,
    String? exportDirectory,
    bool clearExportDirectory = false,
    String? backendExecutableOverride,
    bool clearBackendOverride = false,
    bool? autoStartBackend,
    bool? denseTables,
  }) =>
      WorkstationSettings(
        portableWorkspace: clearPortableWorkspace ? null : (portableWorkspace ?? this.portableWorkspace),
        host: host ?? this.host,
        port: port ?? this.port,
        displayUtc: displayUtc ?? this.displayUtc,
        textScale: textScale ?? this.textScale,
        requestTimeoutSeconds: requestTimeoutSeconds ?? this.requestTimeoutSeconds,
        healthPollSeconds: healthPollSeconds ?? this.healthPollSeconds,
        exportDirectory:
            clearExportDirectory ? null : (exportDirectory ?? this.exportDirectory),
        backendExecutableOverride: clearBackendOverride
            ? null
            : (backendExecutableOverride ?? this.backendExecutableOverride),
        autoStartBackend: autoStartBackend ?? this.autoStartBackend,
        denseTables: denseTables ?? this.denseTables,
      );

  Map<String, dynamic> toJson() => {
        'portable_workspace': portableWorkspace,
        'host': host,
        'port': port,
        'display_utc': displayUtc,
        'text_scale': textScale,
        'request_timeout_seconds': requestTimeoutSeconds,
        'health_poll_seconds': healthPollSeconds,
        'export_directory': exportDirectory,
        'backend_executable_override': backendExecutableOverride,
        'auto_start_backend': autoStartBackend,
        'dense_tables': denseTables,
      };

  factory WorkstationSettings.fromJson(Map<String, dynamic> json) => WorkstationSettings(
        portableWorkspace: asStringOrNull(json['portable_workspace']),
        host: asString(json['host'], fallback: AppConfig.defaultHost),
        port: asIntOrNull(json['port']) ?? AppConfig.defaultPort,
        displayUtc: asBool(json['display_utc'], fallback: true),
        textScale: (asDoubleOrNull(json['text_scale']) ?? 1.0).clamp(0.8, 1.6),
        requestTimeoutSeconds: asIntOrNull(json['request_timeout_seconds']) ?? 20,
        healthPollSeconds: asIntOrNull(json['health_poll_seconds']) ?? 15,
        exportDirectory: asStringOrNull(json['export_directory']),
        backendExecutableOverride: asStringOrNull(json['backend_executable_override']),
        autoStartBackend: asBool(json['auto_start_backend'], fallback: true),
        denseTables: asBool(json['dense_tables'], fallback: true),
      );
}
