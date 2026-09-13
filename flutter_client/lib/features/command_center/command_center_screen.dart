import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/shortcuts.dart';
import '../../core/theme/tokens.dart';
import '../../core/utils/format.dart';
import '../../models/commands/command_reference.dart';
import '../../models/executions/execution_record.dart';
import '../../state/providers.dart';
import '../../widgets/empty_state.dart';
import '../../widgets/failure_view.dart';
import '../../widgets/mono_value.dart';
import '../../widgets/panel.dart';
import '../../widgets/results/result_view.dart';
import '../../widgets/status_chip.dart';
import 'command_editor.dart';

/// The primary workflow: compose a command, submit it to the engine, read the
/// structured result.
///
/// Nothing here parses or validates the command. The execute action is enabled
/// whenever there is text and the engine is reachable; every rejection comes
/// back from the Python parser and is shown verbatim.
class CommandCenterScreen extends ConsumerStatefulWidget {
  const CommandCenterScreen({super.key});

  @override
  ConsumerState<CommandCenterScreen> createState() => _CommandCenterScreenState();
}

class _CommandCenterScreenState extends ConsumerState<CommandCenterScreen> {
  late final CommandHighlightController _controller;
  final _focusNode = FocusNode(debugLabel: 'command-editor');
  Timer? _ticker;
  bool _referenceOpen = true;

  @override
  void initState() {
    super.initState();
    _controller = CommandHighlightController(text: ref.read(commandDraftProvider));
    _controller.addListener(_syncDraft);
  }

  void _syncDraft() {
    final draft = ref.read(commandDraftProvider);
    if (draft != _controller.text) {
      ref.read(commandDraftProvider.notifier).set(_controller.text);
    }
  }

