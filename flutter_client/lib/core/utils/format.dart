import 'package:intl/intl.dart';

/// Display helpers.
///
/// Every one of these returns an explicit "not available" marker rather than a
/// zero or a guess when the backend reported null.
const unavailableMarker = '—';

String formatBytes(int? bytes) {
  if (bytes == null || bytes < 0) return unavailableMarker;
  if (bytes < 1024) return '$bytes B';
  const units = ['KB', 'MB', 'GB', 'TB', 'PB'];
  var value = bytes / 1024;
  var unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return '${value.toStringAsFixed(value >= 100 ? 0 : 2)} ${units[unit]}';
}

String formatDurationMs(num? ms) {
  if (ms == null) return unavailableMarker;
  if (ms < 1000) return '${ms.toStringAsFixed(ms < 10 ? 2 : 0)} ms';
  return '${(ms / 1000).toStringAsFixed(2)} s';
}

String formatPercent(double? value, {int decimals = 1}) =>
    value == null ? unavailableMarker : '${value.toStringAsFixed(decimals)}%';

String formatUptime(int? seconds) {
  if (seconds == null || seconds < 0) return unavailableMarker;
  final days = seconds ~/ 86400;
  final hours = (seconds % 86400) ~/ 3600;
  final minutes = (seconds % 3600) ~/ 60;
  return [
    if (days > 0) '${days}d',
    if (days > 0 || hours > 0) '${hours}h',
    '${minutes}m',
  ].join(' ');
}

final _absolute = DateFormat('yyyy-MM-dd HH:mm:ss');

/// Timestamps are rendered in the operator-selected zone. The raw ISO string
/// with its offset stays available in detail views, because a report's own
/// timestamp is evidence.
String formatTimestamp(DateTime? value, {bool utc = true}) {
  if (value == null) return unavailableMarker;
  final local = utc ? value.toUtc() : value.toLocal();
  return '${_absolute.format(local)} ${utc ? 'UTC' : _offsetLabel(local)}';
}

String formatIsoTimestamp(String? iso, {bool utc = true}) {
  if (iso == null || iso.isEmpty) return unavailableMarker;
  final parsed = DateTime.tryParse(iso);
  return parsed == null ? iso : formatTimestamp(parsed, utc: utc);
}

String _offsetLabel(DateTime local) {
  final offset = local.timeZoneOffset;
  final sign = offset.isNegative ? '-' : '+';
  final hours = offset.inHours.abs().toString().padLeft(2, '0');
  final minutes = (offset.inMinutes.abs() % 60).toString().padLeft(2, '0');
  return 'UTC$sign$hours:$minutes';
}

String formatRelative(DateTime? value) {
  if (value == null) return unavailableMarker;
  final diff = DateTime.now().difference(value);
  if (diff.inSeconds < 5) return 'moments ago';
  if (diff.inSeconds < 60) return '${diff.inSeconds}s ago';
  if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
  if (diff.inHours < 24) return '${diff.inHours}h ago';
  return '${diff.inDays}d ago';
}

/// Elides the middle of a long path, keeping both ends readable. Full values
/// are always available via tooltip and copy.
String elideMiddle(String value, {int max = 56}) {
  if (value.length <= max) return value;
  final keep = (max - 1) ~/ 2;
  return '${value.substring(0, keep)}…${value.substring(value.length - keep)}';
}
