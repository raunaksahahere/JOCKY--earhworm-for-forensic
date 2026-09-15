import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/errors/failure.dart';
import '../../core/theme/tokens.dart';
import '../../core/utils/format.dart';
import '../../state/providers.dart';
import '../../widgets/panel.dart';

/// What this investigation can produce, and how large each one is.
///
/// Asked of the engine rather than estimated here. The engine renders the
/// documents to answer, so the page counts shown are the ones in the files. A
/// client that guessed them would eventually be wrong, and a wrong page count
/// on a forensic report is the kind of small dishonesty that costs trust in
/// everything beside it.
final investigationArtifactsProvider =
    FutureProvider.autoDispose.family<Map<String, dynamic>, String>((ref, caseId) async {
  return ref.watch(apiClientProvider)
      .jsonRequest('/api/v1/investigations/$caseId/artifacts-available');
});

/// The four things an investigator can take away from a finished collection.
///
/// Presented as three questions and a tool, in the order they get asked:
/// what do I need to know, tell me about this one thing, show me everything.
class ArtifactExports extends ConsumerStatefulWidget {
  const ArtifactExports({super.key, required this.caseId});

  final String caseId;

  @override
  ConsumerState<ArtifactExports> createState() => _ArtifactExportsState();
}

class _ArtifactExportsState extends ConsumerState<ArtifactExports> {
  String? _notice;
  String? _error;
  String? _busy;

