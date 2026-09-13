/// Defensive JSON readers.
///
/// The backend is the source of truth, but a forensic client must never turn
/// a missing or unexpected value into a fabricated one. Every reader returns
/// null rather than a substitute when the value is absent or the wrong type.
library;

Map<String, dynamic> asMap(Object? value) =>
    value is Map ? value.map((k, v) => MapEntry(k.toString(), v)) : <String, dynamic>{};

Map<String, dynamic>? asMapOrNull(Object? value) =>
    value is Map ? value.map((k, v) => MapEntry(k.toString(), v)) : null;

String? asStringOrNull(Object? value) => value is String ? value : null;

String asString(Object? value, {String fallback = ''}) =>
    value is String ? value : fallback;

int? asIntOrNull(Object? value) {
  if (value is int) return value;
  if (value is double && value.isFinite) return value.round();
  return null;
}

double? asDoubleOrNull(Object? value) {
  if (value is num && value.isFinite) return value.toDouble();
  return null;
}

bool asBool(Object? value, {bool fallback = false}) =>
    value is bool ? value : fallback;

bool? asBoolOrNull(Object? value) => value is bool ? value : null;

List<String> asStringList(Object? value) =>
    value is List ? value.whereType<String>().toList(growable: false) : const <String>[];

List<Map<String, dynamic>> asMapList(Object? value) => value is List
    ? value.whereType<Map>().map(asMap).toList(growable: false)
    : const <Map<String, dynamic>>[];

/// Parses an ISO-8601 timestamp. Returns null when unparseable; callers must
/// then show the raw string rather than a guessed time.
DateTime? asUtcDateTime(Object? value) {
  if (value is! String || value.isEmpty) return null;
  return DateTime.tryParse(value)?.toUtc();
}
