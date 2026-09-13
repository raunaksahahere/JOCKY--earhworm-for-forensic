import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import '../../core/errors/failure.dart';
import '../../core/utils/json.dart';
import '../../models/cases/investigation.dart';
import '../../models/executions/execution_record.dart';

/// Everything this workstation remembers between sessions.
class WorkstationRecords {
  const WorkstationRecords({
    this.investigations = const [],
    this.executions = const [],
    this.activeCaseId,
  });

  final List<Investigation> investigations;

  /// Newest first.
  final List<ExecutionRecord> executions;
  final String? activeCaseId;

  static const empty = WorkstationRecords();

  Investigation? get activeCase {
    if (activeCaseId == null) return null;
    return investigations.where((c) => c.id == activeCaseId).firstOrNull;
  }

  List<ExecutionRecord> executionsForCase(String caseId) =>
      executions.where((e) => e.caseId == caseId).toList(growable: false);

  WorkstationRecords copyWith({
    List<Investigation>? investigations,
    List<ExecutionRecord>? executions,
    String? activeCaseId,
    bool clearActiveCase = false,
  }) =>
      WorkstationRecords(
        investigations: investigations ?? this.investigations,
        executions: executions ?? this.executions,
        activeCaseId: clearActiveCase ? null : (activeCaseId ?? this.activeCaseId),
      );

  Map<String, dynamic> toJson() => {
        'store_version': RecordStore.storeVersion,
        'active_case_id': activeCaseId,
        'investigations': investigations.map((c) => c.toJson()).toList(),
        'executions': executions.map((e) => e.toJson()).toList(),
      };

  factory WorkstationRecords.fromJson(Map<String, dynamic> json) => WorkstationRecords(
        activeCaseId: asStringOrNull(json['active_case_id']),
        investigations: asMapList(json['investigations'])
            .map(Investigation.fromJson)
            .whereType<Investigation>()
            .toList(growable: false),
        executions: asMapList(json['executions'])
            .map(ExecutionRecord.fromJson)
            .whereType<ExecutionRecord>()
            .toList(growable: false),
      );
}

/// SQLite-backed local workstation contract; see contracts/CLIENT.md.
abstract class RecordStore {
  static const storeVersion = 1;
  static const fileName = 'workstation_records.json';

  Future<WorkstationRecords> load();
  Future<void> save(WorkstationRecords records);

  /// Absolute path of the store, shown in Settings so the analyst knows where
  /// their record of the session lives.
  Future<String> location();
}

class FileRecordStore implements RecordStore {
  FileRecordStore({Future<Directory> Function()? directoryResolver})
      : _directoryResolver = directoryResolver ?? getApplicationSupportDirectory;

  final Future<Directory> Function() _directoryResolver;
  Future<File>? _file;

  Future<File> _resolveFile() {
    return _file ??= () async {
      final dir = await _directoryResolver();
      await dir.create(recursive: true);
      return File('${dir.path}${Platform.pathSeparator}${RecordStore.fileName}');
    }();
  }

  @override
  Future<String> location() async => (await _resolveFile()).path;

  @override
  Future<WorkstationRecords> load() async {
    final File file;
    try {
      file = await _resolveFile();
      if (!file.existsSync()) return WorkstationRecords.empty;
    } on FileSystemException catch (error) {
      throw JockyFailure(
        kind: FailureKind.localStorage,
        message: 'The local record store directory could not be opened.',
        detail: error.message,
      );
    }

    final String text;
    try {
      text = await file.readAsString();
    } on FileSystemException catch (error) {
      throw JockyFailure(
        kind: FailureKind.localStorage,
        message: 'The local record store could not be read.',
        detail: '${error.message} (${file.path})',
      );
    }
    if (text.trim().isEmpty) return WorkstationRecords.empty;

    try {
      final decoded = jsonDecode(text);
      if (decoded is! Map) {
        throw const FormatException('Record store root is not an object');
      }
      return WorkstationRecords.fromJson(asMap(decoded));
    } on FormatException catch (error) {
      // Never silently reset an analyst's history: report it and let the UI
      // offer an explicit, acknowledged reset.
      throw JockyFailure(
        kind: FailureKind.localStorage,
        message: 'The local record store is corrupt and was not loaded. '
            'Existing contents were left untouched.',
        detail: '${error.message} (${file.path})',
      );
    }
  }

  @override
  Future<void> save(WorkstationRecords records) async {
    final file = await _resolveFile();
    final temp = File('${file.path}.tmp');
    try {
      await temp.writeAsString(
        const JsonEncoder.withIndent('  ').convert(records.toJson()),
        flush: true,
      );
      await temp.rename(file.path);
    } on FileSystemException catch (error) {
      throw JockyFailure(
        kind: FailureKind.localStorage,
        message: 'The local record store could not be written; '
            'this session may not be recorded.',
        detail: '${error.message} (${file.path})',
      );
    }
  }
}

/// In-memory store used by tests and by the app when the on-disk store is
/// unavailable, so the session still works without pretending it is durable.
class InMemoryRecordStore implements RecordStore {
  InMemoryRecordStore([this._records = WorkstationRecords.empty]);

  WorkstationRecords _records;

  @override
  Future<WorkstationRecords> load() async => _records;

  @override
  Future<void> save(WorkstationRecords records) async => _records = records;

  @override
  Future<String> location() async => '(in memory — not persisted)';
}