  Future<void> _save({
    required String label,
    required String path,
    required String suggestedName,
    required String extension,
    Map<String, dynamic> body = const {},
  }) async {
    final destination = await ref.read(fileSelectionProvider)
        .pickSaveLocation(suggestedName: suggestedName, extension: extension);
    if (destination == null) return;
    setState(() {
      _busy = label;
      _error = null;
      _notice = null;
    });
    try {
      final response = await ref.read(apiClientProvider).request(path, body: body);
      await File(destination).writeAsBytes(response.bodyBytes);
      if (mounted) {
        setState(() => _notice = '$label written to $destination '
            '(${formatBytes(response.bodyBytes.length)})');
      }
    } on JockyFailure catch (failure) {
      if (mounted) setState(() => _error = failure.message);
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final available = ref.watch(investigationArtifactsProvider(widget.caseId));

    return Panel(
      title: 'Investigation artifacts',
      subtitle: 'Three documents, each answering a different question. The investigator report '
          'is short by design; nothing was removed from the evidence to make it so.',
      actions: [
        IconButton(
          tooltip: 'Recalculate',
          onPressed: () => ref.invalidate(investigationArtifactsProvider(widget.caseId)),
          icon: const Icon(Icons.refresh, size: 18),
        ),
      ],
      child: available.when(
        loading: () => const Padding(
          padding: EdgeInsets.symmetric(vertical: JockySpace.lg),
          child: Center(child: CircularProgressIndicator()),
        ),
        error: (error, _) => Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SelectableText('$error', style: const TextStyle(color: JockyColors.danger)),
            const SizedBox(height: JockySpace.sm),
            OutlinedButton(
              onPressed: () => ref.invalidate(investigationArtifactsProvider(widget.caseId)),
              child: const Text('Try again'),
            ),
          ],
        ),
        data: (payload) => Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _card(
              key: 'artifact-investigator-report',
              question: 'What do I need to know?',
              title: 'Investigator report',
              metrics: _metrics(payload['investigator_report'], ['pages', 'bytes']),
              description: '${payload['investigator_report']?['description'] ?? ''}',
              action: 'Generate',
              onPressed: () => _save(
                label: 'Investigator report',
                path: '/api/v1/investigations/${widget.caseId}/report/export',
                suggestedName: '${payload['investigator_report']?['name']}',
                extension: 'pdf',
                body: const {'format': 'pdf'},
              ),
            ),
            _card(
              key: 'artifact-review-brief',
              question: 'Tell me about this one thing.',
              title: 'Review brief',
              metrics: [
                '1–2 pages per subject',
                '${payload['review_briefs']?['generated'] ?? 0} generated so far',
              ],
              description: '${payload['review_briefs']?['description'] ?? ''}',
              action: null,
              hint: 'Open any record, finding or thread and choose Review brief.',
            ),
            _card(
              key: 'artifact-evidence-package',
              question: 'Show me everything.',
              title: 'Evidence package',
              metrics: [
                '${payload['evidence_package']?['records'] ?? 0} records',
                'complete, with a manifest and a digest per file',
              ],
              description: '${payload['evidence_package']?['description'] ?? ''}',
              action: 'Export',
              onPressed: () => _save(
                label: 'Evidence package',
                path: '/api/v1/investigations/${widget.caseId}/package',
                suggestedName: '${payload['evidence_package']?['name']}',
                extension: 'zip',
              ),
            ),
            const Divider(height: JockySpace.xl),
            _card(
              key: 'artifact-routine-report',
              question: 'Optional',
              title: 'Routine activity report',
              metrics: _metrics(payload['routine_activity'], ['pages', 'groups', 'records']),
              description: '${payload['routine_activity']?['description'] ?? ''}',
              action: 'Export',
              onPressed: () => _save(
                label: 'Routine activity report',
                path: '/api/v1/investigations/${widget.caseId}/routine/export',
                suggestedName: '${payload['routine_activity']?['name']}',
                extension: 'pdf',
              ),
            ),
            _card(
              key: 'artifact-full-report',
              question: 'Rarely wanted',
              title: 'Full report with every appendix',
              metrics: const ['long — grows with the evidence collected'],
              description: 'The investigator report with all appendices appended. Kept because '
                  'nothing was removed, not because it is the one to read.',
              action: 'Export',
              onPressed: () => _save(
                label: 'Full report',
                path: '/api/v1/investigations/${widget.caseId}/report/export',
                suggestedName: 'JOCKY_Full_Report_${widget.caseId}.pdf',
                extension: 'pdf',
                body: const {'format': 'pdf', 'detailed': true},
              ),
            ),
            if (_notice != null) ...[
              const SizedBox(height: JockySpace.sm),
              SelectableText(_notice!, style: const TextStyle(fontSize: 12)),
            ],
            if (_error != null) ...[
              const SizedBox(height: JockySpace.sm),
              SelectableText(_error!,
                  style: const TextStyle(fontSize: 12, color: JockyColors.danger)),
            ],
          ],
        ),
      ),
    );
  }

  List<String> _metrics(Object? source, List<String> keys) {
    final record = source is Map ? source : const {};
    return [
      for (final key in keys)
        if (record[key] != null)
          key == 'bytes'
              ? formatBytes(record[key] as int)
              : '${record[key]} ${key == 'pages' ? 'pages' : key}',
    ];
  }

  Widget _card({
    required String key,
    required String question,
    required String title,
    required List<String> metrics,
    required String description,
    String? action,
    String? hint,
    VoidCallback? onPressed,
  }) {
    final running = _busy == title || _busy == '$title report';
    return Padding(
      padding: const EdgeInsets.only(bottom: JockySpace.md),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(question.toUpperCase(),
                    style: const TextStyle(fontSize: 9.5, letterSpacing: 0.6,
                        fontWeight: FontWeight.w700, color: JockyColors.textMuted)),
                const SizedBox(height: 2),
                Text(title, style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600)),
                if (metrics.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text(metrics.join('  ·  '),
                        style: const TextStyle(fontSize: 12, color: JockyColors.accent)),
                  ),
                Padding(
                  padding: const EdgeInsets.only(top: 3, right: JockySpace.md),
                  child: Text(description,
                      style: const TextStyle(fontSize: 11.5, color: JockyColors.textMuted)),
                ),
                if (hint != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 3),
                    child: Text(hint, style: const TextStyle(fontSize: 11.5)),
                  ),
              ],
            ),
          ),
          if (action != null)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: FilledButton(
                key: Key(key),
                onPressed: running ? null : onPressed,
                child: Text(running ? 'Working…' : action),
              ),
            ),
        ],
      ),
    );
  }
}
