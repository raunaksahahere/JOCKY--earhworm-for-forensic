import '../../core/utils/json.dart';

/// The backend's authoritative parse of a command line
/// (`compiler/commands.py` -> `Command.to_dict()`).
///
/// The client never produces this itself; it only ever displays what the
/// backend parser returned.
class NormalizedCommand {
  const NormalizedCommand({
    required this.schemaVersion,
    required this.action,
    required this.target,
    required this.path,
    required this.searchPath,
    required this.raw,
  });

  final int? schemaVersion;
  final String action;
  final String? target;
  final String? path;
  final String? searchPath;
  final Map<String, dynamic> raw;

  static NormalizedCommand? fromJson(Map<String, dynamic>? json) {
    if (json == null || json.isEmpty) return null;
    return NormalizedCommand(
      schemaVersion: asIntOrNull(json['schema_version']),
      action: asString(json['action'], fallback: 'unknown'),
      target: asStringOrNull(json['target']),
      path: asStringOrNull(json['path']),
      searchPath: asStringOrNull(json['search_path']),
      raw: json,
    );
  }

  /// Human label, e.g. `hash file`. Purely presentational.
  String get label => target == null ? action : '$action $target';
}
