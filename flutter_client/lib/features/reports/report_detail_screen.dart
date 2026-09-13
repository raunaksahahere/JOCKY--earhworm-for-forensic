import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/navigation.dart';
import '../../core/errors/failure.dart';
import '../../core/theme/tokens.dart';
import '../../core/utils/format.dart';
import '../../models/executions/execution_record.dart';
import '../../services/export/report_export_service.dart';
import '../../state/providers.dart';
import '../../widgets/empty_state.dart';
import '../../widgets/failure_view.dart';
import '../../widgets/mono_value.dart';
import '../../widgets/panel.dart';
import '../../widgets/results/result_view.dart';
import '../../widgets/status_chip.dart';

/// Full report view for one execution, with export.
class ReportDetailScreen extends ConsumerStatefulWidget {
  const ReportDetailScreen({super.key, required this.executionId});

  final String executionId;

  @override
  ConsumerState<ReportDetailScreen> createState() => _ReportDetailScreenState();
}

class _ReportDetailScreenState extends ConsumerState<ReportDetailScreen> {
  String? _exportMessage;
  JockyFailure? _exportFailure;
  bool _showRaw = false;

  @override
  Widget build(BuildContext context) {
    final record = ref
        .watch(executionHistoryProvider)
        .where((e) => e.id == widget.executionId)
        .firstOrNull;
    final settings = ref.watch(settingsControllerProvider);

    if (record == null) {
      return Padding(
        padding: const EdgeInsets.all(JockySpace.xl),
        child: EmptyState(
          icon: Icons.description_outlined,
          title: 'That execution is not in this workstation\'s records',
          description:
              'Reports are held locally. If the record store was cleared or replaced, earlier '
              'reports are no longer retrievable — the engine does not keep a copy.',
          action: FilledButton(
            onPressed: () => context.go(JockyDestination.reports.path),
            child: const Text('Back to reports'),
          ),
        ),
      );
    }

    final report = record.report;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(JockySpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _header(record, settings.displayUtc),
          if (_exportFailure != null) ...[
            const SizedBox(height: JockySpace.md),
            FailureView(failure: _exportFailure!),
          ],
          if (_exportMessage != null) ...[
            const SizedBox(height: JockySpace.md),
            Container(
              padding: const EdgeInsets.all(JockySpace.md),
              decoration: BoxDecoration(
                color: JockyColors.okWash,
                border: Border.all(color: JockyColors.ok.withValues(alpha: 0.4)),
                borderRadius: BorderRadius.circular(JockyRadius.md),
              ),
              child: Row(
                children: [
                  const Icon(Icons.check_circle_outline, size: 14, color: JockyColors.ok),
                  const SizedBox(width: JockySpace.sm),
                  Expanded(child: MonoValue(_exportMessage, fontSize: 11.5)),
                ],
              ),
            ),
          ],
          const SizedBox(height: JockySpace.lg),
          if (report == null)
            Panel(
              title: 'No report was issued',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    record.failureMessage ??
                        'The engine did not return a report for this submission.',
                    style: const TextStyle(fontSize: 12.5, height: 1.5),
                  ),
                  const SizedBox(height: JockySpace.md),
                  const CapabilityGap(
                    capability: 'A report is normally returned even for failures',
                    explanation:
                        'The engine builds a report for malformed commands and execution errors '
                        'alike. Its absence here means the response never arrived — the request '
                        'timed out, was abandoned, or the engine was unreachable.',
                  ),
                ],
              ),
            )
          else ...[
            Panel(
              title: 'Execution metadata',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  DataField(label: 'Report id', value: report.reportId, copyable: true),
                  DataField(
                    label: 'Issued at',
                    child: Row(
                      children: [
                        Text(
                          formatIsoTimestamp(report.timestamp, utc: settings.displayUtc),
                          style: const TextStyle(fontSize: 12.5),
                        ),
                        const SizedBox(width: JockySpace.sm),
                        MonoValue(
                          report.timestamp,
                          fontSize: 10.5,
                          color: JockyColors.textFaint,
                        ),
                      ],
                    ),
                  ),
                  DataField(label: 'Command', value: report.command, copyable: true),
                  DataField(label: 'Action', value: report.action, mono: false),
                  DataField(label: 'Target', value: report.target, copyable: true),
                  DataField(
                    label: 'Parsed command',
                    child: report.normalizedCommand == null
                        ? const Text(
                            'The engine did not parse this command.',
                            style: TextStyle(fontSize: 12, color: JockyColors.textFaint),
                          )
                        : Wrap(
                            spacing: 6,
                            runSpacing: 6,
                            children: [
                              for (final entry in report.normalizedCommand!.raw.entries)
                                StatusChip(
                                  label: '${entry.key}=${entry.value}',
                                  tone: StatusTone.neutral,
                                  dense: true,
                                ),
                            ],
                          ),
                  ),
                  DataField(
                    label: 'Engine duration',
                    value: formatDurationMs(report.executionTimeMs),
                    mono: false,
                  ),
                  DataField(
                    label: 'Client round trip',
                    value: '${record.clientElapsedMs} ms',
                    mono: false,
                  ),
                  DataField(
                    label: 'Report schema',
                    child: Row(
                      children: [
                        Text(
                          'v${report.schemaVersion ?? unavailableMarker}',
                          style: const TextStyle(fontSize: 12.5),
                        ),
                        const SizedBox(width: JockySpace.sm),
                        if (report.schemaVersion != null &&
                            report.schemaVersion != 1)
                          const StatusChip(
                            label: 'newer than this client renders',
                            tone: StatusTone.warn,
                            dense: true,
                          ),
                      ],
                    ),
                  ),
                  DataField(
                    label: 'Case attribution',
                    child: Text(
                      record.caseId == null
                          ? 'Unattributed — no case was active at submission.'
                          : record.caseId!,
                      style: TextStyle(
                        fontSize: 12.5,
                        fontFamily: record.caseId == null ? null : JockyType.mono,
                        color: record.caseId == null
                            ? JockyColors.textFaint
                            : JockyColors.text,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            if (report.errors.isNotEmpty) ...[
              const SizedBox(height: JockySpace.lg),
              Panel(
                title: 'Engine errors',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    for (final error in report.errors)
                      Padding(
                        padding: const EdgeInsets.only(bottom: JockySpace.sm),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Icon(Icons.error_outline,
                                size: 14, color: JockyColors.danger),
                            const SizedBox(width: JockySpace.sm),
                            Expanded(
                              child: SelectableText(
                                error,
                                style: const TextStyle(fontSize: 12.5, height: 1.5),
                              ),
                            ),
                          ],
                        ),
                      ),
                    if (report.errorCode != null)
                      DataField(label: 'Error code', value: report.errorCode),
                    if (report.errorKind != null)
                      DataField(label: 'Error kind', value: report.errorKind),
                  ],
                ),
              ),
            ],
            const SizedBox(height: JockySpace.lg),
            Panel(
              title: 'Observation',
              subtitle: 'Result payload as returned by the engine',
              actions: [
                TextButton.icon(
                  onPressed: () => setState(() => _showRaw = !_showRaw),
                  icon: Icon(_showRaw ? Icons.view_agenda_outlined : Icons.data_object,
                      size: 14),
                  label: Text(_showRaw ? 'Structured view' : 'Raw JSON'),
                ),
              ],
              child: report.result == null
                  ? const EmptyState(
                      icon: Icons.inbox_outlined,
                      title: 'No result payload',
                      description:
                          'This execution failed before the collector produced a result. The '
                          'engine still issued this report.',
                      compact: true,
                    )
                  : _showRaw
                      ? RawJsonView(data: report.raw, maxHeight: 620)
                      : ResultView(
                          result: report.result!,
                          displayUtc: settings.displayUtc,
                        ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _header(ExecutionRecord record, bool displayUtc) {
    final report = record.report;
    return Panel(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          IconButton(
            tooltip: 'Back to reports',
            onPressed: () => context.go(JockyDestination.reports.path),
            iconSize: 16,
            icon: const Icon(Icons.arrow_back),
          ),
          const SizedBox(width: JockySpace.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      report?.reportId ?? 'No report issued',
                      style: const TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w600,
                        fontFamily: JockyType.mono,
                      ),
                    ),
                    const SizedBox(width: JockySpace.md),
                    StatusChip(
                      label: switch (record.outcome) {
                        ExecutionOutcome.completed => 'completed',
                        ExecutionOutcome.failed => 'failed',
                        ExecutionOutcome.abandoned => 'abandoned',
                      },
                      tone: switch (record.outcome) {
                        ExecutionOutcome.completed => StatusTone.ok,
                        ExecutionOutcome.failed => StatusTone.danger,
                        ExecutionOutcome.abandoned => StatusTone.neutral,
                      },
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                MonoValue(record.commandText, fontSize: 12, copyable: true),
              ],
            ),
          ),
          const SizedBox(width: JockySpace.md),
          Wrap(
            spacing: JockySpace.sm,
            children: [
              OutlinedButton.icon(
                onPressed: report == null ? null : () => _export(record, pdf: false),
                icon: const Icon(Icons.data_object, size: 14),
                label: const Text('Export JSON'),
              ),
              OutlinedButton.icon(
                onPressed: report == null ? null : () => _export(record, pdf: true),
                icon: const Icon(Icons.picture_as_pdf_outlined, size: 14),
                label: const Text('Export PDF'),
              ),
              OutlinedButton.icon(
                onPressed: () {
                  ref.read(commandDraftProvider.notifier).set(record.commandText);
                  context.go(JockyDestination.commandCenter.path);
                },
                icon: const Icon(Icons.edit_outlined, size: 14),
                label: const Text('Load command'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Future<void> _export(ExecutionRecord record, {required bool pdf}) async {
    setState(() {
      _exportMessage = null;
      _exportFailure = null;
    });

    final report = record.report!;
    final suggested = '${report.reportId}.${pdf ? 'pdf' : 'json'}';
    final path = await ref.read(fileSelectionProvider).pickSaveLocation(
          suggestedName: suggested,
          extension: pdf ? 'pdf' : 'json',
        );
    if (path == null) return;

    final exporter = ref.read(reportExportProvider);
    final caseTitle = record.caseId == null
        ? null
        : ref
            .read(recordsControllerProvider)
            .records
            .investigations
            .where((c) => c.id == record.caseId)
            .firstOrNull
            ?.title;

    try {
      if (pdf) {
        await exporter.writePdf(path, report, caseTitle: caseTitle);
      } else {
        await exporter.writeJson(path, report);
      }
      if (!mounted) return;
      setState(() {
        _exportMessage = pdf && pdfEscapingRequired(report)
            // Said plainly: the printed form is readable but not literal.
            ? 'Written to $path. This report contains characters the PDF core '
                'fonts cannot draw; they appear as \\u{XXXX} codepoint escapes. '
                'Export JSON for the verbatim text.'
            : 'Written to $path';
      });
    } on JockyFailure catch (failure) {
      if (mounted) setState(() => _exportFailure = failure);
    }
  }
}
