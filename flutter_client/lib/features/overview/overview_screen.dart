import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/navigation.dart';
import '../../core/theme/tokens.dart';
import '../../core/utils/format.dart';
import '../../models/executions/execution_record.dart';
import '../../services/backend/backend_supervisor.dart';
import '../../state/providers.dart';
import '../../widgets/data_grid.dart';
import '../../widgets/empty_state.dart';
import '../../widgets/mono_value.dart';
import '../../widgets/panel.dart';
import '../../widgets/status_chip.dart';

/// Operational picture: is the engine ready, what case is open, what has this
/// workstation done recently, and what is currently wrong.
///
/// Every figure here is counted from records this client actually holds or
/// values the engine actually returned. Nothing is estimated.
class OverviewScreen extends ConsumerWidget {
  const OverviewScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(backendControllerProvider);
    final recordsState = ref.watch(recordsControllerProvider);
    final records = recordsState.records;
    final executions = records.executions;
    final settings = ref.watch(settingsControllerProvider);
    final activeCase = records.activeCase;

    final failures = executions
        .where((e) => e.outcome != ExecutionOutcome.completed)
        .take(20)
        .toList(growable: false);
    final partial = executions
        .where((e) => e.report?.result?.complete == false)
        .toList(growable: false);

    return SingleChildScrollView(
      padding: const EdgeInsets.all(JockySpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Card(child: Padding(padding: const EdgeInsets.all(20), child: Wrap(spacing: 16, runSpacing: 12, crossAxisAlignment: WrapCrossAlignment.center, children: [
            const Text('Portable local forensic collection', style: TextStyle(fontSize: 18)),
            FilledButton.icon(onPressed: () => context.go('/device'), icon: const Icon(Icons.manage_search), label: const Text('Analyze This Device')),
            OutlinedButton(onPressed: () => context.go('/device'), child: const Text('Previous investigations')),
          ]))),
          const SizedBox(height: 16),
          _ProblemStrip(
            status: status,
            storeDurable: recordsState.isDurable,
            storeMessage: recordsState.storeFailure?.message,
            partialCount: partial.length,
            failureCount: failures.length,
          ),
          const SizedBox(height: JockySpace.lg),
          LayoutBuilder(
            builder: (context, constraints) {
              final columns = constraints.maxWidth >= 1180 ? 4 : 2;
              final width =
                  (constraints.maxWidth - (columns - 1) * JockySpace.md) / columns;
              return Wrap(
                spacing: JockySpace.md,
                runSpacing: JockySpace.md,
                children: [
                  SizedBox(
                    width: width,
                    child: _Metric(
                      label: 'Engine',
                      value: switch (status.phase) {
                        BackendPhase.ready => 'Ready',
                        BackendPhase.starting || BackendPhase.resolving => 'Starting',
                        BackendPhase.degraded => 'Degraded',
                        BackendPhase.stopping => 'Stopping',
                        BackendPhase.stopped => 'Stopped',
                        BackendPhase.unavailable => 'Offline',
                        BackendPhase.idle => 'Unknown',
                      },
                      detail: status.origin ?? 'no endpoint configured',
                      tone: status.isReady ? StatusTone.ok : StatusTone.danger,
                      onTap: () => context.go(JockyDestination.systemStatus.path),
                    ),
                  ),
                  SizedBox(
                    width: width,
                    child: _Metric(
                      label: 'Open cases',
                      value: '${records.investigations.where((c) => c.isOpen).length}',
                      detail: '${records.investigations.length} recorded in total',
                      tone: StatusTone.accent,
                      onTap: () => context.go(JockyDestination.investigations.path),
                    ),
                  ),
                  SizedBox(
                    width: width,
                    child: _Metric(
                      label: 'Evidence sources',
                      value: '${records.investigations.fold<int>(
                        0,
                        (sum, c) => sum + c.evidence.length,
                      )}',
                      detail: activeCase == null
                          ? 'across all recorded cases'
                          : '${activeCase.evidence.length} in the active case',
                      tone: StatusTone.accent,
                      onTap: () => context.go(JockyDestination.investigations.path),
                    ),
                  ),
                  SizedBox(
                    width: width,
                    child: _Metric(
                      label: 'Executions recorded',
                      value: '${executions.length}',
                      detail: '${executions.where((e) => e.report != null).length} '
                          'engine reports held',
                      tone: StatusTone.accent,
                      onTap: () => context.go(JockyDestination.history.path),
                    ),
                  ),
                ],
              );
            },
          ),
          const SizedBox(height: JockySpace.lg),
          LayoutBuilder(
            builder: (context, constraints) {
              final stacked = constraints.maxWidth < 1100;
              final activity = SizedBox(
                height: 340,
                child: _RecentExecutions(
                  executions: executions.take(40).toList(growable: false),
                  displayUtc: settings.displayUtc,
                ),
              );
              final side = SizedBox(
                height: 340,
                child: _CaseAndReports(displayUtc: settings.displayUtc),
              );
              return stacked
                  ? Column(children: [activity, const SizedBox(height: JockySpace.lg), side])
                  : Row(
                      // The children carry their own height; stretching here
                      // would demand an infinite one inside the scroll view.
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(flex: 3, child: activity),
                        const SizedBox(width: JockySpace.lg),
                        Expanded(flex: 2, child: side),
                      ],
                    );
            },
          ),
          const SizedBox(height: JockySpace.lg),
          _QuickEntry(),
        ],
      ),
    );
  }
}

