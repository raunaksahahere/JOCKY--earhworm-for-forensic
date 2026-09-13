import '../../core/errors/failure.dart';
import '../../core/utils/json.dart';
import '../reports/report.dart';

/// How a command reached the engine. Guided tools and the Command Center use
/// the same execution path; this only records which surface submitted it.
enum ExecutionOrigin { commandCenter, guidedTool, reRun }

ExecutionOrigin executionOriginFrom(String? raw) => switch (raw) {
      'guided_tool' => ExecutionOrigin.guidedTool,
      're_run' => ExecutionOrigin.reRun,
      _ => ExecutionOrigin.commandCenter,
    };

String executionOriginTo(ExecutionOrigin origin) => switch (origin) {
      ExecutionOrigin.guidedTool => 'guided_tool',
      ExecutionOrigin.reRun => 're_run',
      ExecutionOrigin.commandCenter => 'command_center',
    };

enum ExecutionOutcome { completed, failed, abandoned }

ExecutionOutcome executionOutcomeFrom(String? raw) => switch (raw) {
      'failed' => ExecutionOutcome.failed,
      'abandoned' => ExecutionOutcome.abandoned,
      'completed' => ExecutionOutcome.completed,
      _ => ExecutionOutcome.failed,
    };

String executionOutcomeTo(ExecutionOutcome outcome) => switch (outcome) {
      ExecutionOutcome.failed => 'failed',
      ExecutionOutcome.abandoned => 'abandoned',
      ExecutionOutcome.completed => 'completed',
    };

/// SQLite-backed local workstation contract; see contracts/CLIENT.md.
class ExecutionRecord {
  const ExecutionRecord({
    required this.id,
    required this.submittedAt,
    required this.commandText,
    required this.outcome,
    required this.origin,
    required this.caseId,
    required this.clientElapsedMs,
    this.report,
    this.failureKind,
    this.failureCode,
    this.failureMessage,
  });

  final String id;
  final DateTime submittedAt;
  final String commandText;
  final ExecutionOutcome outcome;
  final ExecutionOrigin origin;

  /// Null when no case was active at submission time.
  final String? caseId;

  /// Measured by this client, wall-clock. Distinct from the engine's own
  /// `execution_time_ms`, which excludes transport.
  final int clientElapsedMs;

  /// Present whenever the engine produced one — it does so for failures too.
  final ForensicReport? report;

  final FailureKind? failureKind;
  final String? failureCode;
  final String? failureMessage;

  String? get reportId => report?.reportId;
  String? get action => report?.action ?? report?.normalizedCommand?.action;

  /// Engine-measured duration, or null when the engine did not report one.
  double? get engineElapsedMs => report?.executionTimeMs;

  List<String> get warnings => report?.warnings ?? const [];

  /// One-line result summary for dense tables. Built only from returned data.
  String get summary {
    final failure = failureMessage;
    if (failure != null && failure.isNotEmpty) return failure;
    final result = report?.result;
    if (result != null && result.message.isNotEmpty) return result.message;
    if (outcome == ExecutionOutcome.abandoned) {
      return 'Abandoned by this client before the engine replied.';
    }
    return 'No summary was returned by the engine.';
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'submitted_at': submittedAt.toUtc().toIso8601String(),
        'command_text': commandText,
        'outcome': executionOutcomeTo(outcome),
        'origin': executionOriginTo(origin),
        'case_id': caseId,
        'client_elapsed_ms': clientElapsedMs,
        'failure_kind': failureKind?.name,
        'failure_code': failureCode,
        'failure_message': failureMessage,
        'report': report?.toJson(),
      };

  static ExecutionRecord? fromJson(Map<String, dynamic> json) {
    final id = asStringOrNull(json['id']);
    final submittedAt = asUtcDateTime(json['submitted_at']);
    if (id == null || submittedAt == null) return null;
    final kindName = asStringOrNull(json['failure_kind']);
    return ExecutionRecord(
      id: id,
      submittedAt: submittedAt,
      commandText: asString(json['command_text']),
      outcome: executionOutcomeFrom(asStringOrNull(json['outcome'])),
      origin: executionOriginFrom(asStringOrNull(json['origin'])),
      caseId: asStringOrNull(json['case_id']),
      clientElapsedMs: asIntOrNull(json['client_elapsed_ms']) ?? 0,
      report: ForensicReport.fromJson(asMapOrNull(json['report'])),
      failureKind: kindName == null
          ? null
          : FailureKind.values.where((k) => k.name == kindName).firstOrNull,
      failureCode: asStringOrNull(json['failure_code']),
      failureMessage: asStringOrNull(json['failure_message']),
    );
  }
}
