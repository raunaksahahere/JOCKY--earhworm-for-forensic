import '../../core/utils/json.dart';

/// Authenticated backend readiness; unknown optional fields remain in raw.
class BackendHealth {
  const BackendHealth({
    required this.status,
    required this.engine,
    required this.observedAt,
    required this.raw,
  });

  final String status;
  final String engine;
  final DateTime observedAt;
  final Map<String, dynamic> raw;

  bool get engineOnline => engine == 'online' && raw['ready'] != false;

  factory BackendHealth.fromJson(Map<String, dynamic> json, {DateTime? observedAt}) =>
      BackendHealth(
        status: asString(json['status'], fallback: 'unknown'),
        engine: asString(json['engine'], fallback: 'unknown'),
        observedAt: observedAt ?? DateTime.now(),
        raw: json,
      );
}
