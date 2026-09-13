import 'dart:convert';

import 'package:flutter/material.dart';

import '../../core/theme/tokens.dart';
import '../../core/utils/format.dart';
import '../../models/results/analysis_result.dart';
import '../../models/results/integrity.dart';
import '../data_grid.dart';
import '../empty_state.dart';
import '../failure_view.dart';
import '../mono_value.dart';
import '../panel.dart';
import '../status_chip.dart';
import 'indicator_badges.dart';

/// Renders a dispatcher result according to its action.
///
/// Every renderer surfaces the collector's own completeness fields — a partial
/// observation must never look like a complete one.
class ResultView extends StatelessWidget {
  const ResultView({super.key, required this.result, this.displayUtc = true});

  final AnalysisResult result;
  final bool displayUtc;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        CompletenessStrip(result: result),
        if (result.warnings.isNotEmpty) ...[
          const SizedBox(height: JockySpace.md),
          WarningList(warnings: result.warnings),
        ],
        const SizedBox(height: JockySpace.md),
        switch (result) {
          HashResult() => HashResultView(result: result as HashResult, displayUtc: displayUtc),
          SystemInfoResult() =>
            SystemInfoResultView(result: result as SystemInfoResult, displayUtc: displayUtc),
          ProcessesResult() =>
            ProcessesResultView(result: result as ProcessesResult, displayUtc: displayUtc),
          ListResult() => ListResultView(result: result as ListResult, displayUtc: displayUtc),
          SearchResult() =>
            SearchResultView(result: result as SearchResult, displayUtc: displayUtc),
          EvidenceProtectionResult() =>
            EvidenceProtectionResultView(result: result as EvidenceProtectionResult),
          UnknownResult() => RawJsonView(data: result.raw),
        },
      ],
    );
  }
}

/// The completeness contract, stated explicitly on every result.
class CompletenessStrip extends StatelessWidget {
  const CompletenessStrip({super.key, required this.result});

  final AnalysisResult result;

  @override
  Widget build(BuildContext context) {
    final complete = result.complete;
    final skipped = result.skippedCount ?? 0;

    return Wrap(
      spacing: JockySpace.sm,
      runSpacing: JockySpace.sm,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        StatusChip(
          label: switch (complete) {
            true => 'Observation complete',
            false => 'Observation partial',
            null => 'Completeness not reported',
          },
          tone: switch (complete) {
            true => StatusTone.ok,
            false => StatusTone.warn,
            null => StatusTone.neutral,
          },
          tooltip: 'Reported by the collector. "Complete" describes this collection '
              'run, not the authenticity of the evidence.',
        ),
        if (result.truncated)
          const StatusChip(
            label: 'Truncated',
            tone: StatusTone.warn,
            tooltip: 'The collector hit a result limit; further entries exist but were '
                'not returned.',
          ),
        if (skipped > 0)
          StatusChip(
            label: '$skipped skipped',
            tone: StatusTone.warn,
            icon: Icons.block,
            tooltip: 'Entries the collector could not read.',
          ),
        if (result.message.isNotEmpty)
          Text(
            result.message,
            style: const TextStyle(fontSize: 12, color: JockyColors.textMuted),
          ),
      ],
    );
  }
}

class HashResultView extends StatelessWidget {
  const HashResultView({super.key, required this.result, this.displayUtc = true});

  final HashResult result;
  final bool displayUtc;

