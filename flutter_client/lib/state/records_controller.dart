import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../services/storage/api_record_store.dart';

import '../core/errors/failure.dart';
import '../models/cases/investigation.dart';
import '../models/executions/execution_record.dart';
import '../services/storage/record_store.dart';
import 'providers.dart';

class RecordsState {
  const RecordsState({
    required this.records,
    this.storeFailure,
    this.storeLocation,
  });

  final WorkstationRecords records;

  /// Set when the store could not be read or written. The UI shows the session
  /// as unrecorded rather than pretending it was saved.
  final JockyFailure? storeFailure;
  final String? storeLocation;

  bool get isDurable => storeFailure == null;

  RecordsState copyWith({
    WorkstationRecords? records,
    JockyFailure? storeFailure,
    bool clearFailure = false,
    String? storeLocation,
  }) =>
      RecordsState(
        records: records ?? this.records,
        storeFailure: clearFailure ? null : (storeFailure ?? this.storeFailure),
        storeLocation: storeLocation ?? this.storeLocation,
      );
}

/// Owns cases, evidence lists and execution history for this workstation.
class RecordsController extends Notifier<RecordsState> {
  int _sequence = 0;

  @override
  RecordsState build() {
    final (records, failure) = ref.watch(initialRecordsProvider);
    _sequence = records.executions.length;
    unawaitedLocation();
    ref.listen(backendReadyProvider, (previous, ready) {
      if (ready && previous != true && ref.read(recordStoreProvider) is ApiRecordStore) refresh();
    });
    return RecordsState(records: records, storeFailure: failure);
  }

  Future<void> refresh() async {
    try {
      final records = await ref.read(recordsRepositoryProvider).load();
      state = state.copyWith(records: records, clearFailure: true);
    } on JockyFailure catch (failure) {
      state = state.copyWith(storeFailure: failure);
    }
  }

  void unawaitedLocation() {
    ref.read(recordsRepositoryProvider).storeLocation().then(
          (path) => state = state.copyWith(storeLocation: path),
          onError: (_) {},
        );
  }

  String _nextId(String prefix) {
    _sequence++;
    final stamp = DateTime.now().microsecondsSinceEpoch.toRadixString(36).toUpperCase();
    return '$prefix-$stamp-${_sequence.toString().padLeft(3, '0')}';
  }

  Future<void> _commit(WorkstationRecords next) async {
    state = state.copyWith(records: next);
    try {
      await ref.read(recordsRepositoryProvider).persist(next);
      if (state.storeFailure != null) state = state.copyWith(clearFailure: true);
      if (ref.read(recordStoreProvider) is ApiRecordStore) await refresh();
    } on JockyFailure catch (failure) {
      state = state.copyWith(storeFailure: failure);
    }
  }

  Future<void> recordExecution(ExecutionRecord execution) => _commit(
        ref.read(recordsRepositoryProvider).withExecution(state.records, execution),
      );

  Future<Investigation> openInvestigation({
    required String title,
    String? reference,
    String? examiner,
  }) async {
    final investigation = Investigation(
      id: _nextId('CASE'),
      title: title.trim().isEmpty ? 'Untitled investigation' : title.trim(),
      openedAt: DateTime.now().toUtc(),
      reference: reference?.trim().isEmpty ?? true ? null : reference!.trim(),
      examiner: examiner?.trim().isEmpty ?? true ? null : examiner!.trim(),
    );
    final withCase = ref
        .read(recordsRepositoryProvider)
        .withInvestigation(state.records, investigation);
    await _commit(withCase.copyWith(activeCaseId: investigation.id));
    return investigation;
  }

  Future<void> updateInvestigation(Investigation investigation) => _commit(
        ref
            .read(recordsRepositoryProvider)
            .withInvestigation(state.records, investigation),
      );

  Future<void> setActiveCase(String? caseId) => _commit(
        caseId == null
            ? state.records.copyWith(clearActiveCase: true)
            : state.records.copyWith(activeCaseId: caseId),
      );

  Future<void> closeInvestigation(String caseId) async {
    final investigation =
        state.records.investigations.where((c) => c.id == caseId).firstOrNull;
    if (investigation == null) return;
    await updateInvestigation(
      investigation.copyWith(closedAt: DateTime.now().toUtc()),
    );
  }

  Future<void> reopenInvestigation(String caseId) async {
    final investigation =
        state.records.investigations.where((c) => c.id == caseId).firstOrNull;
    if (investigation == null) return;
    await updateInvestigation(investigation.copyWith(clearClosedAt: true));
  }

  Future<void> addEvidence(
    String caseId, {
    required String path,
    required bool isDirectory,
    String? note,
  }) async {
    final investigation =
        state.records.investigations.where((c) => c.id == caseId).firstOrNull;
    if (investigation == null) return;
    if (investigation.evidence.any((e) => e.path == path)) return;
    final source = EvidenceSource(
      id: _nextId('EV'),
      path: path,
      isDirectory: isDirectory,
      addedAt: DateTime.now().toUtc(),
      note: note,
    );
    await updateInvestigation(
      investigation.copyWith(evidence: [...investigation.evidence, source]),
    );
  }

  Future<void> removeEvidence(String caseId, String evidenceId) async {
    final investigation =
        state.records.investigations.where((c) => c.id == caseId).firstOrNull;
    if (investigation == null) return;
    await updateInvestigation(
      investigation.copyWith(
        evidence:
            investigation.evidence.where((e) => e.id != evidenceId).toList(growable: false),
      ),
    );
  }

  Future<void> setNotes(String caseId, String notes) async {
    final investigation =
        state.records.investigations.where((c) => c.id == caseId).firstOrNull;
    if (investigation == null) return;
    await updateInvestigation(investigation.copyWith(notes: notes));
  }

  /// Explicit, acknowledged destruction of the command record. Never automatic
  /// — a corrupt store is reported, not silently replaced.
  ///
  /// The store performs the deletion and reports what it removed, because the
  /// engine keeps its own authoritative record and retains anything that
  /// belongs to an investigation. Committing an empty execution list here
  /// instead would leave the UI briefly blank and then refill on the next
  /// refresh, which is exactly how this used to appear to do nothing.
  Future<HistoryClearance> clearExecutionHistory() async {
    try {
      final clearance = await ref.read(recordsRepositoryProvider).clearExecutionHistory();
      await refresh();
      return clearance;
    } on JockyFailure catch (failure) {
      state = state.copyWith(storeFailure: failure);
      rethrow;
    }
  }

  Future<void> resetAll() => _commit(WorkstationRecords.empty);

  String newExecutionId() => _nextId('EXEC');
}

final recordsControllerProvider =
    NotifierProvider<RecordsController, RecordsState>(RecordsController.new);

/// The case commands are currently attributed to, or null.
final activeCaseProvider = Provider<Investigation?>(
  (ref) => ref.watch(recordsControllerProvider).records.activeCase,
);

/// Newest-first execution history.
final executionHistoryProvider = Provider<List<ExecutionRecord>>(
  (ref) => ref.watch(recordsControllerProvider).records.executions,
);

/// Reports extracted from executions. The engine returns a report inline with
/// every execution, including failures, so this is the complete report archive
/// this workstation holds.
final reportArchiveProvider = Provider<List<ExecutionRecord>>(
  (ref) => ref
      .watch(executionHistoryProvider)
      .where((e) => e.report != null)
      .toList(growable: false),
);
