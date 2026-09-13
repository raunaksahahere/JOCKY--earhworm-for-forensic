import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/navigation.dart';
import '../../app/shortcuts.dart';
import '../../core/errors/failure.dart';
import '../../core/theme/tokens.dart';
import '../../core/utils/format.dart';
import '../../models/executions/execution_record.dart';
import '../../repositories/records_repository.dart';
import '../../state/providers.dart';
import '../../widgets/data_grid.dart';
import '../../widgets/empty_state.dart';
import '../../widgets/failure_view.dart';
import '../../widgets/mono_value.dart';
import '../../widgets/panel.dart';
import '../../widgets/status_chip.dart';

/// Every command this workstation submitted, with what came back.
///
/// "Load into editor" places the command text in the Command Center and
/// navigates there. It never re-submits: re-running an observation is a new
/// forensic act and must be a deliberate one.
class HistoryScreen extends ConsumerStatefulWidget {
  const HistoryScreen({super.key});

  @override
  ConsumerState<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends ConsumerState<HistoryScreen> {
  final _search = TextEditingController();
  final _searchFocus = FocusNode(debugLabel: 'history-search');
  String _outcomeFilter = 'all';
  String _caseFilter = 'all';
  ExecutionRecord? _selected;

  @override
  void dispose() {
    _search.dispose();
    _searchFocus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final executions = ref.watch(executionHistoryProvider);
    final recordsState = ref.watch(recordsControllerProvider);
    final settings = ref.watch(settingsControllerProvider);
    final query = _search.text.trim().toLowerCase();

    final filtered = executions.where((record) {
      if (_outcomeFilter != 'all' &&
          executionOutcomeTo(record.outcome) != _outcomeFilter) {
        return false;
      }
      if (_caseFilter == 'unattributed' && record.caseId != null) return false;
      if (_caseFilter != 'all' && _caseFilter != 'unattributed' &&
          record.caseId != _caseFilter) {
        return false;
      }
      if (query.isEmpty) return true;
      return record.commandText.toLowerCase().contains(query) ||
          (record.failureCode ?? '').toLowerCase().contains(query) ||
          (record.reportId ?? '').toLowerCase().contains(query) ||
          record.summary.toLowerCase().contains(query);
    }).toList(growable: false);

    final selected = _selected != null &&
            filtered.any((e) => e.id == _selected!.id)
        ? _selected!
        : null;

    return Actions(
      actions: {
        FocusSearchIntent: CallbackAction<FocusSearchIntent>(
          onInvoke: (_) {
            _searchFocus.requestFocus();
            return null;
          },
        ),
      },
      child: Padding(
        padding: const EdgeInsets.all(JockySpace.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (recordsState.storeFailure != null) ...[
              FailureView(failure: recordsState.storeFailure!),
              const SizedBox(height: JockySpace.lg),
            ],
            Expanded(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Expanded(
                    flex: 3,
                    child: _historyPanel(
                      executions,
                      filtered,
                      recordsState,
                      settings.displayUtc,
                    ),
                  ),
                  if (selected != null) ...[
                    const SizedBox(width: JockySpace.lg),
                    SizedBox(
                      width: 380,
                      child: _detailPanel(selected, settings.displayUtc),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _historyPanel(
    List<ExecutionRecord> all,
    List<ExecutionRecord> filtered,
    RecordsState recordsState,
    bool displayUtc,
  ) {
    final cases = recordsState.records.investigations;

    return Panel(
      title: 'Execution history',
      subtitle: '${filtered.length} of ${all.length} shown · retains the most recent '
          '${RecordsRepository.executionRetention}',
      padding: EdgeInsets.zero,
      actions: [
        SizedBox(
          width: 230,
          child: TextField(
            controller: _search,
            focusNode: _searchFocus,
            onChanged: (_) => setState(() {}),
            style: const TextStyle(fontSize: 12),
            decoration: const InputDecoration(
              hintText: 'Search command, code, report',
              prefixIcon: Icon(Icons.search, size: 15, color: JockyColors.textFaint),
            ),
          ),
        ),
        const SizedBox(width: JockySpace.sm),
        _dropdown(
          value: _outcomeFilter,
          items: const {
            'all': 'Any outcome',
            'completed': 'Completed',
            'failed': 'Failed',
            'abandoned': 'Abandoned',
          },
          onChanged: (value) => setState(() => _outcomeFilter = value),
        ),
        const SizedBox(width: JockySpace.sm),
        _dropdown(
          value: _caseFilter,
          items: {
            'all': 'Any case',
            'unattributed': 'Unattributed',
            for (final investigation in cases) investigation.id: investigation.title,
          },
          onChanged: (value) => setState(() => _caseFilter = value),
        ),
        const SizedBox(width: JockySpace.sm),
        IconButton(
          tooltip: 'Clear this workstation\'s execution history',
          onPressed: all.isEmpty ? null : _confirmClear,
          iconSize: 15,
          color: JockyColors.textFaint,
          icon: const Icon(Icons.delete_outline),
        ),
      ],
      child: DataGrid<ExecutionRecord>(
        rows: filtered,
        rowKey: (row) => row.id,
        minWidth: 900,
        selected: (row) => row.id == _selected?.id,
        onSelect: (row) => setState(() => _selected = row),
        emptyState: EmptyState(
          icon: Icons.history,
          title: all.isEmpty ? 'No executions recorded' : 'Nothing matches these filters',
          description: all.isEmpty
              ? 'Commands submitted from the Command Center or Tools are recorded here with '
                  'their engine response.'
              : 'Adjust the search or filters above.',
          compact: true,
          action: all.isEmpty
              ? FilledButton(
                  onPressed: () => context.go(JockyDestination.commandCenter.path),
                  child: const Text('Open Command Center'),
                )
              : null,
        ),
        columns: [
          GridColumn(
            label: 'Submitted',
            width: 190,
            sortValue: (row) => row.submittedAt,
            cell: (row) => MonoValue(
              formatTimestamp(row.submittedAt, utc: displayUtc),
              fontSize: 11,
              color: JockyColors.textMuted,
            ),
          ),
          GridColumn(
            label: 'Outcome',
            width: 118,
            cell: (row) => StatusChip(
              dense: true,
              label: switch (row.outcome) {
                ExecutionOutcome.completed => 'completed',
                ExecutionOutcome.failed => 'failed',
                ExecutionOutcome.abandoned => 'abandoned',
              },
              tone: switch (row.outcome) {
                ExecutionOutcome.completed => StatusTone.ok,
                ExecutionOutcome.failed => StatusTone.danger,
                ExecutionOutcome.abandoned => StatusTone.neutral,
              },
            ),
          ),
          GridColumn(
            label: 'Command',
            flex: 4,
            cell: (row) => MonoValue(row.commandText, fontSize: 11.5, elide: 56),
          ),
          GridColumn(
            label: 'Result summary',
            flex: 4,
            cell: (row) => Text(
              row.summary,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: 11.5,
                color: row.outcome == ExecutionOutcome.completed
                    ? JockyColors.textMuted
                    : JockyColors.danger,
              ),
            ),
          ),
          GridColumn(
            label: 'Source',
            width: 108,
            cell: (row) => Text(
              switch (row.origin) {
                ExecutionOrigin.commandCenter => 'command',
                ExecutionOrigin.guidedTool => 'tool',
                ExecutionOrigin.reRun => 're-run',
              },
              style: const TextStyle(fontSize: 11, color: JockyColors.textFaint),
            ),
          ),
          GridColumn(
            label: 'Engine',
            width: 86,
            alignRight: true,
            sortValue: (row) => row.engineElapsedMs,
            cell: (row) => MonoValue(
              formatDurationMs(row.engineElapsedMs),
              fontSize: 11,
              color: JockyColors.textMuted,
            ),
          ),
        ],
      ),
    );
  }

  Widget _detailPanel(ExecutionRecord record, bool displayUtc) {
    return Panel(
      title: 'Execution detail',
      subtitle: record.id,
      actions: [
        IconButton(
          tooltip: 'Close detail',
          onPressed: () => setState(() => _selected = null),
          iconSize: 15,
          color: JockyColors.textFaint,
          icon: const Icon(Icons.close),
        ),
      ],
      scrollable: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          MonoValue(record.commandText, fontSize: 12, copyable: true, maxLines: 4),
          const SizedBox(height: JockySpace.md),
          DataField(
            label: 'Submitted',
            value: formatTimestamp(record.submittedAt, utc: displayUtc),
            mono: false,
          ),
          DataField(label: 'Report', value: record.reportId ?? 'none issued'),
          DataField(
            label: 'Engine duration',
            value: formatDurationMs(record.engineElapsedMs),
            mono: false,
          ),
          DataField(
            label: 'Round trip',
            value: '${record.clientElapsedMs} ms',
            mono: false,
          ),
          DataField(label: 'Case', value: record.caseId ?? 'unattributed'),
          if (record.failureMessage != null) ...[
            const SizedBox(height: JockySpace.sm),
            FailureView(
              failure: JockyFailure(
                kind: record.failureKind ?? FailureKind.execution,
                message: record.failureMessage!,
                code: record.failureCode,
                report: record.report,
              ),
            ),
          ],
          if (record.warnings.isNotEmpty) ...[
            const SizedBox(height: JockySpace.md),
            WarningList(warnings: record.warnings),
          ],
          const SizedBox(height: JockySpace.lg),
          FilledButton.icon(
            onPressed: () {
              // Loads the command text only. Re-running is an explicit act.
              ref.read(commandDraftProvider.notifier).set(record.commandText);
              context.go(JockyDestination.commandCenter.path);
            },
            icon: const Icon(Icons.edit_outlined, size: 14),
            label: const Text('Load into editor'),
          ),
          const SizedBox(height: JockySpace.sm),
          const Text(
            'Loading places the command in the editor without executing it.',
            style: TextStyle(fontSize: 10.5, color: JockyColors.textFaint, height: 1.4),
          ),
          if (record.report != null) ...[
            const SizedBox(height: JockySpace.sm),
            OutlinedButton.icon(
              onPressed: () => context.go('${JockyDestination.reports.path}/${record.id}'),
              icon: const Icon(Icons.description_outlined, size: 14),
              label: const Text('Open full report'),
            ),
          ],
        ],
      ),
    );
  }

  Future<void> _confirmClear() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: JockyColors.surface,
        title: const Text('Clear execution history?', style: TextStyle(fontSize: 15)),
        content: const Text(
          'This deletes the Command Center history — commands submitted outside an '
          'investigation, and the reports issued for them. They cannot be recovered.\n\n'
          'Executions that belong to an investigation are evidence and are kept, as are the '
          'hash records used to tell whether a file changed between sightings. The engine '
          'records that this clearance happened.',
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
            child: const Text('Clear history'),
          ),
        ],
      ),
    );
    if (!(confirmed ?? false)) return;
    try {
      final clearance =
          await ref.read(recordsControllerProvider.notifier).clearExecutionHistory();
      if (!mounted) return;
      setState(() => _selected = null);
      // Say what actually happened: "nothing was deleted because it is all
      // evidence" is a result, not a silent no-op.
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        SnackBar(content: Text(clearance.summary)),
      );
    } on JockyFailure catch (failure) {
      if (!mounted) return;
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        SnackBar(content: Text('History was not cleared: ${failure.message}')),
      );
    }
  }

  Widget _dropdown({
    required String value,
    required Map<String, String> items,
    required ValueChanged<String> onChanged,
  }) {
    return Container(
      height: 34,
      constraints: const BoxConstraints(maxWidth: 170),
      padding: const EdgeInsets.symmetric(horizontal: JockySpace.sm),
      decoration: BoxDecoration(
        color: JockyColors.surfaceRaised,
        border: Border.all(color: JockyColors.border),
        borderRadius: BorderRadius.circular(JockyRadius.md),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String>(
          value: items.containsKey(value) ? value : items.keys.first,
          isDense: true,
          isExpanded: true,
          dropdownColor: JockyColors.surfaceOverlay,
          style: const TextStyle(fontSize: 12, color: JockyColors.text),
          icon: const Icon(Icons.expand_more, size: 15, color: JockyColors.textFaint),
          items: [
            for (final entry in items.entries)
              DropdownMenuItem(
                value: entry.key,
                child: Text(entry.value, overflow: TextOverflow.ellipsis),
              ),
          ],
          onChanged: (next) => next == null ? null : onChanged(next),
        ),
      ),
    );
  }
}