  @override
  Widget build(BuildContext context) {
    final history = result.integrityHistory;
    final (historyTone, historyIcon) = switch (history.status) {
      LedgerComparison.unchanged => (StatusTone.ok, Icons.verified_outlined),
      LedgerComparison.altered => (StatusTone.danger, Icons.change_circle_outlined),
      LedgerComparison.firstRecorded => (StatusTone.info, Icons.fiber_new_outlined),
      LedgerComparison.algorithmMismatch => (StatusTone.warn, Icons.compare_arrows),
      LedgerComparison.unknown => (StatusTone.neutral, Icons.help_outline),
    };

    final integrity = result.integrityCheck;
    final integrityTone = switch (integrity.status) {
      IntegrityStatus.ok => StatusTone.ok,
      IntegrityStatus.warning => StatusTone.warn,
      IntegrityStatus.critical => StatusTone.danger,
      IntegrityStatus.unknown => StatusTone.neutral,
    };

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Container(
          padding: const EdgeInsets.all(JockySpace.lg),
          decoration: BoxDecoration(
            color: JockyColors.surfaceRaised,
            border: Border.all(color: JockyColors.border),
            borderRadius: BorderRadius.circular(JockyRadius.md),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  StatusChip(label: result.algorithm, tone: StatusTone.accent, icon: Icons.tag),
                  const SizedBox(width: JockySpace.sm),
                  Expanded(
                    child: Text(
                      result.filename,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600),
                    ),
                  ),
                  StatusChip(
                    label: result.verificationState,
                    tone: historyTone,
                    icon: historyIcon,
                    tooltip: history.message,
                  ),
                ],
              ),
              const SizedBox(height: JockySpace.md),
              MonoValue(result.digest, fontSize: 13, copyable: true, maxLines: 2),
            ],
          ),
        ),
        const SizedBox(height: JockySpace.lg),
        SectionLabel('Evidence identity'),
        DataField(label: 'Absolute path', value: result.absolutePath, copyable: true),
        DataField(label: 'Command target', value: result.target),
        DataField(label: 'Size', value: formatBytes(result.sizeBytes), mono: false),
        DataField(
          label: 'Modified',
          value: formatIsoTimestamp(result.modified, utc: displayUtc),
          mono: false,
        ),
        DataField(
          label: 'Created',
          child: result.created == null
              ? const _Unavailable(
                  reason: 'Birth time is not exposed by this filesystem. '
                      'The engine reports null rather than substituting another timestamp.')
              : Text(
                  formatIsoTimestamp(result.created, utc: displayUtc),
                  style: const TextStyle(fontSize: 12.5),
                ),
        ),
        if (result.metadataChanged != null)
          DataField(
            label: 'Metadata changed',
            child: Tooltip(
              message: 'Linux ctime. This is inode metadata change time, not creation time.',
              child: Text(
                formatIsoTimestamp(result.metadataChanged, utc: displayUtc),
                style: const TextStyle(fontSize: 12.5),
              ),
            ),
          ),
        if (result.indicators.isNotEmpty) ...[
          const SizedBox(height: JockySpace.sm),
          SectionLabel('Triage indicators'),
          IndicatorBadges(indicators: result.indicators, dense: false),
        ],
        const SizedBox(height: JockySpace.lg),
        SectionLabel('Structural check'),
        Row(
          children: [
            StatusChip(
              label: integrity.status.name.toUpperCase(),
              tone: integrityTone,
              tooltip: 'Heuristic structural check. "unknown" means a resource limit was '
                  'reached, not that the file is sound.',
            ),
            const SizedBox(width: JockySpace.sm),
            StatusChip(label: integrity.fileType, tone: StatusTone.neutral, dense: true),
          ],
        ),
        const SizedBox(height: JockySpace.sm),
        Text(
          integrity.message,
          style: const TextStyle(fontSize: 12.5, color: JockyColors.textMuted, height: 1.5),
        ),
        const SizedBox(height: JockySpace.lg),
        SectionLabel('Hash ledger comparison'),
        Text(
          history.message,
          style: const TextStyle(fontSize: 12.5, height: 1.5),
        ),
        if (result.previousHash != null) ...[
          const SizedBox(height: JockySpace.md),
          DataField(label: 'Previous digest', value: result.previousHash!.digest, copyable: true),
          DataField(
            label: 'Previously recorded',
            value: formatIsoTimestamp(result.previousHash!.timestamp, utc: displayUtc),
            mono: false,
          ),
          DataField(
            label: 'Previous size',
            value: formatBytes(result.previousHash!.sizeBytes),
            mono: false,
          ),
        ],
      ],
    );
  }
}

