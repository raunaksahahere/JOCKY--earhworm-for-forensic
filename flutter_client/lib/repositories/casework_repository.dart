import '../models/casework/casework_models.dart';
import '../services/api/jocky_api_client.dart';

/// Reads and writes the case file: cases, evidence sources, endpoints and the
/// audit trail. Every call goes to the engine; the client stores none of this
/// itself, so what the investigator sees is what the database holds.
class CaseworkRepository {
  const CaseworkRepository(this._client);

  final JockyApiClient _client;

  List<Map<String, dynamic>> _items(Map<String, dynamic> payload) =>
      (payload['items'] as List? ?? const [])
          .whereType<Map>()
          .map((row) => row.map((key, value) => MapEntry(key.toString(), value)))
          .toList(growable: false);

  // --- cases ---------------------------------------------------------------
  Future<List<CaseRecord>> cases() async =>
      _items(await _client.jsonRequest('/api/v1/cases'))
          .map(CaseRecord.fromJson)
          .toList(growable: false);

  Future<CaseRecord> createCase({
    required String title,
    String? examiner,
    String? reference,
  }) async =>
      CaseRecord.fromJson(await _client.jsonRequest('/api/v1/cases', body: {
        'title': title,
        if (examiner != null && examiner.isNotEmpty) 'examiner': examiner,
        if (reference != null && reference.isNotEmpty) 'reference': reference,
      }));

  Future<CaseRecord> setCaseOpen(String caseId, {required bool open}) async =>
      CaseRecord.fromJson(await _client
          .jsonRequest('/api/v1/cases/$caseId/close', body: {'reopen': open}));

  // --- evidence sources ----------------------------------------------------
  Future<List<EvidenceSource>> evidenceSources({String? caseId}) async {
    final query = caseId == null ? '' : '?case_id=$caseId';
    return _items(await _client.jsonRequest('/api/v1/evidence-sources$query'))
        .map(EvidenceSource.fromJson)
        .toList(growable: false);
  }

  Future<EvidenceSource> registerEvidence({
    required String path,
    String? caseId,
    String? description,
  }) async =>
      EvidenceSource.fromJson(await _client.jsonRequest('/api/v1/evidence-sources', body: {
        'path': path,
        'case_id': ?caseId,
        if (description != null && description.isNotEmpty) 'description': description,
      }));

  Future<EvidenceSource> verifyEvidence(String evidenceId) async =>
      EvidenceSource.fromJson(
          await _client.jsonRequest('/api/v1/evidence-sources/$evidenceId/verify', body: {}));

  // --- endpoints -----------------------------------------------------------
  Future<List<EndpointRecord>> endpoints() async =>
      _items(await _client.jsonRequest('/api/v1/endpoints'))
          .map(EndpointRecord.fromJson)
          .toList(growable: false);

  /// Issues a one-time enrollment token. The authority for collecting from the
  /// machine is required, and the token is returned once and never again.
  Future<Map<String, dynamic>> authorizeEndpoint({
    required String name,
    required String authorizationReference,
  }) =>
      _client.jsonRequest('/api/v1/endpoints/authorize', body: {
        'endpoint_name': name,
        'authorization_reference': authorizationReference,
      });

  Future<EndpointRecord> revokeEndpoint(String endpointId) async => EndpointRecord.fromJson(
      await _client.jsonRequest('/api/v1/endpoints/$endpointId/revoke', body: {}));

  Future<List<Map<String, dynamic>>> endpointTasks({String? endpointId}) async {
    final query = endpointId == null ? '' : '?endpoint_id=$endpointId';
    return _items(await _client.jsonRequest('/api/v1/endpoint-tasks$query'));
  }

  // --- audit and notes -----------------------------------------------------
  Future<List<AuditEntry>> auditTrail({String? caseId}) async {
    final query = caseId == null ? '' : '?case_id=$caseId';
    return _items(await _client.jsonRequest('/api/v1/audit$query'))
        .map(AuditEntry.fromJson)
        .toList(growable: false);
  }

  Future<void> addNote({
    required String body,
    String? caseId,
    String subjectType = 'case',
    String? subjectId,
  }) =>
      _client.jsonRequest('/api/v1/notes', body: {
        'body': body,
        'subject_type': subjectType,
        'case_id': ?caseId,
        'subject_id': ?subjectId,
      });

  // --- collection sources --------------------------------------------------
  Future<List<CollectionSource>> collectionSources() async {
    final payload = await _client.jsonRequest('/api/v1/collection-sources');
    return (payload['selectable'] as List? ?? const [])
        .whereType<Map>()
        .map((row) =>
            CollectionSource.fromJson(row.map((k, v) => MapEntry(k.toString(), v))))
        .toList(growable: false);
  }
}
