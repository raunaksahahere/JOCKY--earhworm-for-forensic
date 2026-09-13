import '../../core/utils/json.dart';

/// An evidence source an analyst has attached to a case.
///
/// The backend has no evidence registry: it observes a path when a command
/// names one. This record is the analyst's own list of what this case covers,
/// held by the client.
class EvidenceSource {
  const EvidenceSource({
    required this.id,
    required this.path,
    required this.isDirectory,
    required this.addedAt,
    this.note,
  });

  final String id;
  final String path;
  final bool isDirectory;
  final DateTime addedAt;
  final String? note;

  String get displayName {
    final normalised = path.replaceAll('\\', '/');
    final trimmed = normalised.endsWith('/')
        ? normalised.substring(0, normalised.length - 1)
        : normalised;
    final index = trimmed.lastIndexOf('/');
    return index >= 0 && index < trimmed.length - 1 ? trimmed.substring(index + 1) : trimmed;
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'path': path,
        'is_directory': isDirectory,
        'added_at': addedAt.toUtc().toIso8601String(),
        'note': note,
      };

  static EvidenceSource? fromJson(Map<String, dynamic> json) {
    final id = asStringOrNull(json['id']);
    final path = asStringOrNull(json['path']);
    final addedAt = asUtcDateTime(json['added_at']);
    if (id == null || path == null || addedAt == null) return null;
    return EvidenceSource(
      id: id,
      path: path,
      isDirectory: asBool(json['is_directory']),
      addedAt: addedAt,
      note: asStringOrNull(json['note']),
    );
  }
}

/// SQLite-backed local workstation contract; see contracts/CLIENT.md.
class Investigation {
  const Investigation({
    required this.id,
    required this.title,
    required this.openedAt,
    this.reference,
    this.examiner,
    this.notes = '',
    this.evidence = const [],
    this.closedAt,
  });

  final String id;
  final String title;
  final DateTime openedAt;

  /// Analyst-supplied external case reference (ticket, FIR, exhibit number).
  final String? reference;
  final String? examiner;
  final String notes;
  final List<EvidenceSource> evidence;
  final DateTime? closedAt;

  bool get isOpen => closedAt == null;

  Investigation copyWith({
    String? title,
    String? reference,
    String? examiner,
    String? notes,
    List<EvidenceSource>? evidence,
    DateTime? closedAt,
    bool clearClosedAt = false,
  }) =>
      Investigation(
        id: id,
        title: title ?? this.title,
        openedAt: openedAt,
        reference: reference ?? this.reference,
        examiner: examiner ?? this.examiner,
        notes: notes ?? this.notes,
        evidence: evidence ?? this.evidence,
        closedAt: clearClosedAt ? null : (closedAt ?? this.closedAt),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'opened_at': openedAt.toUtc().toIso8601String(),
        'reference': reference,
        'examiner': examiner,
        'notes': notes,
        'evidence': evidence.map((e) => e.toJson()).toList(),
        'closed_at': closedAt?.toUtc().toIso8601String(),
      };

  static Investigation? fromJson(Map<String, dynamic> json) {
    final id = asStringOrNull(json['id']);
    final openedAt = asUtcDateTime(json['opened_at']);
    if (id == null || openedAt == null) return null;
    return Investigation(
      id: id,
      title: asString(json['title'], fallback: 'Untitled investigation'),
      openedAt: openedAt,
      reference: asStringOrNull(json['reference']),
      examiner: asStringOrNull(json['examiner']),
      notes: asString(json['notes']),
      evidence: asMapList(json['evidence'])
          .map(EvidenceSource.fromJson)
          .whereType<EvidenceSource>()
          .toList(growable: false),
      closedAt: asUtcDateTime(json['closed_at']),
    );
  }
}