  @override
  void dispose() {
    _ticker?.cancel();
    _controller.removeListener(_syncDraft);
    _controller.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  Future<void> _execute() async {
    final text = _controller.text.trim();
    if (text.isEmpty) return;
    if (ref.read(executionControllerProvider).isRunning) return;

    // Live elapsed counter while the engine works.
    _ticker?.cancel();
    _ticker = Timer.periodic(const Duration(milliseconds: 100), (_) {
      if (mounted) setState(() {});
    });

    await ref.read(executionControllerProvider.notifier).execute(text);
    _ticker?.cancel();
    _ticker = null;
    if (mounted) setState(() {});
  }

  Future<void> _pickEvidence() async {
    final path = await ref.read(fileSelectionProvider).pickFile();
    if (path == null) return;
    _insertPath(path);
  }

  void _insertPath(String path) {
    // Quote only when the path contains whitespace: the command language has no
    // escape sequences, so a quote added anywhere else would change the target.
    final needsQuotes = path.contains(' ') || path.contains('\t');
    final quoted = !needsQuotes
        ? path
        : path.contains('"')
        ? "'$path'"
        : '"$path"';
    final selection = _controller.selection;
    final base = _controller.text;
    final insertAt = selection.isValid ? selection.baseOffset : base.length;
    final next = base.substring(0, insertAt) + quoted + base.substring(insertAt);
    _controller.value = TextEditingValue(
      text: next,
      selection: TextSelection.collapsed(offset: insertAt + quoted.length),
    );
    _focusNode.requestFocus();
  }

  @override
  Widget build(BuildContext context) {
    // Adopt commands loaded from Tools, History or the palette.
    ref.listen<String>(commandDraftProvider, (previous, next) {
      if (next != _controller.text) {
        _controller.value = TextEditingValue(
          text: next,
          selection: TextSelection.collapsed(offset: next.length),
        );
        _focusNode.requestFocus();
      }
    });

    final execution = ref.watch(executionControllerProvider);
    final ready = ref.watch(backendReadyProvider);
    final settings = ref.watch(settingsControllerProvider);
    final wide = MediaQuery.sizeOf(context).width >= 1240;

    final editor = _editorPanel(execution, ready);
    final results = _resultPanel(execution, settings.displayUtc);
    final reference = _referencePanel();

    return Actions(
      actions: {
        ExecuteCommandIntent: CallbackAction<ExecuteCommandIntent>(
          onInvoke: (_) {
            _execute();
            return null;
          },
        ),
        SelectEvidenceIntent: CallbackAction<SelectEvidenceIntent>(
          onInvoke: (_) {
            _pickEvidence();
            return null;
          },
        ),
      },
      child: Padding(
        padding: const EdgeInsets.all(JockySpace.lg),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  editor,
                  const SizedBox(height: JockySpace.lg),
                  Expanded(child: results),
                ],
              ),
            ),
            if (wide && _referenceOpen) ...[
              const SizedBox(width: JockySpace.lg),
              SizedBox(width: 320, child: reference),
            ],
          ],
        ),
      ),
    );
  }

  Widget _editorPanel(ExecutionState execution, bool ready) {
    final running = execution.isRunning;

    return Panel(
      title: 'Command',
      subtitle: 'Parsed and validated by the engine. This editor does not check syntax.',
      actions: [
        if (!_referenceOpen)
          TextButton.icon(
            onPressed: () => setState(() => _referenceOpen = true),
            icon: const Icon(Icons.menu_book_outlined, size: 14),
            label: const Text('Reference'),
          ),
      ],
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            decoration: BoxDecoration(
              color: JockyColors.canvas,
              border: Border.all(color: JockyColors.borderStrong),
              borderRadius: BorderRadius.circular(JockyRadius.md),
            ),
            padding: const EdgeInsets.symmetric(horizontal: JockySpace.md, vertical: 2),
            child: Row(
              children: [
                const Text(
                  '›',
                  style: TextStyle(
                    fontFamily: JockyType.mono,
                    fontSize: 16,
                    color: JockyColors.accent,
                  ),
                ),
                const SizedBox(width: JockySpace.sm),
                Expanded(
                  child: TextField(
                    controller: _controller,
                    focusNode: _focusNode,
                    autofocus: true,
                    enabled: !running,
                    onSubmitted: (_) => _execute(),
                    maxLines: 1,
                    style: const TextStyle(
                      fontFamily: JockyType.mono,
                      fontSize: 14,
                      height: 1.6,
                    ),
                    decoration: const InputDecoration(
                      filled: false,
                      border: InputBorder.none,
                      enabledBorder: InputBorder.none,
                      focusedBorder: InputBorder.none,
                      hintText: 'HASH FILE "/evidence/case 1/image.bin"',
                      contentPadding: EdgeInsets.symmetric(vertical: 14),
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: JockySpace.md),
          // Wrapped so the action row reflows instead of clipping controls on a
          // narrow window; the execution state stays pinned to the right.
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Expanded(
                child: Wrap(
                  spacing: JockySpace.sm,
                  runSpacing: JockySpace.sm,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    FilledButton.icon(
                      onPressed: running ? null : _execute,
                      icon: running
                          ? const SizedBox(
                              width: 13,
                              height: 13,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.play_arrow_rounded, size: 16),
                      label: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(running ? 'Observing…' : 'Execute'),
                          const SizedBox(width: 8),
                          const KeyHint(['Ctrl', '↵']),
                        ],
                      ),
                    ),
                    if (running)
                      OutlinedButton.icon(
                        onPressed: () =>
                            ref.read(executionControllerProvider.notifier).abandon(),
                        icon: const Icon(Icons.stop_circle_outlined, size: 14),
                        label: const Text('Abandon wait'),
                      )
                    else ...[
                      OutlinedButton.icon(
                        onPressed: _pickEvidence,
                        icon: const Icon(Icons.folder_open_outlined, size: 14),
                        label: const Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text('Evidence file'),
                            SizedBox(width: 6),
                            KeyHint(['Ctrl', 'O']),
                          ],
                        ),
                      ),
                      OutlinedButton.icon(
                        onPressed: () async {
                          final path = await ref.read(fileSelectionProvider).pickDirectory();
                          if (path != null) _insertPath(path);
                        },
                        icon: const Icon(Icons.folder_copy_outlined, size: 14),
                        label: const Text('Directory'),
                      ),
                      TextButton(
                        onPressed: () {
                          _controller.clear();
                          ref.read(commandDraftProvider.notifier).clear();
                          ref.read(executionControllerProvider.notifier).reset();
                          setState(() {});
                        },
                        child: const Text('Clear'),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: JockySpace.md),
              _ExecutionStateStrip(execution: execution, ready: ready),
            ],
          ),
          if (!ready) ...[
            const SizedBox(height: JockySpace.md),
            const CapabilityGap(
              capability: 'The engine is not currently reachable',
              explanation:
                  'Commands submitted now will fail at the transport layer. Start or check the '
                  'engine from System Status.',
            ),
          ],
        ],
      ),
    );
  }

  Widget _resultPanel(ExecutionState execution, bool displayUtc) {
    final record = execution.record;
    final response = execution.response;
    final failure = execution.failure;

    return Panel(
      title: 'Result',
      subtitle: record == null
          ? 'The engine returns a structured result and a report for every submission.'
          : 'Report ${record.reportId ?? 'not issued'}',
      actions: [
        if (record?.report != null)
          StatusChip(
            label: 'schema v${record!.report!.schemaVersion ?? '?'}',
            tone: StatusTone.neutral,
            dense: true,
          ),
      ],
      padding: EdgeInsets.zero,
      child: Builder(
        builder: (context) {
          if (execution.isRunning) {
            return const EmptyState(
              icon: Icons.hourglass_top_outlined,
              title: 'The engine is observing',
              description: 'The dispatcher runs synchronously. The result and its report arrive together.',
            );
          }
          if (failure == null && response == null) {
            return const EmptyState(
              icon: Icons.terminal_outlined,
              title: 'No command submitted yet',
              description:
                  'Compose a command above, or open the palette with Ctrl+K to load a '
                  'backend-published example.',
            );
          }

          return SingleChildScrollView(
            padding: const EdgeInsets.all(JockySpace.lg),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (record != null) _provenance(record, displayUtc),
                if (failure != null) ...[
                  const SizedBox(height: JockySpace.md),
                  FailureView(failure: failure, onRetry: _execute),
                  if (failure.report != null && failure.report!.warnings.isNotEmpty) ...[
                    const SizedBox(height: JockySpace.md),
                    WarningList(warnings: failure.report!.warnings),
                  ],
                ],
                if (response?.result != null) ...[
                  const SizedBox(height: JockySpace.lg),
                  ResultView(result: response!.result!, displayUtc: displayUtc),
                ],
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _provenance(ExecutionRecord record, bool displayUtc) {
    final normalized = record.report?.normalizedCommand;
    return Container(
      padding: const EdgeInsets.all(JockySpace.md),
      decoration: BoxDecoration(
        color: JockyColors.surfaceRaised,
        border: Border.all(color: JockyColors.border),
        borderRadius: BorderRadius.circular(JockyRadius.md),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: JockySpace.sm,
            runSpacing: JockySpace.sm,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              StatusChip(
                label: switch (record.outcome) {
                  ExecutionOutcome.completed => 'Execution completed',
                  ExecutionOutcome.failed => 'Execution failed',
                  ExecutionOutcome.abandoned => 'Wait abandoned',
                },
                tone: switch (record.outcome) {
                  ExecutionOutcome.completed => StatusTone.ok,
                  ExecutionOutcome.failed => StatusTone.danger,
                  ExecutionOutcome.abandoned => StatusTone.neutral,
                },
              ),
              if (normalized != null)
                StatusChip(
                  label: normalized.label,
                  tone: StatusTone.accent,
                  dense: true,
                  tooltip: 'Action and target as parsed by the engine.',
                ),
              StatusChip(
                label: 'engine ${formatDurationMs(record.engineElapsedMs)}',
                tone: StatusTone.neutral,
                dense: true,
                icon: Icons.speed,
                tooltip: 'Engine-measured execution time.',
              ),
              StatusChip(
                label: 'round trip ${record.clientElapsedMs} ms',
                tone: StatusTone.neutral,
                dense: true,
                icon: Icons.sync_alt,
                tooltip: 'Measured by this client, including transport.',
              ),
              StatusChip(
                label: formatTimestamp(record.submittedAt, utc: displayUtc),
                tone: StatusTone.neutral,
                dense: true,
                icon: Icons.schedule,
              ),
            ],
          ),
          const SizedBox(height: JockySpace.sm),
          MonoValue(record.commandText, fontSize: 12, copyable: true),
        ],
      ),
    );
  }

  Widget _referencePanel() {
    final reference = ref.watch(commandReferenceProvider);

    return Panel(
      title: 'Command reference',
      subtitle: 'Published by the engine',
      actions: [
        IconButton(
          tooltip: 'Hide reference',
          onPressed: () => setState(() => _referenceOpen = false),
          iconSize: 15,
          color: JockyColors.textFaint,
          icon: const Icon(Icons.close),
        ),
      ],
      padding: EdgeInsets.zero,
      child: reference.when(
        loading: () => const Center(
          child: Padding(
            padding: EdgeInsets.all(JockySpace.xl),
            child: SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
          ),
        ),
        error: (error, _) => Padding(
          padding: const EdgeInsets.all(JockySpace.md),
          child: Text(
            'The reference could not be loaded: $error',
            style: const TextStyle(fontSize: 11.5, color: JockyColors.textMuted),
          ),
        ),
        data: (value) {
          final (catalogue, failure) = value;
          if (failure != null) {
            return Padding(
              padding: const EdgeInsets.all(JockySpace.md),
              child: FailureView(
                failure: failure,
                compact: true,
                onRetry: () => ref.invalidate(commandReferenceProvider),
              ),
            );
          }
          if (catalogue.entries.isEmpty) {
            return const EmptyState(
              icon: Icons.menu_book_outlined,
              title: 'No commands published',
              description: 'The engine returned an empty reference.',
              compact: true,
            );
          }
          return ListView(
            key: const ValueKey('command-reference-list'),
            padding: const EdgeInsets.all(JockySpace.md),
            children: [
              Text(
                'Schema v${catalogue.schemaVersion ?? '?'} · '
                '${catalogue.entries.length} actions',
                style: const TextStyle(fontSize: 10.5, color: JockyColors.textFaint),
              ),
              const SizedBox(height: JockySpace.md),
              for (final entry in catalogue.entries)
                _ReferenceEntry(
                  entry: entry,
                  onLoad: () => ref.read(commandDraftProvider.notifier).set(entry.example),
                ),
            ],
          );
        },
      ),
    );
  }
}

class _ReferenceEntry extends StatelessWidget {
  const _ReferenceEntry({required this.entry, required this.onLoad});

  final CommandReferenceEntry entry;
  final VoidCallback onLoad;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: JockySpace.sm),
      padding: const EdgeInsets.all(JockySpace.md),
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
              Expanded(
                child: Text(
                  entry.name,
                  style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
                ),
              ),
              StatusChip(label: entry.category, tone: StatusTone.neutral, dense: true),
            ],
          ),
          const SizedBox(height: 6),
          MonoValue(entry.syntax, fontSize: 11, color: JockyColors.accent),
          const SizedBox(height: 5),
          Text(
            entry.description,
            style: const TextStyle(fontSize: 11, height: 1.45, color: JockyColors.textMuted),
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(
                child: MonoValue(entry.example, fontSize: 10.5, color: JockyColors.textFaint),
              ),
              TextButton(
                onPressed: onLoad,
                style: TextButton.styleFrom(
                  padding: const EdgeInsets.symmetric(horizontal: 6),
                  minimumSize: const Size(0, 24),
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                ),
                child: const Text('Load'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _ExecutionStateStrip extends StatelessWidget {
  const _ExecutionStateStrip({required this.execution, required this.ready});

  final ExecutionState execution;
  final bool ready;

  @override
  Widget build(BuildContext context) {
    if (execution.isRunning) {
      final elapsed = execution.elapsed ?? Duration.zero;
      return Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const StatusChip(label: 'Running', tone: StatusTone.info, icon: Icons.bolt),
          const SizedBox(width: JockySpace.sm),
          MonoValue(
            '${(elapsed.inMilliseconds / 1000).toStringAsFixed(1)} s',
            fontSize: 12,
            color: JockyColors.textMuted,
          ),
        ],
      );
    }
    if (!ready) {
      return const StatusChip(label: 'Engine offline', tone: StatusTone.danger);
    }
    return const StatusChip(label: 'Engine ready', tone: StatusTone.ok);
  }
}