/// Explicit "the engine could not measure this" marker.
///
/// [compact] is used inside narrow table cells, where the full phrase does not
/// fit: it renders the standard unavailable marker and keeps the explanation in
/// the tooltip, so the meaning is never lost or clipped.
class _Unavailable extends StatelessWidget {
  const _Unavailable({required this.reason, this.compact = false});

  final String reason;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    if (compact) {
      return Tooltip(
        message: reason,
        child: const Text(
          unavailableMarker,
          semanticsLabel: 'not available',
          style: TextStyle(fontSize: 12, color: JockyColors.textFaint),
        ),
      );
    }
    return Tooltip(
      message: reason,
      child: const Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.do_not_disturb_alt, size: 12, color: JockyColors.textFaint),
          SizedBox(width: 5),
          Flexible(
            child: Text(
              'not available',
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 12, color: JockyColors.textFaint),
            ),
          ),
        ],
      ),
    );
  }
}

class SystemInfoResultView extends StatelessWidget {
  const SystemInfoResultView({super.key, required this.result, this.displayUtc = true});

  final SystemInfoResult result;
  final bool displayUtc;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SectionLabel('Host identity'),
        DataField(label: 'Hostname', value: result.hostname, copyable: true),
        DataField(label: 'Operating system', value: '${result.os} ${result.osRelease}'),
        DataField(label: 'OS version', value: result.osVersion),
        DataField(label: 'Platform', value: result.platformString),
        DataField(label: 'Architecture', value: result.architecture),
        const SizedBox(height: JockySpace.md),
        SectionLabel('Processor and memory'),
        DataField(label: 'Processor', value: result.processor),
        DataField(
          label: 'Cores',
          mono: false,
          value: '${result.cpuLogicalCores ?? unavailableMarker} logical, '
              '${result.cpuPhysicalCores ?? unavailableMarker} physical',
        ),
        DataField(label: 'CPU load', value: formatPercent(result.cpuPercent), mono: false),
        DataField(
          label: 'Memory',
          mono: false,
          value: result.memoryTotalGb == null
              ? unavailableMarker
              : '${result.memoryAvailableGb ?? unavailableMarker} GB available of '
                  '${result.memoryTotalGb} GB (${formatPercent(result.memoryUsedPercent)} used)',
        ),
        DataField(
          label: 'Primary volume',
          mono: false,
          value: result.diskTotalGb == null
              ? unavailableMarker
              : '${result.diskTotalGb} GB total, ${formatPercent(result.diskUsedPercent)} used',
        ),
        const SizedBox(height: JockySpace.md),
        SectionLabel('Runtime'),
        DataField(label: 'Engine Python', value: result.pythonRuntime),
        DataField(
          label: 'Boot time',
          value: formatIsoTimestamp(result.bootTime, utc: displayUtc),
          mono: false,
        ),
        DataField(label: 'Uptime', value: formatUptime(result.uptimeSeconds), mono: false),
        DataField(
          label: 'Collected at',
          value: formatIsoTimestamp(result.collectedAt, utc: displayUtc),
          mono: false,
        ),
        if (result.monitoringNote != null) ...[
          const SizedBox(height: JockySpace.md),
          WarningList(warnings: [result.monitoringNote!], title: 'Collector note'),
        ],
      ],
    );
  }
}

class ProcessesResultView extends StatelessWidget {
  const ProcessesResultView({super.key, required this.result, this.displayUtc = true});

  final ProcessesResult result;
  final bool displayUtc;

