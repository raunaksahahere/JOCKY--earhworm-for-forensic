import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/config/app_config.dart';
import '../../core/errors/failure.dart';
import '../../core/theme/tokens.dart';
import '../../models/executions/execution_record.dart';
import '../../state/providers.dart';
import '../../widgets/failure_view.dart';
import '../../widgets/mono_value.dart';
import '../../widgets/panel.dart';
import '../../widgets/status_chip.dart';

/// Client preferences.
///
/// Nothing here changes how the engine collects, validates or reports. Engine
/// configuration lives with the engine; exposing it from a desktop client would
/// let a display preference alter forensic behaviour.
class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  late final TextEditingController _host;
  late final TextEditingController _port;
  String? _message;
  JockyFailure? _failure;

  @override
  void initState() {
    super.initState();
    final settings = ref.read(settingsControllerProvider);
    _host = TextEditingController(text: settings.host);
    _port = TextEditingController(text: '${settings.port}');
  }

  @override
  void dispose() {
    _host.dispose();
    _port.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final settings = ref.watch(settingsControllerProvider);
    final controller = ref.read(settingsControllerProvider.notifier);
    final recordsState = ref.watch(recordsControllerProvider);

    return SingleChildScrollView(
      padding: const EdgeInsets.all(JockySpace.lg),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 880),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Panel(title: 'Investigation storage', subtitle: 'Restart JOCKY after changing the workspace. Existing data is never moved automatically.', child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(settings.portableWorkspace == null ? 'System application data' : 'Portable workspace: ${settings.portableWorkspace}'),
                Wrap(spacing: 12, children: [
                  TextButton(onPressed: () async {
                    final path = await ref.read(fileSelectionProvider).pickDirectory(confirmButtonText: 'Use portable workspace');
                    if (path != null) await controller.update((s) => s.copyWith(portableWorkspace: path));
                  }, child: const Text('Choose portable workspace')),
                  TextButton(onPressed: () => controller.update((s) => s.copyWith(clearPortableWorkspace: true)), child: const Text('Use system application data')),
                ]),
                TextButton(onPressed: () async {
                  final path = await ref.read(fileSelectionProvider).pickFile(confirmButtonText: 'Import former workstation JSON');
                  if (path == null) return;
                  try {
                    final result = await ref.read(apiClientProvider).jsonRequest('/api/v1/storage/import-workstation', body: {'path': path});
                    await ref.read(recordsControllerProvider.notifier).refresh();
                    if (mounted) setState(() => _message = 'Legacy records imported: $result');
                  } on Object catch (error) {
                    if (mounted) setState(() => _message = 'Import failed; source preserved: $error');
                  }
                }, child: const Text('Import previous workstation records')),
                const Text('Explicit launch configuration JOCKY_WORKSPACE overrides this setting. Stop collection and close JOCKY before removing storage.'),
              ])),
              const SizedBox(height: 16),
              if (_failure != null) ...[
                FailureView(failure: _failure!),
                const SizedBox(height: JockySpace.lg),
              ],
              Panel(
                title: 'Engine connection',
                subtitle: 'The engine observes this host; it is a local service, not a '
                    'remote one',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Expanded(
                          flex: 3,
                          child: _labelled(
                            'Host',
                            TextField(
                              controller: _host,
                              style: const TextStyle(
                                fontFamily: JockyType.mono,
                                fontSize: 12.5,
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(width: JockySpace.md),
                        Expanded(
                          child: _labelled(
                            'Port',
                            TextField(
                              controller: _port,
                              style: const TextStyle(
                                fontFamily: JockyType.mono,
                                fontSize: 12.5,
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(width: JockySpace.md),
                        FilledButton(
                          onPressed: () async {
                            final port = int.tryParse(_port.text.trim());
                            if (port == null || port < 1 || port > 65535) {
                              setState(() => _failure = const JockyFailure(
                                    kind: FailureKind.localStorage,
                                    message: 'The port must be a number between 1 and 65535.',
                                  ));
                              return;
                            }
                            setState(() {
                              _failure = null;
                              _message = null;
                            });
                            await controller.setEndpoint(
                              host: _host.text.trim().isEmpty
                                  ? AppConfig.defaultHost
                                  : _host.text.trim(),
                              port: port,
                            );
                            await ref.read(backendControllerProvider.notifier).refresh();
                            if (mounted) {
                              setState(() => _message = 'Endpoint updated and re-probed.');
                            }
                          },
                          child: const Text('Apply'),
                        ),
                      ],
                    ),
                    if (_host.text.trim() != AppConfig.defaultHost &&
                        _host.text.trim() != 'localhost') ...[
                      const SizedBox(height: JockySpace.md),
                      const CapabilityGap(
                        capability: 'This endpoint is not loopback',
                        explanation:
                            'The backend serves plain HTTP with permissive CORS and no '
                            'authentication. Pointing this client at a non-loopback address '
                            'sends command text and results across the network in the clear.',
                      ),
                    ],
                    const SizedBox(height: JockySpace.lg),
                    _switchRow(
                      'Start the packaged engine automatically',
                      'On launch, resolve and start the bundled engine. When an engine is '
                          'already listening it is adopted instead.',
                      settings.autoStartBackend,
                      controller.setAutoStartBackend,
                    ),
                    const SizedBox(height: JockySpace.md),
                    _labelled(
                      'Engine executable override',
                      Row(
                        children: [
                          Expanded(
                            child: MonoValue(
                              settings.backendExecutableOverride ??
                                  'resolved next to the application bundle',
                              fontSize: 11.5,
                              color: settings.backendExecutableOverride == null
                                  ? JockyColors.textFaint
                                  : JockyColors.text,
                              elide: 70,
                            ),
                          ),
                          const SizedBox(width: JockySpace.sm),
                          OutlinedButton(
                            onPressed: () async {
                              final path =
                                  await ref.read(fileSelectionProvider).pickFile();
                              if (path != null) {
                                await controller.setBackendExecutableOverride(path);
                              }
                            },
                            child: const Text('Choose'),
                          ),
                          if (settings.backendExecutableOverride != null) ...[
                            const SizedBox(width: JockySpace.sm),
                            TextButton(
                              onPressed: () =>
                                  controller.setBackendExecutableOverride(null),
                              child: const Text('Reset'),
                            ),
                          ],
                        ],
                      ),
                    ),
                    const SizedBox(height: JockySpace.lg),
                    _labelled(
                      'Request timeout — ${settings.requestTimeoutSeconds}s',
                      Slider(
                        value: settings.requestTimeoutSeconds.toDouble(),
                        min: 5,
                        max: 180,
                        divisions: 35,
                        label: '${settings.requestTimeoutSeconds}s',
                        onChanged: (value) => controller.setRequestTimeout(value.round()),
                      ),
                    ),
                    const Text(
                      'A timeout abandons this client\'s wait. The engine dispatcher is '
                      'synchronous and has no cancellation endpoint, so an observation may '
                      'still complete after the client stops waiting.',
                      style: TextStyle(fontSize: 11, height: 1.5, color: JockyColors.textFaint),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: JockySpace.lg),
              Panel(
                title: 'Appearance and display',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _switchRow(
                      'Show timestamps in UTC',
                      'Forensic timestamps default to UTC. Turning this off shows local time '
                          'with its offset; the raw value with its original offset stays '
                          'available on every report.',
                      settings.displayUtc,
                      controller.setDisplayUtc,
                    ),
                    const SizedBox(height: JockySpace.md),
                    _switchRow(
                      'Dense table rows',
                      'Compact row height for long evidence and process listings.',
                      settings.denseTables,
                      controller.setDenseTables,
                    ),
                    const SizedBox(height: JockySpace.md),
                    _labelled(
                      'Text scale — ${settings.textScale.toStringAsFixed(2)}×',
                      Slider(
                        value: settings.textScale,
                        min: 0.8,
                        max: 1.6,
                        divisions: 16,
                        label: '${settings.textScale.toStringAsFixed(2)}×',
                        onChanged: controller.setTextScale,
                      ),
                    ),
                    const Text(
                      'Interface theme: dark. This build ships a single high-contrast dark '
                      'palette tuned for long examination sessions.',
                      style: TextStyle(fontSize: 11.5, color: JockyColors.textFaint),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: JockySpace.lg),
              Panel(
                title: 'Export and storage',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _labelled(
                      'Default export location',
                      Row(
                        children: [
                          Expanded(
                            child: MonoValue(
                              settings.exportDirectory ??
                                  'not set — the save dialog chooses',
                              fontSize: 11.5,
                              color: settings.exportDirectory == null
                                  ? JockyColors.textFaint
                                  : JockyColors.text,
                              elide: 70,
                            ),
                          ),
                          const SizedBox(width: JockySpace.sm),
                          OutlinedButton(
                            onPressed: () async {
                              final path =
                                  await ref.read(fileSelectionProvider).pickDirectory();
                              if (path != null) await controller.setExportDirectory(path);
                            },
                            child: const Text('Choose'),
                          ),
                          if (settings.exportDirectory != null) ...[
                            const SizedBox(width: JockySpace.sm),
                            TextButton(
                              onPressed: () => controller.setExportDirectory(null),
                              child: const Text('Clear'),
                            ),
                          ],
                        ],
                      ),
                    ),
                    const SizedBox(height: JockySpace.lg),
                    DataField(
                      label: 'Record store',
                      child: Row(
                        children: [
                          StatusChip(
                            label: recordsState.isDurable ? 'writable' : 'unavailable',
                            tone: recordsState.isDurable ? StatusTone.ok : StatusTone.warn,
                            dense: true,
                          ),
                          const SizedBox(width: JockySpace.sm),
                          Expanded(
                            child: MonoValue(
                              recordsState.storeLocation,
                              fontSize: 11,
                              color: JockyColors.textMuted,
                              elide: 72,
                            ),
                          ),
                        ],
                      ),
                    ),
                    DataField(
                      label: 'Contents',
                      mono: false,
                      value: '${recordsState.records.investigations.length} case(s), '
                          '${recordsState.records.executions.length} execution(s) with their '
                          'engine reports',
                    ),
                    const SizedBox(height: JockySpace.md),
                    Row(
                      children: [
                        OutlinedButton.icon(
                          onPressed: () => _exportAll(recordsState.records.executions),
                          icon: const Icon(Icons.archive_outlined, size: 14),
                          label: const Text('Export all records as JSON'),
                        ),
                        const SizedBox(width: JockySpace.sm),
                        OutlinedButton.icon(
                          style: OutlinedButton.styleFrom(
                            foregroundColor: JockyColors.danger,
                            side: BorderSide(
                              color: JockyColors.danger.withValues(alpha: 0.5),
                            ),
                          ),
                          onPressed: _confirmReset,
                          icon: const Icon(Icons.delete_forever_outlined, size: 14),
                          label: const Text('Reset all local records'),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: JockySpace.lg),
              Panel(
                title: 'Diagnostics and versions',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    DataField(label: 'Client', value: ClientBuild.name, mono: false),
                    DataField(label: 'Client version', value: ClientBuild.version),
                    DataField(
                      label: 'Command schema targeted',
                      value: 'v${ClientBuild.supportedCommandSchema}',
                    ),
                    DataField(
                      label: 'Report schema rendered',
                      value: 'v${ClientBuild.supportedReportSchema}',
                    ),
                    DataField(
                      label: 'Backend version',
                      child: const Tooltip(
                        message: 'GET /health returns only {status, engine}. No version string '
                            'exists in the backend contract.',
                        child: Text(
                          'not reported by backend',
                          style: TextStyle(fontSize: 12, color: JockyColors.textFaint),
                        ),
                      ),
                    ),
                    DataField(
                      label: 'Host platform',
                      value: '${Platform.operatingSystem} '
                          '${Platform.operatingSystemVersion}',
                      mono: false,
                    ),
                    if (ref.read(settingsControllerProvider.notifier).lastError != null)
                      DataField(
                        label: 'Settings write error',
                        value: ref.read(settingsControllerProvider.notifier).lastError,
                      ),
                    const SizedBox(height: JockySpace.md),
                    Row(
                      children: [
                        OutlinedButton.icon(
                          onPressed: () async {
                            await controller.restoreDefaults();
                            if (!mounted) return;
                            _host.text = AppConfig.defaultHost;
                            _port.text = '${AppConfig.defaultPort}';
                            setState(() => _message = 'Settings restored to defaults.');
                          },
                          icon: const Icon(Icons.settings_backup_restore, size: 14),
                          label: const Text('Restore default settings'),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              if (_message != null) ...[
                const SizedBox(height: JockySpace.md),
                Row(
                  children: [
                    const Icon(Icons.check_circle_outline, size: 14, color: JockyColors.ok),
                    const SizedBox(width: JockySpace.sm),
                    Text(
                      _message!,
                      style: const TextStyle(fontSize: 12, color: JockyColors.ok),
                    ),
                  ],
                ),
              ],
              const SizedBox(height: JockySpace.xl),
            ],
          ),
        ),
      ),
    );
  }

  Widget _labelled(String label, Widget child) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: const TextStyle(fontSize: 11.5, color: JockyColors.textMuted),
          ),
          const SizedBox(height: 5),
          child,
        ],
      );

  Widget _switchRow(
    String title,
    String description,
    bool value,
    ValueChanged<bool> onChanged,
  ) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: const TextStyle(fontSize: 12.5)),
              const SizedBox(height: 2),
              Text(
                description,
                style: const TextStyle(
                  fontSize: 11,
                  height: 1.5,
                  color: JockyColors.textFaint,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(width: JockySpace.lg),
        Switch(value: value, onChanged: onChanged),
      ],
    );
  }

  Future<void> _exportAll(List<ExecutionRecord> executions) async {
    setState(() {
      _message = null;
      _failure = null;
    });
    final path = await ref.read(fileSelectionProvider).pickSaveLocation(
          suggestedName: 'jocky-records-'
              '${DateTime.now().toUtc().toIso8601String().split('T').first}.json',
          extension: 'json',
        );
    if (path == null) return;
    try {
      await ref.read(reportExportProvider).writeExecutionBundleJson(path, executions);
      if (mounted) setState(() => _message = 'Records written to $path');
    } on JockyFailure catch (failure) {
      if (mounted) setState(() => _failure = failure);
    }
  }

  Future<void> _confirmReset() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: JockyColors.surface,
        title: const Text('Reset all local records?', style: TextStyle(fontSize: 15)),
        content: const Text(
          'This deletes every case, evidence list, note, execution and engine report this '
          'workstation holds. The engine keeps no copy of any of it. Export first if you need '
          'these records.',
          style: TextStyle(fontSize: 12.5, height: 1.5),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: JockyColors.danger),
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Delete all records'),
          ),
        ],
      ),
    );
    if (confirmed ?? false) {
      await ref.read(recordsControllerProvider.notifier).resetAll();
      if (mounted) setState(() => _message = 'All local records were deleted.');
    }
  }
}
