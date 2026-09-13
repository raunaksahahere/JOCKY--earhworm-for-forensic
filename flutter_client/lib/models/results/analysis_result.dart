import '../../core/utils/json.dart';
import 'indicator.dart';
import 'integrity.dart';

/// Typed views over the dispatcher result payloads produced by
/// `communication/dispatcher.py` -> `analysis/*`.
///
/// Every variant keeps [raw] so forward-compatible fields added by the backend
/// survive into export and detail views instead of being silently dropped.
sealed class AnalysisResult {
  const AnalysisResult({required this.raw});

  final Map<String, dynamic> raw;

  String get action => asString(raw['action'], fallback: 'unknown');
  String get message => asString(raw['message']);

  /// Collector-declared completeness. `complete == false` means the observation
  /// is partial; the UI must say so rather than implying full coverage.
  bool? get complete => asBoolOrNull(raw['complete']);
  bool get truncated => asBool(raw['truncated']);
  int? get skippedCount => asIntOrNull(raw['skipped_count']);
  List<String> get warnings => asStringList(raw['warnings']);

  static AnalysisResult? fromJson(Map<String, dynamic>? json) {
    if (json == null || json.isEmpty) return null;
    return switch (asStringOrNull(json['action'])) {
      'hash' => HashResult(raw: json),
      'encrypt' || 'decrypt' => EvidenceProtectionResult(raw: json),
      'system_info' => SystemInfoResult(raw: json),
      'processes' => ProcessesResult(raw: json),
      'list' => ListResult(raw: json),
      'search' => SearchResult(raw: json),
      _ => UnknownResult(raw: json),
    };
  }
}

class HashResult extends AnalysisResult {
  const HashResult({required super.raw});

  String get target => asString(raw['target']);
  String get filename => asString(raw['filename']);
  String get absolutePath => asString(raw['absolute_path']);
  String get algorithm => asString(raw['algorithm'], fallback: 'UNKNOWN');
  String get digest => asString(raw['hash']);
  int? get sizeBytes => asIntOrNull(raw['size_bytes']);
  String? get modified => asStringOrNull(raw['modified']);

  /// Null when the filesystem does not expose a birth time. Not a zero date.
  String? get created => asStringOrNull(raw['created']);

  /// Linux ctime. Explicitly *not* creation time.
  String? get metadataChanged => asStringOrNull(raw['metadata_changed']);

  String get verificationState => asString(raw['verification_state']);
  IntegrityCheck get integrityCheck =>
      IntegrityCheck.fromJson(asMap(raw['integrity_check']));
  IntegrityHistory get integrityHistory =>
      IntegrityHistory.fromJson(asMap(raw['integrity_history']));
  PreviousHash? get previousHash {
    final value = asMapOrNull(raw['previous_hash']);
    return value == null ? null : PreviousHash.fromJson(value);
  }

  List<Indicator> get indicators => Indicator.listFrom(raw['indicators']);
}

/// The legacy `ENCRYPT` action. Destructive and in-place; the UI treats it as a
/// guarded evidence-handling utility, never as evidence protection.
class EvidenceProtectionResult extends AnalysisResult {
  const EvidenceProtectionResult({required super.raw});

  String get path => asString(raw['path']);
  String get status => asString(raw['status']);
}

class SystemInfoResult extends AnalysisResult {
  const SystemInfoResult({required super.raw});

  String get hostname => asString(raw['hostname']);
  String get os => asString(raw['os']);
  String get osRelease => asString(raw['os_release']);
  String get osVersion => asString(raw['os_version']);
  String get architecture => asString(raw['architecture']);
  String get processor => asString(raw['processor']);
  int? get cpuLogicalCores => asIntOrNull(raw['cpu_logical_cores']);
  int? get cpuPhysicalCores => asIntOrNull(raw['cpu_physical_cores']);
  double? get cpuPercent => asDoubleOrNull(raw['cpu_percent']);
  String get pythonRuntime => asString(raw['python_runtime']);
  String get platformString => asString(raw['platform_string']);
  double? get memoryTotalGb => asDoubleOrNull(raw['memory_total_gb']);
  double? get memoryAvailableGb => asDoubleOrNull(raw['memory_available_gb']);
  double? get memoryUsedPercent => asDoubleOrNull(raw['memory_used_percent']);
  double? get diskTotalGb => asDoubleOrNull(raw['disk_total_gb']);
  double? get diskUsedPercent => asDoubleOrNull(raw['disk_used_percent']);
  String? get bootTime => asStringOrNull(raw['boot_time']);
  int? get uptimeSeconds => asIntOrNull(raw['uptime_seconds']);
  String? get monitoringNote => asStringOrNull(raw['monitoring_note']);
  String? get collectedAt => asStringOrNull(raw['collected_at']);
}

