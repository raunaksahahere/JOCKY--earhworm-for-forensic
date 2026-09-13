import '../api/jocky_api_client.dart';
import 'record_store.dart';

/// SQLite is authoritative. The client sends editable case metadata only.
class ApiRecordStore implements RecordStore {
  ApiRecordStore(this.api);
  final JockyApiClient api;

  @override
  Future<WorkstationRecords> load() async {
    final records = WorkstationRecords.fromJson(await api.jsonRequest('/api/v1/workstation'));
    api.activeCaseId = records.activeCaseId;
    return records;
  }

  @override
  Future<void> save(WorkstationRecords records) async {
    await api.jsonRequest('/api/v1/workstation', body: {
      'investigations': records.investigations.map((item) => item.toJson()).toList(),
      'active_case_id': records.activeCaseId,
    });
    api.activeCaseId = records.activeCaseId;
  }

  /// The engine owns the execution record, so clearing is a request to it, not
  /// a local edit. `save` deliberately sends case metadata only: a save that
  /// simply omitted the executions changed nothing, and the next load restored
  /// every one of them.
  @override
  Future<HistoryClearance> clearExecutionHistory() async =>
      HistoryClearance.fromJson(await api.jsonRequest('/api/v1/history/clear', body: const {}));

  @override
  Future<String> location() async => 'Backend SQLite workspace (see Device investigations / storage)';
}
