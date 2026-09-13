import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import '../../core/utils/json.dart';
import '../../models/settings/workstation_settings.dart';

abstract class SettingsStore {
  static const fileName = 'settings.json';

  Future<WorkstationSettings> load();
  Future<void> save(WorkstationSettings settings);
  Future<String> location();
}

/// Settings failures are never fatal: a client that cannot read its own
/// preferences still has to connect to the engine, so defaults are used and
/// the condition is surfaced in Settings rather than thrown at startup.
class FileSettingsStore implements SettingsStore {
  FileSettingsStore({Future<Directory> Function()? directoryResolver})
      : _directoryResolver = directoryResolver ?? getApplicationSupportDirectory;

  final Future<Directory> Function() _directoryResolver;

  Future<File> _resolveFile() async {
    final dir = await _directoryResolver();
    await dir.create(recursive: true);
    return File('${dir.path}${Platform.pathSeparator}${SettingsStore.fileName}');
  }

  @override
  Future<String> location() async => (await _resolveFile()).path;

  @override
  Future<WorkstationSettings> load() async {
    try {
      final file = await _resolveFile();
      if (!file.existsSync()) return WorkstationSettings.defaults;
      final decoded = jsonDecode(await file.readAsString());
      if (decoded is! Map) return WorkstationSettings.defaults;
      return WorkstationSettings.fromJson(asMap(decoded));
    } on Object {
      return WorkstationSettings.defaults;
    }
  }

  @override
  Future<void> save(WorkstationSettings settings) async {
    final file = await _resolveFile();
    final temp = File('${file.path}.tmp');
    await temp.writeAsString(
      const JsonEncoder.withIndent('  ').convert(settings.toJson()),
      flush: true,
    );
    await temp.rename(file.path);
  }
}

class InMemorySettingsStore implements SettingsStore {
  InMemorySettingsStore([this._settings = WorkstationSettings.defaults]);

  WorkstationSettings _settings;

  @override
  Future<WorkstationSettings> load() async => _settings;

  @override
  Future<void> save(WorkstationSettings settings) async => _settings = settings;

  @override
  Future<String> location() async => '(in memory — not persisted)';
}
