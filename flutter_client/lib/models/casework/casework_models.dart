import '../../core/utils/json.dart';

/// An enquiry. One case holds the investigations, evidence sources and notes
/// that belong together; an investigation can still stand alone without one.
class CaseRecord {
  const CaseRecord({
    required this.id,
    required this.title,
    required this.status,
    required this.createdAt,
    this.closedAt,
    this.examiner,
    this.reference,
    this.investigationCount = 0,
    this.evidenceSourceCount = 0,
  });

  factory CaseRecord.fromJson(Map<String, dynamic> json) => CaseRecord(
        id: asString(json['id']),
        title: asString(json['title']),
        status: asString(json['status'], fallback: 'open'),
        createdAt: asString(json['created_at']),
        closedAt: asStringOrNull(json['closed_at']),
        examiner: asStringOrNull(json['examiner']),
        reference: asStringOrNull(json['reference']),
        investigationCount: asIntOrNull(json['investigation_count']) ?? 0,
        evidenceSourceCount: asIntOrNull(json['evidence_source_count']) ?? 0,
      );

  final String id;
  final String title;
  final String status;
  final String createdAt;
  final String? closedAt;
  final String? examiner;
  final String? reference;
  final int investigationCount;
  final int evidenceSourceCount;

  bool get isOpen => status == 'open';
}

/// A registered evidence source, with the integrity history that proves what
/// was done to it. `supersedes` names an earlier acquisition of the same bytes;
/// a source is never replaced, only added to.
class EvidenceSource {
  const EvidenceSource({
    required this.id,
    required this.reference,
    required this.sourceType,
    required this.acquisitionStatus,
    required this.verificationState,
    required this.registeredAt,
    this.caseId,
    this.originalPath,
    this.sha256,
    this.sizeBytes,
    this.supersedes,
    this.description,
    this.integrityEvents = const [],
  });

  factory EvidenceSource.fromJson(Map<String, dynamic> json) => EvidenceSource(
        id: asString(json['id']),
        reference: asString(json['reference']),
        sourceType: asString(json['source_type']),
        acquisitionStatus: asString(json['acquisition_status']),
        verificationState: asString(json['verification_state']),
        registeredAt: asString(json['registered_at']),
        caseId: asStringOrNull(json['case_id']),
        originalPath: asStringOrNull(json['original_path']),
        sha256: asStringOrNull(json['sha256']),
        sizeBytes: json['size_bytes'] is num ? (json['size_bytes'] as num).toInt() : null,
        supersedes: asStringOrNull(json['supersedes']),
        description: asStringOrNull(json['description']),
        integrityEvents: asMapList(json['integrity_events'])
            .map(IntegrityEvent.fromJson)
            .toList(growable: false),
      );

  final String id;
  final String reference;
  final String sourceType;
  final String acquisitionStatus;
  final String verificationState;
  final String registeredAt;
  final String? caseId;
  final String? originalPath;
  final String? sha256;
  final int? sizeBytes;
  final String? supersedes;
  final String? description;
  final List<IntegrityEvent> integrityEvents;

  bool get isVerified => verificationState == 'VERIFIED';
  bool get isMismatch => verificationState == 'MISMATCH';
}

class IntegrityEvent {
  const IntegrityEvent({
    required this.event,
    required this.timestamp,
    required this.outcome,
    this.detail,
    this.expected,
    this.observed,
  });

  factory IntegrityEvent.fromJson(Map<String, dynamic> json) => IntegrityEvent(
        event: asString(json['event']),
        timestamp: asString(json['timestamp']),
        outcome: asString(json['outcome']),
        detail: asStringOrNull(json['detail']),
        expected: asStringOrNull(json['expected_sha256']),
        observed: asStringOrNull(json['observed_sha256']),
      );

  final String event;
  final String timestamp;
  final String outcome;
  final String? detail;
  final String? expected;
  final String? observed;
}

/// An authorized machine. `health` says whether JOCKY has heard from it
/// recently — never whether the machine itself is up.
class EndpointRecord {
  const EndpointRecord({
    required this.id,
    required this.name,
    required this.status,
    required this.healthState,
    required this.enrolledAt,
    this.hostname,
    this.platform,
    this.agentVersion,
    this.lastSeenAt,
    this.healthDetail,
    this.authorizationReference,
    this.capabilities = const [],
    this.taskCounts = const {},
  });

  factory EndpointRecord.fromJson(Map<String, dynamic> json) {
    final health = asMap(json['health']);
    return EndpointRecord(
      id: asString(json['id']),
      name: asString(json['name']),
      status: asString(json['status']),
      healthState: asString(health['state'], fallback: 'unknown'),
      enrolledAt: asString(json['enrolled_at']),
      hostname: asStringOrNull(json['hostname']),
      platform: asStringOrNull(json['platform']),
      agentVersion: asStringOrNull(json['agent_version']),
      lastSeenAt: asStringOrNull(json['last_seen_at']),
      healthDetail: asStringOrNull(health['detail']),
      authorizationReference: asStringOrNull(json['authorization_reference']),
      capabilities: asStringList(json['capabilities']),
      taskCounts: asMap(json['tasks']).map((key, value) => MapEntry(key, asIntOrNull(value) ?? 0)),
    );
  }

  final String id;
  final String name;
  final String status;
  final String healthState;
  final String enrolledAt;
  final String? hostname;
  final String? platform;
  final String? agentVersion;
  final String? lastSeenAt;
  final String? healthDetail;
  final String? authorizationReference;
  final List<String> capabilities;
  final Map<String, int> taskCounts;

  bool get isRevoked => status == 'revoked';
}

/// One thing JOCKY or the investigator did. Deliberately separate from
/// evidence: this is a record of the investigation, not of the examined host.
class AuditEntry {
  const AuditEntry({
    required this.timestamp,
    required this.actor,
    required this.action,
    required this.outcome,
    this.objectType,
    this.objectId,
    this.caseId,
    this.detail,
  });

  factory AuditEntry.fromJson(Map<String, dynamic> json) => AuditEntry(
        timestamp: asString(json['timestamp']),
        actor: asString(json['actor']),
        action: asString(json['action']),
        outcome: asString(json['outcome']),
        objectType: asStringOrNull(json['object_type']),
        objectId: asStringOrNull(json['object_id']),
        caseId: asStringOrNull(json['case_id']),
        detail: json['detail'] == null ? null : '${json['detail']}',
      );

  final String timestamp;
  final String actor;
  final String action;
  final String outcome;
  final String? objectType;
  final String? objectId;
  final String? caseId;
  final String? detail;

  bool get succeeded => outcome == 'success';
}

/// A source an investigator may add to a collection.
///
/// `supported` is the platform's own answer, not the registry's. A source this
/// platform has no adapter for must not be offered as though selecting it would
/// collect something: the collection would succeed and the evidence would
/// simply be absent, which is the one kind of gap a forensic tool must never
/// produce silently.
class CollectionSource {
  const CollectionSource({
    required this.source,
    required this.description,
    required this.needsArgument,
    this.supported = true,
    this.unsupportedReason,
  });

  factory CollectionSource.fromJson(Map<String, dynamic> json) => CollectionSource(
        source: asString(json['source']),
        description: asString(json['description']),
        needsArgument: json['needs_argument'] == true,
        // Absent means supported: an older engine that does not report this
        // could only have offered sources it could collect.
        supported: json['supported'] != false,
        unsupportedReason: asStringOrNull(json['unsupported_reason']),
      );

  final String source;
  final String description;
  final bool needsArgument;
  final bool supported;
  final String? unsupportedReason;
}
