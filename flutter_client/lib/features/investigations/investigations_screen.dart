import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/navigation.dart';
import '../../core/theme/tokens.dart';
import '../../core/utils/format.dart';
import '../../models/cases/investigation.dart';
import '../../state/providers.dart';
import '../../widgets/data_grid.dart';
import '../../widgets/empty_state.dart';
import '../../widgets/failure_view.dart';
import '../../widgets/mono_value.dart';
import '../../widgets/panel.dart';
import '../../widgets/status_chip.dart';

/// Case list.
///
/// Cases are held by this client: the engine has no case concept, so opening a
/// case creates no server-side record and the UI says so.
class InvestigationsScreen extends ConsumerStatefulWidget {
  const InvestigationsScreen({super.key, this.openCreateDialog = false});

  final bool openCreateDialog;

  @override
  ConsumerState<InvestigationsScreen> createState() => _InvestigationsScreenState();
}

class _InvestigationsScreenState extends ConsumerState<InvestigationsScreen> {
  @override
  void initState() {
    super.initState();
    if (widget.openCreateDialog) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _openCreateDialog());
    }
  }

  Future<void> _openCreateDialog() async {
    final created = await showDialog<Investigation?>(
      context: context,
      builder: (context) => const _NewInvestigationDialog(),
    );
    if (created != null && mounted) {
      context.go('${JockyDestination.investigations.path}/${created.id}');
    }
  }

  @override
  Widget build(BuildContext context) {
    final recordsState = ref.watch(recordsControllerProvider);
    final cases = recordsState.records.investigations;
    final executions = ref.watch(executionHistoryProvider);
    final settings = ref.watch(settingsControllerProvider);
    final activeId = recordsState.records.activeCaseId;

    return Padding(
      padding: const EdgeInsets.all(JockySpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            const Expanded(child: Text('Cases and command history are stored by the local backend in SQLite.')),
            FilledButton.icon(onPressed: () => context.go('/device'), icon: const Icon(Icons.manage_search), label: const Text('Analyze This Device')),
          ]),
          if (recordsState.storeFailure != null) ...[
            const SizedBox(height: JockySpace.md),
            FailureView(failure: recordsState.storeFailure!),
          ],
          const SizedBox(height: JockySpace.lg),
          Expanded(
            child: Panel(
              title: 'Investigations',
              subtitle: '${cases.length} recorded · '
                  '${cases.where((c) => c.isOpen).length} open',
              padding: EdgeInsets.zero,
              actions: [
                FilledButton.icon(
                  onPressed: _openCreateDialog,
                  icon: const Icon(Icons.add, size: 15),
                  label: const Text('Open investigation'),
                ),
              ],
              child: DataGrid<Investigation>(
                rows: cases,
                rowKey: (row) => row.id,
                minWidth: 860,
                selected: (row) => row.id == activeId,
                onSelect: (row) =>
                    context.go('${JockyDestination.investigations.path}/${row.id}'),
                emptyState: EmptyState(
                  icon: Icons.folder_open_outlined,
                  title: 'No investigations recorded',
                  description:
                      'Open an investigation to attribute observations to a case and keep its '
                      'evidence list, notes and reports together.',
                  action: FilledButton.icon(
                    onPressed: _openCreateDialog,
                    icon: const Icon(Icons.add, size: 15),
                    label: const Text('Open investigation'),
                  ),
                ),
                columns: [
                  GridColumn(
                    label: 'State',
                    width: 100,
                    cell: (row) => StatusChip(
                      label: row.isOpen ? 'open' : 'closed',
                      tone: row.isOpen ? StatusTone.ok : StatusTone.neutral,
                      dense: true,
                    ),
                  ),
                  GridColumn(
                    label: 'Title',
                    flex: 3,
                    sortValue: (row) => row.title.toLowerCase(),
                    cell: (row) => Row(
                      children: [
                        Flexible(
                          child: Text(row.title, overflow: TextOverflow.ellipsis),
                        ),
                        if (row.id == activeId) ...[
                          const SizedBox(width: 6),
                          const StatusChip(label: 'active', tone: StatusTone.accent, dense: true),
                        ],
                      ],
                    ),
                  ),
                  GridColumn(
                    label: 'Reference',
                    flex: 2,
                    sortValue: (row) => row.reference ?? '',
                    cell: (row) => MonoValue(row.reference, fontSize: 11),
                  ),
                  GridColumn(
                    label: 'Examiner',
                    flex: 2,
                    cell: (row) => Text(
                      row.examiner ?? unavailableMarker,
                      style: const TextStyle(color: JockyColors.textMuted),
                    ),
                  ),
                  GridColumn(
                    label: 'Evidence',
                    width: 90,
                    alignRight: true,
                    sortValue: (row) => row.evidence.length,
                    cell: (row) => Text('${row.evidence.length}'),
                  ),
                  GridColumn(
                    label: 'Executions',
                    width: 100,
                    alignRight: true,
                    cell: (row) => Text(
                      '${executions.where((e) => e.caseId == row.id).length}',
                    ),
                  ),
                  GridColumn(
                    label: 'Opened',
                    width: 190,
                    sortValue: (row) => row.openedAt,
                    cell: (row) => MonoValue(
                      formatTimestamp(row.openedAt, utc: settings.displayUtc),
                      fontSize: 11,
                      color: JockyColors.textMuted,
                    ),
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

class _NewInvestigationDialog extends ConsumerStatefulWidget {
  const _NewInvestigationDialog();

  @override
  ConsumerState<_NewInvestigationDialog> createState() => _NewInvestigationDialogState();
}

class _NewInvestigationDialogState extends ConsumerState<_NewInvestigationDialog> {
  final _title = TextEditingController();
  final _reference = TextEditingController();
  final _examiner = TextEditingController();

  @override
  void dispose() {
    _title.dispose();
    _reference.dispose();
    _examiner.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: JockyColors.surface,
      shape: RoundedRectangleBorder(
        side: const BorderSide(color: JockyColors.borderStrong),
        borderRadius: BorderRadius.circular(JockyRadius.lg),
      ),
      title: const Text('Open an investigation', style: TextStyle(fontSize: 15)),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(
              controller: _title,
              autofocus: true,
              decoration: const InputDecoration(labelText: 'Title'),
            ),
            const SizedBox(height: JockySpace.md),
            TextField(
              controller: _reference,
              decoration: const InputDecoration(
                labelText: 'Case reference (optional)',
                hintText: 'Exhibit, ticket or FIR number',
              ),
            ),
            const SizedBox(height: JockySpace.md),
            TextField(
              controller: _examiner,
              decoration: const InputDecoration(labelText: 'Examiner (optional)'),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () async {
            final created =
                await ref.read(recordsControllerProvider.notifier).openInvestigation(
                      title: _title.text,
                      reference: _reference.text,
                      examiner: _examiner.text,
                    );
            if (context.mounted) Navigator.of(context).pop(created);
          },
          child: const Text('Open and make active'),
        ),
      ],
    );
  }
}