  @override
  Widget build(BuildContext context) {
    final processes = result.processes;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SectionLabel(
          'Observed processes — showing ${result.returnedCount ?? processes.length} '
          'of ${result.processCount ?? unavailableMarker}',
        ),
        SizedBox(
          height: 420,
          child: DataGrid<ProcessObservation>(
            rows: processes,
            rowKey: (row) => '${row.pid}-${row.name}',
            minWidth: 760,
            emptyState: const EmptyState(
              icon: Icons.memory_outlined,
              title: 'No processes returned',
              description: 'The engine completed the observation but returned no rows.',
              compact: true,
            ),
            columns: [
              GridColumn(
                label: 'PID',
                width: 80,
                sortValue: (row) => row.pid,
                cell: (row) => MonoValue(row.pid?.toString(), fontSize: 11.5),
              ),
              GridColumn(
                label: 'Process',
                flex: 3,
                sortValue: (row) => row.name.toLowerCase(),
                cell: (row) => Text(row.name, overflow: TextOverflow.ellipsis),
              ),
              GridColumn(
                label: 'User',
                flex: 2,
                sortValue: (row) => row.username.toLowerCase(),
                cell: (row) => Text(
                  row.username,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: JockyColors.textMuted),
                ),
              ),
              GridColumn(
                label: 'State',
                width: 100,
                sortValue: (row) => row.status,
                cell: (row) => Text(
                  row.status,
                  style: const TextStyle(color: JockyColors.textMuted, fontSize: 11.5),
                ),
              ),
              GridColumn(
                label: 'Memory',
                width: 90,
                alignRight: true,
                tooltip: 'Percentage of physical memory. Blank means the engine could '
                    'not measure it.',
                sortValue: (row) => row.memoryPercent,
                cell: (row) => row.memoryPercent == null
                    ? const _Unavailable(
                        compact: true,
                        reason: 'The engine could not measure this process\'s memory. '
                            'Null is not zero.')
                    : MonoValue(formatPercent(row.memoryPercent, decimals: 2), fontSize: 11.5),
              ),
              GridColumn(
                label: 'CPU',
                width: 80,
                alignRight: true,
                tooltip: 'Always unavailable in a snapshot collector: no sampling '
                    'interval was taken.',
                cell: (row) => const _Unavailable(
                  compact: true,
                  reason: 'A single snapshot cannot establish an interval CPU percentage. '
                      'The engine reports null rather than 0.',
                ),
              ),
              GridColumn(
                label: 'Started',
                flex: 2,
                sortValue: (row) => row.created,
                cell: (row) => MonoValue(
                  row.created == null
                      ? null
                      : formatIsoTimestamp(row.created, utc: displayUtc),
                  fontSize: 11,
                  color: JockyColors.textMuted,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: JockySpace.sm),
        Text(
          'Collected at ${formatIsoTimestamp(result.collectedAt, utc: displayUtc)}',
          style: const TextStyle(fontSize: 11, color: JockyColors.textFaint),
        ),
      ],
    );
  }
}

class ListResultView extends StatelessWidget {
  const ListResultView({super.key, required this.result, this.displayUtc = true});

  final ListResult result;
  final bool displayUtc;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        DataField(label: 'Directory', value: result.target, copyable: true),
        DataField(
          label: 'Entries',
          mono: false,
          value: '${result.returnedCount ?? 0} returned of ${result.entryCount ?? 0} found '
              '(${result.entriesScanned ?? 0} scanned)',
        ),
        const SizedBox(height: JockySpace.sm),
        SizedBox(
          height: 420,
          child: _EntryGrid(entries: result.entries, displayUtc: displayUtc, showType: true),
        ),
      ],
    );
  }
}

class SearchResultView extends StatelessWidget {
  const SearchResultView({super.key, required this.result, this.displayUtc = true});

  final SearchResult result;
  final bool displayUtc;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        DataField(label: 'Name contains', value: result.searchTarget),
        DataField(label: 'Searched under', value: result.searchDirectory, copyable: true),
        DataField(
          label: 'Matches',
          mono: false,
          value: '${result.matchCount ?? 0} match(es) from '
              '${result.entriesScanned ?? 0} files scanned',
        ),
        const SizedBox(height: JockySpace.xs),
        const Text(
          'Case-insensitive filename substring match, recursive.',
          style: TextStyle(fontSize: 11, color: JockyColors.textFaint),
        ),
        const SizedBox(height: JockySpace.md),
        SizedBox(
          height: 420,
          child: _EntryGrid(entries: result.matches, displayUtc: displayUtc, showType: false),
        ),
      ],
    );
  }
}