class ProcessObservation {
  const ProcessObservation({
    required this.pid,
    required this.name,
    required this.username,
    required this.status,
    required this.memoryPercent,
    required this.cpuPercent,
    required this.created,
  });

  final int? pid;
  final String name;
  final String username;
  final String status;

  /// Null means unavailable. The backend contract forbids rendering null as 0.
  final double? memoryPercent;

  /// Always null in this snapshot collector: no interval was sampled.
  final double? cpuPercent;
  final String? created;

  factory ProcessObservation.fromJson(Map<String, dynamic> json) => ProcessObservation(
        pid: asIntOrNull(json['pid']),
        name: asString(json['name'], fallback: 'unknown'),
        username: asString(json['username'], fallback: 'n/a'),
        status: asString(json['status'], fallback: 'unknown'),
        memoryPercent: asDoubleOrNull(json['memory_percent']),
        cpuPercent: asDoubleOrNull(json['cpu_percent']),
        created: asStringOrNull(json['created']),
      );
}

class ProcessesResult extends AnalysisResult {
  const ProcessesResult({required super.raw});

  int? get processCount => asIntOrNull(raw['process_count']);
  int? get returnedCount => asIntOrNull(raw['returned_count']);
  String? get collectedAt => asStringOrNull(raw['collected_at']);
  List<ProcessObservation> get processes => asMapList(raw['processes'])
      .map(ProcessObservation.fromJson)
      .toList(growable: false);
}

class DirectoryEntry {
  const DirectoryEntry({
    required this.name,
    required this.path,
    required this.isDirectory,
    required this.sizeBytes,
    required this.modified,
    required this.indicators,
  });

  final String name;
  final String path;
  final bool isDirectory;
  final int? sizeBytes;
  final String? modified;
  final List<Indicator> indicators;

  factory DirectoryEntry.fromJson(Map<String, dynamic> json) => DirectoryEntry(
        name: asString(json['name']),
        path: asString(json['path']),
        isDirectory: asStringOrNull(json['type']) == 'directory',
        sizeBytes: asIntOrNull(json['size_bytes']),
        modified: asStringOrNull(json['modified']),
        indicators: Indicator.listFrom(json['indicators']),
      );
}

class ListResult extends AnalysisResult {
  const ListResult({required super.raw});

  String get target => asString(raw['target']);
  int? get entryCount => asIntOrNull(raw['entry_count']);
  int? get returnedCount => asIntOrNull(raw['returned_count']);
  int? get entriesScanned => asIntOrNull(raw['entries_scanned']);
  List<DirectoryEntry> get entries =>
      asMapList(raw['entries']).map(DirectoryEntry.fromJson).toList(growable: false);
}

class SearchResult extends AnalysisResult {
  const SearchResult({required super.raw});

  String get searchTarget => asString(raw['search_target']);
  String get searchDirectory => asString(raw['search_directory']);
  int? get matchCount => asIntOrNull(raw['match_count']);
  int? get entriesScanned => asIntOrNull(raw['entries_scanned']);
  List<DirectoryEntry> get matches =>
      asMapList(raw['results']).map(DirectoryEntry.fromJson).toList(growable: false);
}

/// An action this client build does not have a dedicated renderer for. Shown as
/// structured JSON rather than hidden, so a newer backend is never misreported.
class UnknownResult extends AnalysisResult {
  const UnknownResult({required super.raw});
}
