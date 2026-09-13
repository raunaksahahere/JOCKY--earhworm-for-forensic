import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/config/app_config.dart';
import '../../core/theme/tokens.dart';
import '../../core/utils/format.dart';
import '../../models/executions/execution_record.dart';
import '../../models/results/analysis_result.dart';
import '../../services/backend/backend_supervisor.dart';
import '../../state/providers.dart';
import '../../widgets/empty_state.dart';
import '../../widgets/failure_view.dart';
import '../../widgets/mono_value.dart';
import '../../widgets/panel.dart';
import '../../widgets/results/result_view.dart';
import '../../widgets/status_chip.dart';

/// Three separate things, deliberately not merged:
///   1. Backend readiness — what the engine reports about itself right now.
///   2. Application status — what this client knows about its own state.
///   3. Host observations — what the engine last collected about the machine,
///      shown with its collection time so it is never mistaken for live data.
class SystemStatusScreen extends ConsumerWidget {
  const SystemStatusScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(backendControllerProvider);
    final settings = ref.watch(settingsControllerProvider);
    final recordsState = ref.watch(recordsControllerProvider);
    final reference = ref.watch(commandReferenceProvider);

    // The most recent host observation this workstation holds, if any.
    final lastSystemInfo = ref.watch(executionHistoryProvider).where(
          (e) => e.report?.result is SystemInfoResult,
        ).firstOrNull;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(JockySpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _backendPanel(context, ref, status, reference, settings.displayUtc),
          const SizedBox(height: JockySpace.lg),
          _applicationPanel(context, ref, recordsState, settings.displayUtc),
          const SizedBox(height: JockySpace.lg),
          _hostPanel(context, ref, lastSystemInfo, settings.displayUtc),
        ],
      ),
    );
  }

  Widget _backendPanel(
    BuildContext context,
    WidgetRef ref,
    BackendStatus status,
    AsyncValue<dynamic> reference,
    bool displayUtc,
  ) {
    final controller = ref.read(backendControllerProvider.notifier);
    final schemaVersion = reference.value?.$1.schemaVersion;

    final (tone, label) = switch (status.phase) {
      BackendPhase.ready => (StatusTone.ok, 'Ready'),
      BackendPhase.starting || BackendPhase.resolving => (StatusTone.info, 'Starting'),
      BackendPhase.degraded => (StatusTone.warn, 'Degraded'),
      BackendPhase.stopping => (StatusTone.warn, 'Stopping'),
      BackendPhase.stopped => (StatusTone.danger, 'Stopped'),
      BackendPhase.unavailable => (StatusTone.danger, 'Unreachable'),
      BackendPhase.idle => (StatusTone.neutral, 'Not yet probed'),
    };

    return Panel(
      title: 'Backend readiness',
      subtitle: 'What the engine reports about itself',
      actions: [
        OutlinedButton.icon(
          onPressed: controller.refresh,
          icon: const Icon(Icons.refresh, size: 14),
          label: const Text('Probe now'),
        ),
        const SizedBox(width: JockySpace.sm),
        OutlinedButton.icon(
          onPressed: status.isReady ? null : controller.start,
          icon: const Icon(Icons.play_arrow_rounded, size: 14),
          label: const Text('Start engine'),
        ),
        const SizedBox(width: JockySpace.sm),
        OutlinedButton.icon(
          onPressed: controller.restart,
          icon: const Icon(Icons.restart_alt, size: 14),
          label: const Text('Restart'),
        ),
      ],
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              StatusChip(label: label, tone: tone),
              const SizedBox(width: JockySpace.sm),
              if (status.managedByClient)
                const StatusChip(
                  label: 'started by this client',
                  tone: StatusTone.neutral,
                  dense: true,
                  icon: Icons.link,
                )
              else if (status.phase == BackendPhase.ready)
                const StatusChip(
                  label: 'external process',
                  tone: StatusTone.neutral,
                  dense: true,
                  icon: Icons.open_in_new,
                  tooltip: 'This engine was already running. The client adopted it and will '
                      'not terminate it.',
                ),
            ],
          ),
          if (status.failure != null) ...[
            const SizedBox(height: JockySpace.md),
            FailureView(failure: status.failure!, onRetry: controller.refresh),
          ],
          const SizedBox(height: JockySpace.lg),
          DataField(label: 'Endpoint', value: status.origin ?? AppConfig.defaultHost),
          DataField(
            label: 'Last healthy reply',
            child: status.lastHealthyAt == null
                ? const _NotReported(
                    reason: 'This client has not received a successful /health reply.')
                : Text(
                    '${formatTimestamp(status.lastHealthyAt, utc: displayUtc)} '
                    '(${formatRelative(status.lastHealthyAt)})',
                    style: const TextStyle(fontSize: 12.5),
                  ),
          ),
          DataField(label: 'Engine status text', value: status.detail, mono: false),
          DataField(
            label: 'Command schema',
            child: schemaVersion == null
                ? const _NotReported(reason: 'GET /commands has not been read yet.')
                : Row(
                    children: [
                      Text('v$schemaVersion', style: const TextStyle(fontSize: 12.5)),
                      const SizedBox(width: JockySpace.sm),
                      if (schemaVersion != ClientBuild.supportedCommandSchema)
                        const StatusChip(
                          label: 'client targets v1',
                          tone: StatusTone.warn,
                          dense: true,
                        ),
                    ],
                  ),
          ),
          const _DurableBackendStatus(),
          DataField(
            label: 'Permission gaps',
            child: const _NotReported(
              reason: 'The backend reports permission problems per command (permission_denied) '
                  'and as collector warnings. It publishes no standing permission inventory.',
            ),
          ),
          const SizedBox(height: JockySpace.md),
          SectionLabel('Process supervision'),
          DataField(label: 'Executable', value: status.executablePath ?? 'not resolved'),
          DataField(
            label: 'Process id',
            value: status.processId?.toString() ?? 'not managed by this client',
          ),
          if (status.exitCode != null)
            DataField(label: 'Last exit code', value: '${status.exitCode}'),
          const SizedBox(height: JockySpace.sm),
          _diagnostics(context, controller.diagnosticLog),
        ],
      ),
    );
  }

  Widget _diagnostics(BuildContext context, List<String> log) {
    return ExpansionTile(
      title: const Text('Engine diagnostic output', style: TextStyle(fontSize: 12.5)),
      subtitle: const Text(
        'Captured stdout and stderr. Diagnostics only — never parsed as a protocol.',
        style: TextStyle(fontSize: 11, color: JockyColors.textFaint),
      ),
      tilePadding: EdgeInsets.zero,
      shape: const Border(),
      collapsedShape: const Border(),
      children: [
        Container(
          width: double.infinity,
          height: 160,
          padding: const EdgeInsets.all(JockySpace.md),
          decoration: BoxDecoration(
            color: JockyColors.canvas,
            border: Border.all(color: JockyColors.border),
            borderRadius: BorderRadius.circular(JockyRadius.md),
          ),
          child: log.isEmpty
              ? const Text(
                  'No output captured. The engine was not started by this client, or it has '
                  'written nothing yet.',
                  style: TextStyle(fontSize: 11.5, color: JockyColors.textFaint),
                )
              : Scrollbar(
                  child: SingleChildScrollView(
                    reverse: true,
                    child: SelectableText(
                      log.join('\n'),
                      style: const TextStyle(
                        fontFamily: JockyType.mono,
                        fontSize: 10.5,
                        height: 1.5,
                        color: JockyColors.textMuted,
                      ),
                    ),
                  ),
                ),
        ),
      ],
    );
  }

  Widget _applicationPanel(
    BuildContext context,
    WidgetRef ref,
    RecordsState recordsState,
    bool displayUtc,
  ) {
    final executions = recordsState.records.executions;

    return Panel(
      title: 'Application status',
      subtitle: 'This desktop client',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          DataField(label: 'Client', value: '${ClientBuild.name} ${ClientBuild.version}'),
          DataField(
            label: 'Platform',
            value: '${Platform.operatingSystem} ${Platform.operatingSystemVersion}',
          ),
          DataField(label: 'Dart runtime', value: Platform.version.split(' ').first),
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
                    elide: 70,
                  ),
                ),
              ],
            ),
          ),
          DataField(
            label: 'Records held',
            mono: false,
            value: '${recordsState.records.investigations.length} case(s), '
                '${executions.length} execution(s), '
                '${executions.where((e) => e.report != null).length} report(s)',
          ),
          DataField(
            label: 'Last submission',
            child: executions.isEmpty
                ? const _NotReported(reason: 'No command has been submitted in any session.')
                : Text(
                    formatTimestamp(executions.first.submittedAt, utc: displayUtc),
                    style: const TextStyle(fontSize: 12.5),
                  ),
          ),
          if (recordsState.storeFailure != null) ...[
            const SizedBox(height: JockySpace.md),
            FailureView(failure: recordsState.storeFailure!),
          ],
        ],
      ),
    );
  }

  Widget _hostPanel(
    BuildContext context,
    WidgetRef ref,
    ExecutionRecord? lastSystemInfo,
    bool displayUtc,
  ) {
    final result = lastSystemInfo?.report?.result;

    return Panel(
      title: 'Host observations',
      subtitle: 'Collected by the engine — a snapshot, not a live feed',
      actions: [
        FilledButton.icon(
          onPressed: () => ref
              .read(executionControllerProvider.notifier)
              .execute('SYSTEM INFO', origin: ExecutionOrigin.guidedTool),
          icon: const Icon(Icons.refresh, size: 14),
          label: const Text('Observe the host'),
        ),
      ],
      child: result is! SystemInfoResult
          ? const EmptyState(
              icon: Icons.monitor_heart_outlined,
              title: 'No host observation collected',
              description:
                  'Run SYSTEM INFO to collect read-only host facts. Until then this client has '
                  'nothing to report and will not display placeholder values.',
              compact: true,
            )
          : Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Container(
                  padding: const EdgeInsets.all(JockySpace.md),
                  decoration: BoxDecoration(
                    color: JockyColors.surfaceRaised,
                    border: Border.all(color: JockyColors.border),
                    borderRadius: BorderRadius.circular(JockyRadius.md),
                  ),
                  child: Row(
                    children: [
                      const Icon(Icons.schedule, size: 14, color: JockyColors.textMuted),
                      const SizedBox(width: JockySpace.sm),
                      Expanded(
                        child: Text(
                          'Collected ${formatIsoTimestamp(result.collectedAt, utc: displayUtc)} '
                          '(${formatRelative(lastSystemInfo?.submittedAt)}). '
                          'These values describe that moment, not now.',
                          style: const TextStyle(fontSize: 11.5, color: JockyColors.textMuted),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: JockySpace.lg),
                SystemInfoResultView(result: result, displayUtc: displayUtc),
              ],
            ),
    );
  }
}

class _NotReported extends StatelessWidget {
  const _NotReported({required this.reason});

  final String reason;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: reason,
      child: const Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.help_outline, size: 12, color: JockyColors.textFaint),
          SizedBox(width: 5),
          Flexible(
            child: Text(
              'not reported by backend',
              style: TextStyle(fontSize: 12, color: JockyColors.textFaint),
            ),
          ),
        ],
      ),
    );
  }
}

class _DurableBackendStatus extends ConsumerWidget {
  const _DurableBackendStatus();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(durableStatusProvider);
    return status.when(
      loading: () => const Text('Loading storage readiness…'),
      error: (error, _) => const Text('Backend version and storage readiness are not reported until an authenticated session is ready.'),
      data: (data) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        DataField(label: 'Backend version', value: '${data['versions']['backend']}'),
        DataField(label: 'API version', value: '${data['versions']['api']}'),
        DataField(label: 'Storage mode', value: '${data['storage']['mode']}'),
        DataField(label: 'Workspace', value: '${data['storage']['path']}', copyable: true),
        DataField(label: 'Storage readiness', value: data['storage']['error']?.toString() ?? 'Ready'),
        DataField(label: 'Free bytes', value: '${data['storage']['free_bytes']}'),
      ]),
    );
  }
}
final durableStatusProvider = FutureProvider.autoDispose((ref) async {
  ref.watch(backendReadyProvider);
  return ref.read(apiClientProvider).jsonRequest('/api/v1/status');
});