class _ProblemStrip extends StatelessWidget {
  const _ProblemStrip({
    required this.status,
    required this.storeDurable,
    required this.storeMessage,
    required this.partialCount,
    required this.failureCount,
  });

  final BackendStatus status;
  final bool storeDurable;
  final String? storeMessage;
  final int partialCount;
  final int failureCount;

  @override
  Widget build(BuildContext context) {
    final problems = <(StatusTone, String, String)>[
      if (!status.isReady)
        (
          StatusTone.danger,
          'Engine not ready',
          status.failure?.message ?? status.detail ?? 'No engine is answering.',
        ),
      if (!storeDurable)
        (
          StatusTone.warn,
          'This session is not being recorded',
          storeMessage ?? 'The local record store is unavailable.',
        ),
      if (partialCount > 0)
        (
          StatusTone.warn,
          '$partialCount partial observation(s)',
          'A collector reported incomplete coverage. Review the warnings on those reports.',
        ),
      if (failureCount > 0)
        (
          StatusTone.info,
          '$failureCount failed or abandoned execution(s)',
          'Reviewable in History with the engine error code that was returned.',
        ),
    ];

    if (problems.isEmpty) {
      return Panel(
        child: Row(
          children: [
            const StatusChip(label: 'No outstanding problems', tone: StatusTone.ok),
            const SizedBox(width: JockySpace.md),
            Expanded(
              child: Text(
                'The engine is ready and this workstation recorded every submission.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          ],
        ),
      );
    }

    return Panel(
      title: 'Attention',
      subtitle: '${problems.length} item(s) need a decision',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (final (tone, title, detail) in problems)
            Padding(
              padding: const EdgeInsets.only(bottom: JockySpace.sm),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(statusIcon(tone), size: 14, color: statusColor(tone)),
                  const SizedBox(width: JockySpace.sm),
                  // Proportional rather than fixed, so the strip stays readable
                  // when the window is narrow.
                  Expanded(
                    flex: 2,
                    child: Text(
                      title,
                      style: TextStyle(
                        fontSize: 12.5,
                        fontWeight: FontWeight.w600,
                        color: statusColor(tone),
                      ),
                    ),
                  ),
                  const SizedBox(width: JockySpace.md),
                  Expanded(
                    flex: 3,
                    child: Text(
                      detail,
                      style: const TextStyle(
                        fontSize: 12,
                        height: 1.45,
                        color: JockyColors.textMuted,
                      ),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({
    required this.label,
    required this.value,
    required this.detail,
    required this.tone,
    this.onTap,
  });

  final String label;
  final String value;
  final String detail;
  final StatusTone tone;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(JockyRadius.lg),
      child: Container(
        padding: const EdgeInsets.all(JockySpace.lg),
        decoration: BoxDecoration(
          color: JockyColors.surface,
          border: Border.all(color: JockyColors.border),
          borderRadius: BorderRadius.circular(JockyRadius.lg),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(label.toUpperCase(), style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: JockySpace.sm),
            Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Container(width: 3, height: 18, color: statusColor(tone)),
                const SizedBox(width: JockySpace.sm),
                Flexible(
                  child: Text(
                    value,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 21,
                      fontWeight: FontWeight.w600,
                      letterSpacing: -0.5,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 5),
            Text(
              detail,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 11, height: 1.4, color: JockyColors.textFaint),
            ),
          ],
        ),
      ),
    );
  }
}

class _RecentExecutions extends StatelessWidget {
  const _RecentExecutions({required this.executions, required this.displayUtc});

  final List<ExecutionRecord> executions;
  final bool displayUtc;

  @override
  Widget build(BuildContext context) {
    return Panel(
      title: 'Recent executions',
      subtitle: 'Submitted by this workstation',
      padding: EdgeInsets.zero,
      actions: [
        TextButton(
          onPressed: () => context.go(JockyDestination.history.path),
          child: const Text('Full history'),
        ),
      ],
      child: DataGrid<ExecutionRecord>(
        rows: executions,
        rowKey: (row) => row.id,
        minWidth: 640,
        onSelect: (row) => context.go('${JockyDestination.reports.path}/${row.id}'),
        emptyState: EmptyState(
          icon: Icons.playlist_add_outlined,
          title: 'No commands submitted yet',
          description:
              'Run an observation from the Command Center or Tools and it will appear here '
              'with its engine report.',
          compact: true,
          action: FilledButton.icon(
            onPressed: () => context.go(JockyDestination.commandCenter.path),
            icon: const Icon(Icons.terminal_outlined, size: 14),
            label: const Text('Open Command Center'),
          ),
        ),
        columns: [
          GridColumn(
            label: 'State',
            width: 120,
            cell: (row) => _outcomeChip(row),
          ),
          GridColumn(
            label: 'Command',
            flex: 4,
            cell: (row) => MonoValue(row.commandText, fontSize: 11.5, elide: 60),
          ),
          GridColumn(
            label: 'Engine',
            width: 90,
            alignRight: true,
            cell: (row) => MonoValue(
              formatDurationMs(row.engineElapsedMs),
              fontSize: 11,
              color: JockyColors.textMuted,
            ),
          ),
          GridColumn(
            label: 'When',
            width: 110,
            alignRight: true,
            cell: (row) => Tooltip(
              message: formatTimestamp(row.submittedAt, utc: displayUtc),
              child: Text(
                formatRelative(row.submittedAt),
                style: const TextStyle(fontSize: 11, color: JockyColors.textMuted),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

Widget _outcomeChip(ExecutionRecord record) => StatusChip(
      dense: true,
      label: switch (record.outcome) {
        ExecutionOutcome.completed => 'completed',
        ExecutionOutcome.failed => record.failureCode ?? 'failed',
        ExecutionOutcome.abandoned => 'abandoned',
      },
      tone: switch (record.outcome) {
        ExecutionOutcome.completed => StatusTone.ok,
        ExecutionOutcome.failed => StatusTone.danger,
        ExecutionOutcome.abandoned => StatusTone.neutral,
      },
      tooltip: record.summary,
    );

class _CaseAndReports extends ConsumerWidget {
  const _CaseAndReports({required this.displayUtc});

  final bool displayUtc;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final activeCase = ref.watch(activeCaseProvider);
    final reports = ref.watch(reportArchiveProvider).take(6).toList(growable: false);

    return Panel(
      title: 'Active case',
      subtitle: activeCase?.reference ?? 'Commands are attributed to the selected case',
      padding: EdgeInsets.zero,
      actions: [
        TextButton(
          onPressed: () => context.go(JockyDestination.investigations.path),
          child: const Text('Workspace'),
        ),
      ],
      child: ListView(
        padding: const EdgeInsets.all(JockySpace.lg),
        children: [
          if (activeCase == null)
            const EmptyState(
              icon: Icons.folder_off_outlined,
              title: 'No active case',
              description:
                  'Executions are still recorded, but without case attribution. Open a case '
                  'from the Investigations workspace.',
              compact: true,
            )
          else ...[
            DataField(label: 'Title', value: activeCase.title, mono: false),
            DataField(
              label: 'Opened',
              value: formatTimestamp(activeCase.openedAt, utc: displayUtc),
              mono: false,
            ),
            DataField(
              label: 'Evidence sources',
              value: '${activeCase.evidence.length}',
              mono: false,
            ),
            DataField(
              label: 'Executions',
              value: '${ref.watch(executionHistoryProvider).where(
                    (e) => e.caseId == activeCase.id,
                  ).length}',
              mono: false,
            ),
          ],
          const SizedBox(height: JockySpace.md),
          SectionLabel('Recent reports'),
          if (reports.isEmpty)
            const Text(
              'No engine reports held yet.',
              style: TextStyle(fontSize: 12, color: JockyColors.textFaint),
            )
          else
            for (final record in reports)
              InkWell(
                onTap: () => context.go('${JockyDestination.reports.path}/${record.id}'),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 5),
                  child: Row(
                    children: [
                      SizedBox(
                        width: 106,
                        child: MonoValue(
                          record.reportId,
                          fontSize: 11,
                          color: JockyColors.accent,
                        ),
                      ),
                      Expanded(
                        child: Text(
                          record.action ?? 'unparsed',
                          style: const TextStyle(fontSize: 11.5, color: JockyColors.textMuted),
                        ),
                      ),
                      Text(
                        formatRelative(record.submittedAt),
                        style: const TextStyle(fontSize: 10.5, color: JockyColors.textFaint),
                      ),
                    ],
                  ),
                ),
              ),
        ],
      ),
    );
  }
}

class _QuickEntry extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Panel(
      title: 'Start an observation',
      subtitle: 'Both routes submit the same command to the same engine',
      child: Wrap(
        spacing: JockySpace.md,
        runSpacing: JockySpace.md,
        children: [
          FilledButton.icon(
            onPressed: () => context.go(JockyDestination.commandCenter.path),
            icon: const Icon(Icons.terminal_outlined, size: 15),
            label: const Text('Command Center'),
          ),
          OutlinedButton.icon(
            onPressed: () => context.go(JockyDestination.tools.path),
            icon: const Icon(Icons.construction_outlined, size: 15),
            label: const Text('Guided tools'),
          ),
          OutlinedButton.icon(
            onPressed: () => context.go(JockyDestination.investigations.path),
            icon: const Icon(Icons.create_new_folder_outlined, size: 15),
            label: const Text('Open a case'),
          ),
        ],
      ),
    );
  }
}