class _EntryGrid extends StatelessWidget {
  const _EntryGrid({
    required this.entries,
    required this.displayUtc,
    required this.showType,
  });

  final List<DirectoryEntry> entries;
  final bool displayUtc;
  final bool showType;

  @override
  Widget build(BuildContext context) {
    return DataGrid<DirectoryEntry>(
      rows: entries,
      rowKey: (row) => row.path,
      minWidth: 720,
      emptyState: const EmptyState(
        icon: Icons.folder_off_outlined,
        title: 'Nothing returned',
        description: 'The engine completed this observation and returned no entries.',
        compact: true,
      ),
      columns: [
        if (showType)
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
          flex: 3,
          sortValue: (row) => row.name.toLowerCase(),
          cell: (row) => Text(row.name, overflow: TextOverflow.ellipsis),
        ),
        GridColumn(
          label: 'Path',
          flex: 4,
          sortValue: (row) => row.path.toLowerCase(),
          cell: (row) => MonoValue(
            row.path,
            fontSize: 11,
            color: JockyColors.textMuted,
            elide: 64,
          ),
        ),
        GridColumn(
          label: 'Size',
          width: 100,
          alignRight: true,
          sortValue: (row) => row.sizeBytes,
          cell: (row) => row.isDirectory && (row.sizeBytes ?? 0) == 0
              ? const Text('—', style: TextStyle(color: JockyColors.textFaint))
              : MonoValue(formatBytes(row.sizeBytes), fontSize: 11.5),
        ),
        GridColumn(
          label: 'Modified',
          width: 190,
          sortValue: (row) => row.modified,
          cell: (row) => MonoValue(
            formatIsoTimestamp(row.modified, utc: displayUtc),
            fontSize: 11,
            color: JockyColors.textMuted,
          ),
        ),
        GridColumn(
          label: 'Indicators',
          width: 130,
          cell: (row) => IndicatorSummary(indicators: row.indicators),
        ),
      ],
    );
  }
}

class EvidenceProtectionResultView extends StatelessWidget {
  const EvidenceProtectionResultView({super.key, required this.result});

  final EvidenceProtectionResult result;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const CapabilityGap(
          capability: 'Legacy evidence-operation record',
          explanation: 'This is a stored result. Current JOCKY exports authenticated encrypted copies with an explicit recovery passphrase and never overwrites source evidence.',
        ),
        const SizedBox(height: JockySpace.md),
        DataField(label: 'Path', value: result.path, copyable: true),
        DataField(label: 'Engine status', value: result.status, mono: false),
      ],
    );
  }
}

/// Structured fallback: shows exactly what the engine returned.
class RawJsonView extends StatelessWidget {
  const RawJsonView({super.key, required this.data, this.maxHeight = 420});

  final Map<String, dynamic> data;
  final double maxHeight;

  @override
  Widget build(BuildContext context) {
    final text = const JsonEncoder.withIndent('  ').convert(data);
    return ConstrainedBox(
      constraints: BoxConstraints(maxHeight: maxHeight),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(JockySpace.md),
        decoration: BoxDecoration(
          color: JockyColors.canvas,
          border: Border.all(color: JockyColors.border),
          borderRadius: BorderRadius.circular(JockyRadius.md),
        ),
        child: Scrollbar(
          child: SingleChildScrollView(
            child: SelectableText(
              text,
              style: const TextStyle(
                fontFamily: JockyType.mono,
                fontSize: 11.5,
                height: 1.5,
                color: JockyColors.textMuted,
              ),
            ),
          ),
        ),
      ),
    );
  }
}
