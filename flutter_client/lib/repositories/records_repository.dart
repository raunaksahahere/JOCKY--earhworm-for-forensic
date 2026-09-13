import '../models/cases/investigation.dart';
import '../models/executions/execution_record.dart';
import '../services/storage/record_store.dart';

/// SQLite-backed local workstation contract; see contracts/CLIENT.md.
class RecordsRepository {
  const RecordsRepository(this._store);

  final RecordStore _store;

  Future<WorkstationRecords> load() => _store.load();

  Future<WorkstationRecords> persist(WorkstationRecords records) async {
    await _store.save(records);
    return records;
  }

  Future<String> storeLocation() => _store.location();

  Future<HistoryClearance> clearExecutionHistory() => _store.clearExecutionHistory();

  /// Newest-first execution list, capped so a long session cannot grow the
  /// store without bound. The cap is explicit in the UI.
  static const executionRetention = 500;

  WorkstationRecords withExecution(
    WorkstationRecords records,
    ExecutionRecord execution,
  ) =>
      records.copyWith(
        executions: [execution, ...records.executions].take(executionRetention).toList(),
      );

  WorkstationRecords withInvestigation(
    WorkstationRecords records,
    Investigation investigation,
  ) {
    final existing = records.investigations.indexWhere((c) => c.id == investigation.id);
    final next = [...records.investigations];
    if (existing >= 0) {
      next[existing] = investigation;
    } else {
      next.insert(0, investigation);
    }
    return records.copyWith(investigations: next);
  }
}
