import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/navigation.dart';
import '../../core/theme/tokens.dart';
import '../../core/utils/format.dart';
import '../../models/cases/investigation.dart';
import '../../models/executions/execution_record.dart';
import '../../state/providers.dart';
import '../../widgets/data_grid.dart';
import '../../widgets/empty_state.dart';
import '../../widgets/mono_value.dart';
import '../../widgets/panel.dart';
import '../../widgets/status_chip.dart';

/// One case: its identity, the evidence sources the analyst attached, the
/// commands run against it, and the reports the engine issued.
///
/// Two timelines are kept visibly separate:
///   * **Execution timeline** — when this workstation submitted commands.
///   * **Evidence timeline** — timestamps the engine read from the artefacts.
/// Collapsing them would imply an evidentiary ordering that neither the client
/// nor the engine can establish.
class InvestigationDetailScreen extends ConsumerStatefulWidget {
  const InvestigationDetailScreen({super.key, required this.caseId});

  final String caseId;

  @override
  ConsumerState<InvestigationDetailScreen> createState() =>
      _InvestigationDetailScreenState();
}

class _InvestigationDetailScreenState
    extends ConsumerState<InvestigationDetailScreen> {
  late final TextEditingController _notes;
  String? _loadedNotesFor;
  int _timeline = 0;

  @override
  void initState() {
    super.initState();
    _notes = TextEditingController();
  }

  @override
  void dispose() {
    _notes.dispose();
    super.dispose();
  }

  Investigation? get _investigation => ref
      .watch(recordsControllerProvider)
      .records
      .investigations
      .where((c) => c.id == widget.caseId)
      .firstOrNull;

  @override
  Widget build(BuildContext context) {
    final investigation = _investigation;
    final settings = ref.watch(settingsControllerProvider);

    if (investigation == null) {
      return Padding(
        padding: const EdgeInsets.all(JockySpace.xl),
        child: EmptyState(
          icon: Icons.folder_off_outlined,
          title: 'That investigation is not in this workstation\'s records',
          description:
              'It may have been reset, or this client\'s record store was replaced. '
              'Case identifiers are local to this workstation.',
          action: FilledButton(
            onPressed: () => context.go(JockyDestination.investigations.path),
            child: const Text('Back to investigations'),
          ),
        ),
      );
    }

    if (_loadedNotesFor != investigation.id) {
      _loadedNotesFor = investigation.id;
      _notes.text = investigation.notes;
    }

    final executions = ref
        .watch(executionHistoryProvider)
        .where((e) => e.caseId == investigation.id)
        .toList(growable: false);
    final activeId = ref.watch(recordsControllerProvider).records.activeCaseId;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(JockySpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextButton.icon(onPressed: () => context.go('/device/${widget.caseId}'), icon: const Icon(Icons.manage_search), label: const Text('Device observations and Export PDF')),
          _header(investigation, activeId == investigation.id, settings.displayUtc),
          const SizedBox(height: JockySpace.lg),
          LayoutBuilder(
            builder: (context, constraints) {
              final stacked = constraints.maxWidth < 1150;
              final evidence = _evidencePanel(investigation, settings.displayUtc);
              final notes = _notesPanel(investigation);
              return stacked
                  ? Column(children: [
                      evidence,
                      const SizedBox(height: JockySpace.lg),
                      notes,
                    ])
                  : Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(flex: 3, child: evidence),
                        const SizedBox(width: JockySpace.lg),
                        Expanded(flex: 2, child: notes),
                      ],
                    );
            },
          ),
          const SizedBox(height: JockySpace.lg),
          SizedBox(
            height: 420,
            child: _timelinePanel(investigation, executions, settings.displayUtc),
          ),
        ],
      ),
    );
  }

  Widget _header(Investigation investigation, bool isActive, bool displayUtc) {
    return Panel(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Flexible(
                      child: Text(
                        investigation.title,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                    ),
                    const SizedBox(width: JockySpace.md),
                    StatusChip(
                      label: investigation.isOpen ? 'open' : 'closed',
                      tone: investigation.isOpen ? StatusTone.ok : StatusTone.neutral,
                      dense: true,
                    ),
                    if (isActive) ...[
                      const SizedBox(width: 6),
                      const StatusChip(label: 'active', tone: StatusTone.accent, dense: true),
                    ],
                  ],
                ),
                const SizedBox(height: JockySpace.md),
                Wrap(
                  spacing: JockySpace.xl,
                  runSpacing: JockySpace.sm,
                  children: [
                    _inlineField('Case id', investigation.id),
                    _inlineField('Reference', investigation.reference ?? unavailableMarker),
                    _inlineField('Examiner', investigation.examiner ?? unavailableMarker),
                    _inlineField(
                      'Opened',
                      formatTimestamp(investigation.openedAt, utc: displayUtc),
                    ),
                    if (investigation.closedAt != null)
                      _inlineField(
                        'Closed',
                        formatTimestamp(investigation.closedAt, utc: displayUtc),
                      ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(width: JockySpace.lg),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (!isActive)
                    OutlinedButton.icon(
                      onPressed: () => ref
                          .read(recordsControllerProvider.notifier)
                          .setActiveCase(investigation.id),
                      icon: const Icon(Icons.check_circle_outline, size: 14),
                      label: const Text('Make active'),
                    ),
                  const SizedBox(width: JockySpace.sm),
                  OutlinedButton.icon(
                    onPressed: () {
                      final controller = ref.read(recordsControllerProvider.notifier);
                      investigation.isOpen
                          ? controller.closeInvestigation(investigation.id)
                          : controller.reopenInvestigation(investigation.id);
                    },
                    icon: Icon(
                      investigation.isOpen ? Icons.lock_outline : Icons.lock_open,
                      size: 14,
                    ),
                    label: Text(investigation.isOpen ? 'Close case' : 'Reopen case'),
                  ),
                ],
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _inlineField(String label, String value) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(label.toUpperCase(), style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 2),
          MonoValue(value, fontSize: 11.5, color: JockyColors.textMuted),
        ],
      );

  Widget _evidencePanel(Investigation investigation, bool displayUtc) {
    return Panel(
      title: 'Evidence sources',
      subtitle: 'Paths this case covers. Attaching one records it; it does not read it.',
      padding: EdgeInsets.zero,
      actions: [
        OutlinedButton.icon(
          onPressed: () async {
            final path = await ref.read(fileSelectionProvider).pickFile();
            if (path == null) return;
            await ref
                .read(recordsControllerProvider.notifier)
                .addEvidence(investigation.id, path: path, isDirectory: false);
          },
          icon: const Icon(Icons.insert_drive_file_outlined, size: 14),
          label: const Text('Add file'),
        ),
        const SizedBox(width: JockySpace.sm),
        OutlinedButton.icon(
          onPressed: () async {
            final path = await ref.read(fileSelectionProvider).pickDirectory();
            if (path == null) return;
            await ref
                .read(recordsControllerProvider.notifier)
                .addEvidence(investigation.id, path: path, isDirectory: true);
          },
          icon: const Icon(Icons.folder_outlined, size: 14),
          label: const Text('Add directory'),
        ),
      ],
      child: SizedBox(
        height: 260,
        child: DataGrid<EvidenceSource>(
          rows: investigation.evidence,
          rowKey: (row) => row.id,
          minWidth: 620,
          emptyState: const EmptyState(
            icon: Icons.inventory_2_outlined,
            title: 'No evidence sources attached',
            description:
                'Attach the files and directories this case covers. Commands can then be '
                'launched against them from Tools without retyping paths.',
            compact: true,
          ),
          columns: [
            GridColumn(
              label: '',
              width: 34,
              cell: (row) => Icon(
                row.isDirectory ? Icons.folder_outlined : Icons.insert_drive_file_outlined,
                size: 13,
                color: row.isDirectory ? JockyColors.accent : JockyColors.textFaint,
              ),
            ),
            GridColumn(
              label: 'Name',
              flex: 2,
              sortValue: (row) => row.displayName.toLowerCase(),
              cell: (row) => Text(row.displayName, overflow: TextOverflow.ellipsis),
            ),
            GridColumn(
              label: 'Path',
              flex: 4,
              cell: (row) => MonoValue(
                row.path,
                fontSize: 11,
                color: JockyColors.textMuted,
                elide: 56,
              ),
            ),
            GridColumn(
              label: 'Attached',
              width: 130,
              sortValue: (row) => row.addedAt,
              cell: (row) => Tooltip(
                message: formatTimestamp(row.addedAt, utc: displayUtc),
                child: Text(
                  formatRelative(row.addedAt),
                  style: const TextStyle(fontSize: 11, color: JockyColors.textMuted),
                ),
              ),
            ),
            GridColumn(
              label: '',
              width: 110,
              alignRight: true,
              cell: (row) => Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  IconButton(
                    tooltip: 'Load a HASH command for this file',
                    onPressed: row.isDirectory
                        ? null
                        : () {
                            ref
                                .read(commandDraftProvider.notifier)
                                .set('HASH FILE ${_quote(row.path)}');
                            context.go(JockyDestination.commandCenter.path);
                          },
                    iconSize: 14,
                    icon: const Icon(Icons.tag),
                  ),
                  IconButton(
                    tooltip: 'Remove from this case',
                    onPressed: () => ref
                        .read(recordsControllerProvider.notifier)
                        .removeEvidence(investigation.id, row.id),
                    iconSize: 14,
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _notesPanel(Investigation investigation) {
    return Panel(
      title: 'Examiner notes',
      subtitle: 'Stored with this case in the local record store',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            height: 190,
            child: TextField(
              controller: _notes,
              maxLines: null,
              expands: true,
              textAlignVertical: TextAlignVertical.top,
              style: const TextStyle(fontSize: 12.5, height: 1.5),
              decoration: const InputDecoration(
                hintText: 'Observations, decisions, and why each command was run.',
                alignLabelWithHint: true,
              ),
            ),
          ),
          const SizedBox(height: JockySpace.md),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              FilledButton.icon(
                onPressed: () => ref
                    .read(recordsControllerProvider.notifier)
                    .setNotes(investigation.id, _notes.text),
                icon: const Icon(Icons.save_outlined, size: 14),
                label: const Text('Save notes'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _timelinePanel(
    Investigation investigation,
    List<ExecutionRecord> executions,
    bool displayUtc,
  ) {
    return Panel(
      title: _timeline == 0 ? 'Execution timeline' : 'Evidence timeline',
      subtitle: _timeline == 0
          ? 'When this workstation submitted commands for this case'
          : 'Timestamps the engine read from artefacts it observed'
              ' — not when they were examined',
      padding: EdgeInsets.zero,
      actions: [
        SegmentedButton<int>(
          segments: const [
            ButtonSegment(value: 0, label: Text('Executions'), icon: Icon(Icons.play_arrow, size: 13)),
            ButtonSegment(value: 1, label: Text('Artefacts'), icon: Icon(Icons.history_edu, size: 13)),
          ],
          selected: {_timeline},
          showSelectedIcon: false,
          style: ButtonStyle(
            textStyle: const WidgetStatePropertyAll(TextStyle(fontSize: 11.5)),
            visualDensity: VisualDensity.compact,
            side: const WidgetStatePropertyAll(BorderSide(color: JockyColors.border)),
          ),
          onSelectionChanged: (value) => setState(() => _timeline = value.first),
        ),
      ],
      child: _timeline == 0
          ? _executionTimeline(executions, displayUtc)
          : _evidenceTimeline(executions, displayUtc),
    );
  }

  Widget _executionTimeline(List<ExecutionRecord> executions, bool displayUtc) {
    return DataGrid<ExecutionRecord>(
      rows: executions,
      rowKey: (row) => row.id,
      minWidth: 860,
      onSelect: (row) => context.go('${JockyDestination.reports.path}/${row.id}'),
      emptyState: EmptyState(
        icon: Icons.timeline_outlined,
        title: 'No commands recorded for this case',
        description:
            'Make this case active, then run an observation. Executions submitted while it is '
            'active are attributed to it.',
        compact: true,
        action: OutlinedButton(
          onPressed: () => context.go(JockyDestination.commandCenter.path),
          child: const Text('Open Command Center'),
        ),
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
          label: 'State',
          width: 110,
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
          cell: (row) => MonoValue(row.commandText, fontSize: 11.5, elide: 70),
        ),
        GridColumn(
          label: 'Report',
          width: 120,
          cell: (row) => MonoValue(row.reportId, fontSize: 11, color: JockyColors.accent),
        ),
      ],
    );
  }

  Widget _evidenceTimeline(List<ExecutionRecord> executions, bool displayUtc) {
    // Artefact timestamps the engine actually returned, read from the raw result
    // map so a newer backend shape is never silently dropped.
    final entries = <(String, String, String, String)>[];
    for (final execution in executions) {
      final raw = execution.report?.raw['result'];
      if (raw is! Map) continue;
      final action = raw['action'];
      if (action != 'hash') continue;
      final path = '${raw['absolute_path'] ?? raw['target'] ?? ''}';
      final modified = raw['modified'];
      final created = raw['created'];
      if (modified is String) {
        entries.add(('modified', path, modified, execution.id));
      }
      if (created is String) {
        entries.add(('created', path, created, execution.id));
      }
    }
    entries.sort((a, b) => b.$3.compareTo(a.$3));

    return DataGrid<(String, String, String, String)>(
      rows: entries,
      minWidth: 800,
      onSelect: (row) => context.go('${JockyDestination.reports.path}/${row.$4}'),
      emptyState: const EmptyState(
        icon: Icons.history_edu_outlined,
        title: 'No artefact timestamps collected',
        description:
            'Filesystem timestamps appear here once a HASH observation returns them. The engine '
            'exposes creation time only where the filesystem provides it.',
        compact: true,
      ),
      columns: [
        GridColumn(
          label: 'Artefact time',
          width: 210,
          sortValue: (row) => row.$3,
          cell: (row) => MonoValue(
            formatIsoTimestamp(row.$3, utc: displayUtc),
            fontSize: 11,
          ),
        ),
        GridColumn(
          label: 'Kind',
          width: 110,
          cell: (row) => StatusChip(
            label: row.$1,
            tone: row.$1 == 'created' ? StatusTone.info : StatusTone.neutral,
            dense: true,
          ),
        ),
        GridColumn(
          label: 'Artefact',
          flex: 4,
          cell: (row) => MonoValue(row.$2, fontSize: 11, elide: 80),
        ),
      ],
    );
  }

  String _quote(String path) {
    if (!path.contains(' ') && !path.contains('\t')) return path;
    return path.contains('"') ? "'$path'" : '"$path"';
  }
}
