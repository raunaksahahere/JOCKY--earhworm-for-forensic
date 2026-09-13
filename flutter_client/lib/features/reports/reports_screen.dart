import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/navigation.dart';
import '../../app/shortcuts.dart';
import '../../core/theme/tokens.dart';
import '../../core/utils/format.dart';
import '../../models/executions/execution_record.dart';
import '../../state/providers.dart';
import '../../widgets/data_grid.dart';
import '../../widgets/empty_state.dart';
import '../../widgets/failure_view.dart';
import '../../widgets/mono_value.dart';
import '../../widgets/panel.dart';
import '../../widgets/status_chip.dart';

/// Report archive.
///
/// The engine issues a report with every execution, including failed ones, but
/// stores them in SQLite. This view projects the durable command report archive.
class ReportsScreen extends ConsumerStatefulWidget {
  const ReportsScreen({super.key});

  @override
  ConsumerState<ReportsScreen> createState() => _ReportsScreenState();
}

class _ReportsScreenState extends ConsumerState<ReportsScreen> {
  final _searchFocus = FocusNode(debugLabel: 'report-search');
  final _search = TextEditingController();
  String _statusFilter = 'all';
  String _actionFilter = 'all';

  @override
  void dispose() {
    _search.dispose();
    _searchFocus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final archive = ref.watch(reportArchiveProvider);
    final settings = ref.watch(settingsControllerProvider);
    final query = _search.text.trim().toLowerCase();

    final actions = {
      for (final record in archive)
        if (record.action != null) record.action!,
    }.toList()
      ..sort();

    final filtered = archive.where((record) {
      final report = record.report!;
      if (_statusFilter != 'all' && report.status != _statusFilter) return false;
      if (_actionFilter != 'all' && record.action != _actionFilter) return false;
      if (query.isEmpty) return true;
      return report.reportId.toLowerCase().contains(query) ||
          report.command.toLowerCase().contains(query) ||
          (report.target ?? '').toLowerCase().contains(query) ||
          (report.errorCode ?? '').toLowerCase().contains(query);
    }).toList(growable: false);

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
            Row(children: [
              const Expanded(child: Text('Command reports are retained in backend SQLite. Full device reports are available from each device investigation.')),
              TextButton(onPressed: () => context.go('/device'), child: const Text('Device investigation reports')),
            ]),
            const SizedBox(height: JockySpace.lg),
            Expanded(
              child: Panel(
                title: 'Reports',
                subtitle: '${filtered.length} of ${archive.length} shown',
                padding: EdgeInsets.zero,
                actions: [
                  SizedBox(
                    width: 260,
                    child: TextField(
                      controller: _search,
                      focusNode: _searchFocus,
                      onChanged: (_) => setState(() {}),
                      style: const TextStyle(fontSize: 12),
                      decoration: const InputDecoration(
                        hintText: 'Search id, command, target, code',
                        prefixIcon: Icon(Icons.search, size: 15, color: JockyColors.textFaint),
                        suffixIcon: Padding(
                          padding: EdgeInsets.only(right: 8, top: 10),
                          child: KeyHint(['Ctrl', 'F']),
                        ),
                        suffixIconConstraints: BoxConstraints(minWidth: 0, minHeight: 0),
                      ),
                    ),
                  ),
                  const SizedBox(width: JockySpace.sm),
                  _filter(
                    value: _statusFilter,
                    items: const {'all': 'Any status', 'completed': 'Completed', 'failed': 'Failed'},
                    onChanged: (value) => setState(() => _statusFilter = value),
                  ),
                  const SizedBox(width: JockySpace.sm),
                  _filter(
                    value: _actionFilter,
                    items: {
                      'all': 'Any action',
                      for (final action in actions) action: action,
                    },
                    onChanged: (value) => setState(() => _actionFilter = value),
                  ),
                ],
                child: DataGrid<ExecutionRecord>(
                  rows: filtered,
                  rowKey: (row) => row.id,
                  minWidth: 980,
                  onSelect: (row) =>
                      context.go('${JockyDestination.reports.path}/${row.id}'),
                  emptyState: EmptyState(
                    icon: Icons.description_outlined,
                    title: archive.isEmpty
                        ? 'No reports held yet'
                        : 'No reports match these filters',
                    description: archive.isEmpty
                        ? 'Every execution returns a report. Run an observation and it will be '
                            'archived here with its full result payload.'
                        : 'Clear the search or filters to see the full archive.',
                    compact: true,
                    action: archive.isEmpty
                        ? FilledButton(
                            onPressed: () => context.go(JockyDestination.commandCenter.path),
                            child: const Text('Open Command Center'),
                          )
                        : null,
                  ),
                  columns: [
                    GridColumn(
                      label: 'Report id',
                      width: 126,
                      sortValue: (row) => row.reportId ?? '',
                      cell: (row) => MonoValue(
                        row.reportId,
                        fontSize: 11.5,
                        color: JockyColors.accent,
                      ),
                    ),
                    GridColumn(
                      label: 'Status',
                      width: 116,
                      cell: (row) => StatusChip(
                        dense: true,
                        label: row.report!.status,
                        tone: row.report!.completed ? StatusTone.ok : StatusTone.danger,
                      ),
                    ),
                    GridColumn(
                      label: 'Action',
                      width: 110,
                      sortValue: (row) => row.action ?? '',
                      cell: (row) => Text(
                        row.action ?? unavailableMarker,
                        style: const TextStyle(color: JockyColors.textMuted),
                      ),
                    ),
                    GridColumn(
                      label: 'Command',
                      flex: 4,
                      cell: (row) => MonoValue(row.report!.command, fontSize: 11.5, elide: 64),
                    ),
                    GridColumn(
                      label: 'Findings',
                      width: 150,
                      cell: (row) => _findings(row),
                    ),
                    GridColumn(
                      label: 'Engine',
                      width: 88,
                      alignRight: true,
                      sortValue: (row) => row.engineElapsedMs,
                      cell: (row) => MonoValue(
                        formatDurationMs(row.engineElapsedMs),
                        fontSize: 11,
                        color: JockyColors.textMuted,
                      ),
                    ),
                    GridColumn(
                      label: 'Issued',
                      width: 190,
                      sortValue: (row) => row.report!.timestamp,
                      cell: (row) => MonoValue(
                        formatIsoTimestamp(row.report!.timestamp, utc: settings.displayUtc),
                        fontSize: 11,
                        color: JockyColors.textMuted,
                      ),
                    ),
                    GridColumn(
                      label: 'Schema',
                      width: 76,
                      alignRight: true,
                      cell: (row) => Text(
                        'v${row.report!.schemaVersion ?? '?'}',
                        style: const TextStyle(fontSize: 11, color: JockyColors.textFaint),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _findings(ExecutionRecord record) {
    final report = record.report!;
    final result = report.result;
    final chips = <Widget>[
      if (report.errors.isNotEmpty)
        StatusChip(
          label: report.errorCode ?? 'error',
          tone: StatusTone.danger,
          dense: true,
          tooltip: report.errors.join('\n'),
        ),
      if (report.warnings.isNotEmpty)
        StatusChip(
          label: '${report.warnings.length}W',
          tone: StatusTone.warn,
          dense: true,
          tooltip: report.warnings.join('\n'),
        ),
      if (result?.truncated ?? false)
        const StatusChip(label: 'trunc', tone: StatusTone.warn, dense: true),
    ];
    if (chips.isEmpty) {
      return const Text('—', style: TextStyle(color: JockyColors.textFaint));
    }
    return Wrap(spacing: 4, children: chips);
  }

  Widget _filter({
    required String value,
    required Map<String, String> items,
    required ValueChanged<String> onChanged,
  }) {
    return Container(
      height: 34,
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
          borderRadius: BorderRadius.circular(JockyRadius.md),
          dropdownColor: JockyColors.surfaceOverlay,
          style: const TextStyle(fontSize: 12, color: JockyColors.text),
          icon: const Icon(Icons.expand_more, size: 15, color: JockyColors.textFaint),
          items: [
            for (final entry in items.entries)
              DropdownMenuItem(value: entry.key, child: Text(entry.value)),
          ],
          onChanged: (next) => next == null ? null : onChanged(next),
        ),
      ),
    );
  }
}
