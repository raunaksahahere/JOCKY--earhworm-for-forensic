import '../../models/reports/report.dart';

/// Every distinct failure the client must present differently.
///
/// A generic "something went wrong" is never acceptable in a forensic tool:
/// the analyst has to know whether the *command* was wrong, the *evidence* was
/// unreachable, or the *engine* was unavailable.
enum FailureKind {
  /// Backend rejected the command text (`error_kind: parser`).
  commandSyntax,

  /// Backend rejected the command semantics (`error_kind: validation`).
  commandValidation,

  /// Backend executed and failed against the host (`error_kind: execution`).
  execution,

  /// Backend raised an unexpected internal error (`error_kind: internal`).
  backendInternal,

  /// No connection to the backend at all.
  backendUnavailable,

  /// Connection made, no response within the deadline.
  timeout,

  /// Caller abandoned the request.
  cancelled,

  /// Backend replied with something that is not a valid JOCKY response.
  malformedResponse,

  /// The backend does not expose the capability the UI asked for.
  unsupportedCapability,

  /// Local disk/store failure inside this client.
  localStorage,
}

/// A typed, presentable failure. [message] is always backend-sourced when the
/// backend produced one; the client never rewrites a backend explanation.
class JockyFailure implements Exception {
  const JockyFailure({
    required this.kind,
    required this.message,
    this.code,
    this.httpStatus,
    this.report,
    this.detail,
  });

  final FailureKind kind;
  final String message;

  /// Backend `error_code`, e.g. `invalid_syntax`, `not_found`.
  final String? code;
  final int? httpStatus;

  /// The backend still produces a report for failures; keep it for the archive.
  final ForensicReport? report;

  /// Client-side context (exception text, path). Never evidence contents.
  final String? detail;

  bool get isCommandRejection =>
      kind == FailureKind.commandSyntax || kind == FailureKind.commandValidation;

  /// Short label used in status strips and table cells.
  String get headline => switch (kind) {
        FailureKind.commandSyntax => 'Command rejected by parser',
        FailureKind.commandValidation => 'Command rejected by validation',
        FailureKind.execution => 'Execution failed',
        FailureKind.backendInternal => 'Backend internal error',
        FailureKind.backendUnavailable => 'Engine unreachable',
        FailureKind.timeout => 'Engine did not respond in time',
        FailureKind.cancelled => 'Execution abandoned',
        FailureKind.malformedResponse => 'Unreadable engine response',
        FailureKind.unsupportedCapability => 'Capability not provided by backend',
        FailureKind.localStorage => 'Local record store unavailable',
      };

  /// What the analyst can actually do next. Deliberately concrete.
  String get remediation => switch (kind) {
        FailureKind.commandSyntax =>
          'Check the syntax against the command reference. Quote paths containing spaces.',
        FailureKind.commandValidation =>
          'The action and target combination is not accepted by the engine.',
        FailureKind.execution =>
          'Confirm the evidence path exists and is readable by the account running the engine.',
        FailureKind.backendInternal =>
          'The engine logged an exception. Inspect the backend log before relying on this run.',
        FailureKind.backendUnavailable =>
          'Start the engine from System Status, or confirm the configured host and port.',
        FailureKind.timeout =>
          'The engine may still be working. Re-check System Status before re-running.',
        FailureKind.cancelled =>
          'The request was abandoned by this client. The engine may have completed it anyway.',
        FailureKind.malformedResponse =>
          'The endpoint answered, but not with a JOCKY response. Verify host and port.',
        FailureKind.unsupportedCapability =>
          'This build of the backend does not expose that capability.',
        FailureKind.localStorage =>
          'This client could not read or write its own record store. Check Settings for the location.',
      };

  @override
  String toString() => 'JockyFailure(${kind.name}, code: $code): $message';
}
