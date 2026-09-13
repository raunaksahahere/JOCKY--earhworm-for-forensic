import '../../core/utils/json.dart';
import '../commands/normalized_command.dart';
import '../results/analysis_result.dart';

/// A report as produced by `reports/report.py`, extended by the API with
/// `normalized_command`, `error_code` and `error_kind`.
///
/// `status == "completed"` means execution completed. It does not assert that
/// collection was complete or that evidence is authentic — the UI must read
/// `complete`, `truncated`, `skippedCount` and `warnings` for that.
class ForensicReport {
  const ForensicReport({
    required this.reportId,
    required this.timestamp,
    required this.schemaVersion,
    required this.command,
    required this.action,
    required this.target,
    required this.status,
    required this.executionTimeMs,
    required this.warnings,
    required this.errors,
    required this.normalizedCommand,
    required this.errorCode,
    required this.errorKind,
    required this.result,
    required this.raw,
  });

  final String reportId;
  final String timestamp;
  final int? schemaVersion;
  final String command;
  final String? action;
  final String? target;
  final String status;
  final double? executionTimeMs;
  final List<String> warnings;
  final List<String> errors;
  final NormalizedCommand? normalizedCommand;
  final String? errorCode;
  final String? errorKind;
  final AnalysisResult? result;
  final Map<String, dynamic> raw;

  bool get completed => status == 'completed';
  bool get failed => status == 'failed';

  DateTime? get timestampUtc => asUtcDateTime(timestamp);

  static ForensicReport? fromJson(Map<String, dynamic>? json) {
    if (json == null || json.isEmpty) return null;
    return ForensicReport(
      reportId: asString(json['report_id'], fallback: 'unknown'),
      timestamp: asString(json['timestamp']),
      schemaVersion: asIntOrNull(json['schema_version']),
      command: asString(json['command']),
      action: asStringOrNull(json['action']),
      target: asStringOrNull(json['target']),
      status: asString(json['status'], fallback: 'unknown'),
      executionTimeMs: asDoubleOrNull(json['execution_time_ms']),
      warnings: asStringList(json['warnings']),
      errors: asStringList(json['errors']),
      normalizedCommand: NormalizedCommand.fromJson(asMapOrNull(json['normalized_command'])),
      errorCode: asStringOrNull(json['error_code']),
      errorKind: asStringOrNull(json['error_kind']),
      result: AnalysisResult.fromJson(asMapOrNull(json['result'])),
      raw: json,
    );
  }

  Map<String, dynamic> toJson() => raw;
}
