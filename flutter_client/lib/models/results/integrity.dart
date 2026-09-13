import '../../core/utils/json.dart';

/// Structural sanity check from `analysis/integrity.py`.
/// `unknown` means a resource limit was hit — it is not a clean verdict.
enum IntegrityStatus { ok, warning, critical, unknown }

IntegrityStatus integrityStatusFrom(String? raw) => switch (raw) {
      'ok' => IntegrityStatus.ok,
      'warning' => IntegrityStatus.warning,
      'critical' => IntegrityStatus.critical,
      _ => IntegrityStatus.unknown,
    };

class IntegrityCheck {
  const IntegrityCheck({
    required this.performed,
    required this.fileType,
    required this.status,
    required this.message,
  });

  final bool performed;
  final String fileType;
  final IntegrityStatus status;
  final String message;

  factory IntegrityCheck.fromJson(Map<String, dynamic> json) => IntegrityCheck(
        performed: asBool(json['performed']),
        fileType: asString(json['file_type'], fallback: 'unknown'),
        status: integrityStatusFrom(asStringOrNull(json['status'])),
        message: asString(json['message']),
      );
}

/// Comparison against JOCKY's own prior observation of the same absolute path.
enum LedgerComparison { firstRecorded, unchanged, altered, algorithmMismatch, unknown }

LedgerComparison ledgerComparisonFrom(String? raw) => switch (raw) {
      'first_recorded' => LedgerComparison.firstRecorded,
      'unchanged' => LedgerComparison.unchanged,
      'altered' => LedgerComparison.altered,
      'algorithm_mismatch' => LedgerComparison.algorithmMismatch,
      _ => LedgerComparison.unknown,
    };

class IntegrityHistory {
  const IntegrityHistory({
    required this.hasPrevious,
    required this.status,
    required this.message,
  });

  final bool hasPrevious;
  final LedgerComparison status;
  final String message;

  factory IntegrityHistory.fromJson(Map<String, dynamic> json) => IntegrityHistory(
        hasPrevious: asBool(json['has_previous']),
        status: ledgerComparisonFrom(asStringOrNull(json['status'])),
        message: asString(json['message']),
      );
}

class PreviousHash {
  const PreviousHash({
    required this.algorithm,
    required this.digest,
    required this.sizeBytes,
    required this.timestamp,
  });

  final String algorithm;
  final String digest;
  final int? sizeBytes;
  final String timestamp;

  factory PreviousHash.fromJson(Map<String, dynamic> json) => PreviousHash(
        algorithm: asString(json['algorithm'], fallback: 'unknown'),
        digest: asString(json['hash']),
        sizeBytes: asIntOrNull(json['size_bytes']),
        timestamp: asString(json['timestamp']),
      );
}
