import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/errors/failure.dart';
import '../models/commands/command_response.dart';
import '../models/executions/execution_record.dart';
import 'providers.dart';

enum ExecutionPhase { idle, running, completed, failed, abandoned }

/// State of the single in-flight command this workstation allows at a time.
/// One engine, one synchronous dispatcher: queueing concurrent commands would
/// misrepresent how the backend actually executes them.
class ExecutionState {
  const ExecutionState({
    this.phase = ExecutionPhase.idle,
    this.commandText = '',
    this.startedAt,
    this.finishedAt,
    this.response,
    this.failure,
    this.record,
  });

  final ExecutionPhase phase;
  final String commandText;
  final DateTime? startedAt;
  final DateTime? finishedAt;
  final CommandResponse? response;
  final JockyFailure? failure;
  final ExecutionRecord? record;

  bool get isRunning => phase == ExecutionPhase.running;
  bool get hasOutcome =>
      phase == ExecutionPhase.completed ||
      phase == ExecutionPhase.failed ||
      phase == ExecutionPhase.abandoned;

  /// Elapsed wall-clock, live while running.
  Duration? get elapsed {
    if (startedAt == null) return null;
    return (finishedAt ?? DateTime.now()).difference(startedAt!);
  }

  static const idle = ExecutionState();
}

class ExecutionController extends Notifier<ExecutionState> {
  Completer<void>? _cancellation;

  @override
  ExecutionState build() => ExecutionState.idle;

  /// Submits [commandText] verbatim. No trimming beyond the horizontal
  /// whitespace the backend itself strips, and no client-side validation:
  /// the Python parser decides whether this is a command.
  Future<ExecutionRecord?> execute(
    String commandText, {
    ExecutionOrigin origin = ExecutionOrigin.commandCenter,
  }) async {
    if (state.isRunning) return null;

    final cancellation = Completer<void>();
    _cancellation = cancellation;
    final startedAt = DateTime.now();
    final stopwatch = Stopwatch()..start();

    state = ExecutionState(
      phase: ExecutionPhase.running,
      commandText: commandText,
      startedAt: startedAt,
    );

    final records = ref.read(recordsControllerProvider.notifier);
    final caseId = ref.read(recordsControllerProvider).records.activeCaseId;
    final id = records.newExecutionId();

    ExecutionRecord record;
    try {
      final response = await ref.read(commandRepositoryProvider).execute(
            commandText,
            cancellation: cancellation.future,
          );
      stopwatch.stop();
      record = ExecutionRecord(
        id: id,
        submittedAt: startedAt.toUtc(),
        commandText: commandText,
        outcome: ExecutionOutcome.completed,
        origin: origin,
        caseId: caseId,
        clientElapsedMs: stopwatch.elapsedMilliseconds,
        report: response.report,
      );
      state = ExecutionState(
        phase: ExecutionPhase.completed,
        commandText: commandText,
        startedAt: startedAt,
        finishedAt: DateTime.now(),
        response: response,
        record: record,
      );
    } on JockyFailure catch (failure) {
      stopwatch.stop();
      record = ExecutionRecord(
        id: id,
        submittedAt: startedAt.toUtc(),
        commandText: commandText,
        outcome: failure.kind == FailureKind.cancelled
            ? ExecutionOutcome.abandoned
            : ExecutionOutcome.failed,
        origin: origin,
        caseId: caseId,
        clientElapsedMs: stopwatch.elapsedMilliseconds,
        // The engine returns a report for failures too; keep it.
        report: failure.report,
        failureKind: failure.kind,
        failureCode: failure.code,
        failureMessage: failure.message,
      );
      state = ExecutionState(
        phase: failure.kind == FailureKind.cancelled
            ? ExecutionPhase.abandoned
            : ExecutionPhase.failed,
        commandText: commandText,
        startedAt: startedAt,
        finishedAt: DateTime.now(),
        failure: failure,
        record: record,
      );
    } finally {
      _cancellation = null;
    }

    await records.recordExecution(record);
    return record;
  }

  /// Abandons this client's wait for the response.
  ///
  /// The backend exposes no cancellation endpoint and its dispatcher is
  /// synchronous, so the observation may still complete on the engine. The UI
  /// says "abandoned", never "cancelled on the engine".
  void abandon() {
    final cancellation = _cancellation;
    if (cancellation != null && !cancellation.isCompleted) cancellation.complete();
  }

  void reset() {
    state = ExecutionState.idle;
  }
}

final executionControllerProvider =
    NotifierProvider<ExecutionController, ExecutionState>(ExecutionController.new);

/// Text currently in the Command Center editor. Held in app state so guided
/// tools, history re-use and the palette can all load a command into it
/// without any of them executing it.
class CommandDraftController extends Notifier<String> {
  @override
  String build() => '';

  void set(String value) => state = value;
  void clear() => state = '';
}

final commandDraftProvider =
    NotifierProvider<CommandDraftController, String>(CommandDraftController.new);
