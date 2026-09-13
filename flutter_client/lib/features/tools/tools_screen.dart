import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/tokens.dart';
import '../../models/executions/execution_record.dart';
import '../../state/providers.dart';
import '../../widgets/empty_state.dart';
import '../../widgets/failure_view.dart';
import '../../widgets/mono_value.dart';
import '../../widgets/panel.dart';
import '../../widgets/results/result_view.dart';
import '../../widgets/status_chip.dart';
import 'tool_definitions.dart';

/// Guided forms over the engine's published actions.
///
/// Every tool shows the exact command it will submit before it runs, and
/// submits through the same execution path as the Command Center.
class ToolsScreen extends ConsumerStatefulWidget {
  const ToolsScreen({super.key});

  @override
  ConsumerState<ToolsScreen> createState() => _ToolsScreenState();
}

class _ToolsScreenState extends ConsumerState<ToolsScreen> {
  ToolDefinition? _active;
  final Map<String, TextEditingController> _controllers = {};

  @override
  void dispose() {
    for (final controller in _controllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  TextEditingController _controllerFor(ToolDefinition tool, ToolField field) =>
      _controllers.putIfAbsent(
        '${tool.referenceName}:${field.key}',
        TextEditingController.new,
      );

  Map<String, String> _values(ToolDefinition tool) => {
        for (final field in tool.fields)
          field.key: _controllerFor(tool, field).text.trim(),
      };

  bool _ready(ToolDefinition tool) => tool.fields
      .where((field) => field.required)
      .every((field) => _controllerFor(tool, field).text.trim().isNotEmpty);

  @override
  Widget build(BuildContext context) {
    final reference = ref.watch(commandReferenceProvider);
    final execution = ref.watch(executionControllerProvider);
    final settings = ref.watch(settingsControllerProvider);

    return reference.when(
      loading: () => const Center(
        child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)),
      ),
      error: (error, _) => Padding(
        padding: const EdgeInsets.all(JockySpace.xl),
        child: EmptyState(
          icon: Icons.construction_outlined,
          title: 'Tools are unavailable',
          description: 'The engine\'s command reference could not be read: $error',
          action: FilledButton(
            onPressed: () => ref.invalidate(commandReferenceProvider),
            child: const Text('Retry'),
          ),
        ),
      ),
      data: (value) {
        final (catalogue, failure) = value;
        if (failure != null) {
          return Padding(
            padding: const EdgeInsets.all(JockySpace.xl),
            child: FailureView(
              failure: failure,
              onRetry: () => ref.invalidate(commandReferenceProvider),
            ),
          );
        }

        final published = catalogue.entries.map((e) => e.name).toSet();
        // Only offer what this engine build actually publishes.
        final available = toolDefinitions
            .where((tool) => published.contains(tool.referenceName))
            .toList(growable: false);
        final unpublished = toolDefinitions
            .where((tool) => !published.contains(tool.referenceName))
            .toList(growable: false);

        if (available.isEmpty) {
          return const Padding(
            padding: EdgeInsets.all(JockySpace.xl),
            child: EmptyState(
              icon: Icons.construction_outlined,
              title: 'This engine publishes no actions this client has a form for',
              description:
                  'Use the Command Center, which submits whatever the engine\'s parser accepts.',
            ),
          );
        }

        final active = _active ?? available.first;

        return Padding(
          padding: const EdgeInsets.all(JockySpace.lg),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SizedBox(
                width: 280,
                child: Panel(
                  title: 'Guided actions',
                  subtitle: '${available.length} published by the engine',
                  padding: EdgeInsets.zero,
                  child: ListView(
                    padding: const EdgeInsets.all(JockySpace.sm),
                    children: [
                      for (final tool in available)
                        _ToolTile(
                          tool: tool,
                          active: tool.referenceName == active.referenceName,
                          onTap: () => setState(() => _active = tool),
                        ),
                      if (unpublished.isNotEmpty) ...[
                        const SizedBox(height: JockySpace.md),
                        const Padding(
                          padding: EdgeInsets.symmetric(horizontal: JockySpace.sm),
                          child: Text(
                            'NOT PUBLISHED BY THIS ENGINE',
                            style: TextStyle(
                              fontSize: 9.5,
                              letterSpacing: 0.8,
                              fontWeight: FontWeight.w700,
                              color: JockyColors.textFaint,
                            ),
                          ),
                        ),
                        const SizedBox(height: 6),
                        for (final tool in unpublished)
                          Padding(
                            padding: const EdgeInsets.symmetric(
                              horizontal: JockySpace.md,
                              vertical: 3,
                            ),
                            child: Text(
                              tool.title,
                              style: const TextStyle(
                                fontSize: 11.5,
                                color: JockyColors.textFaint,
                              ),
                            ),
                          ),
                      ],
                    ],
                  ),
                ),
              ),
              const SizedBox(width: JockySpace.lg),
              Expanded(child: _form(active, execution, settings.displayUtc)),
            ],
          ),
        );
      },
    );
  }

  Widget _form(ToolDefinition tool, ExecutionState execution, bool displayUtc) {
    final preview = tool.build(_values(tool));
    final ready = _ready(tool);
    final running = execution.isRunning;
    final showResult = execution.record?.origin == ExecutionOrigin.guidedTool;

    return Panel(
      title: tool.title,
      subtitle: tool.referenceName,
      padding: EdgeInsets.zero,
      child: ListView(
        padding: const EdgeInsets.all(JockySpace.lg),
        children: [
          Text(
            tool.summary,
            style: const TextStyle(fontSize: 12.5, height: 1.55, color: JockyColors.textMuted),
          ),
          if (tool.destructive) ...[
            const SizedBox(height: JockySpace.md),
            Container(
              padding: const EdgeInsets.all(JockySpace.md),
              decoration: BoxDecoration(
                color: JockyColors.dangerWash,
                border: Border.all(color: JockyColors.danger.withValues(alpha: 0.45)),
                borderRadius: BorderRadius.circular(JockyRadius.md),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(Icons.dangerous_outlined, size: 15, color: JockyColors.danger),
                  const SizedBox(width: JockySpace.sm),
                  Expanded(
                    child: Text(
                      tool.destructiveWarning!,
                      style: const TextStyle(fontSize: 12, height: 1.5),
                    ),
                  ),
                ],
              ),
            ),
          ],
          const SizedBox(height: JockySpace.lg),
          if (tool.fields.isEmpty)
            const Text(
              'This action takes no arguments.',
              style: TextStyle(fontSize: 12, color: JockyColors.textFaint),
            ),
          for (final field in tool.fields) ...[
            Text(field.label, style: const TextStyle(fontSize: 11.5, color: JockyColors.textMuted)),
            const SizedBox(height: 5),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _controllerFor(tool, field),
                    onChanged: (_) => setState(() {}),
                    style: const TextStyle(fontFamily: JockyType.mono, fontSize: 12.5),
                    decoration: InputDecoration(hintText: field.hint),
                  ),
                ),
                if (field.kind != ToolFieldKind.text) ...[
                  const SizedBox(width: JockySpace.sm),
                  OutlinedButton.icon(
                    onPressed: () async {
                      final selection = ref.read(fileSelectionProvider);
                      final path = field.kind == ToolFieldKind.filePath
                          ? await selection.pickFile()
                          : await selection.pickDirectory();
                      if (path == null) return;
                      _controllerFor(tool, field).text = path;
                      setState(() {});
                    },
                    icon: Icon(
                      field.kind == ToolFieldKind.filePath
                          ? Icons.insert_drive_file_outlined
                          : Icons.folder_outlined,
                      size: 14,
                    ),
                    label: const Text('Browse'),
                  ),
                ],
              ],
            ),
            const SizedBox(height: JockySpace.md),
          ],
          const SizedBox(height: JockySpace.sm),
          SectionLabel('Command to be submitted'),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(JockySpace.md),
            decoration: BoxDecoration(
              color: JockyColors.canvas,
              border: Border.all(color: JockyColors.border),
              borderRadius: BorderRadius.circular(JockyRadius.md),
            ),
            child: MonoValue(
              ready ? preview : 'Complete the fields above to build the command.',
              fontSize: 12.5,
              color: ready ? JockyColors.accent : JockyColors.textFaint,
              copyable: ready,
            ),
          ),
          const SizedBox(height: JockySpace.sm),
          const Text(
            'The engine parses and validates this text; this form does not.',
            style: TextStyle(fontSize: 10.5, color: JockyColors.textFaint),
          ),
          const SizedBox(height: JockySpace.lg),
          Row(
            children: [
              FilledButton.icon(
                onPressed: !ready || running ? null : () => _run(tool, preview),
                style: tool.destructive
                    ? FilledButton.styleFrom(backgroundColor: JockyColors.danger)
                    : null,
                icon: running
                    ? const SizedBox(
                        width: 13,
                        height: 13,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : Icon(tool.destructive ? Icons.warning_amber : Icons.play_arrow_rounded,
                        size: 16),
                label: Text(running ? 'Observing…' : 'Run observation'),
              ),
              const SizedBox(width: JockySpace.sm),
              OutlinedButton.icon(
                onPressed: !ready
                    ? null
                    : () => ref.read(commandDraftProvider.notifier).set(preview),
                icon: const Icon(Icons.edit_outlined, size: 14),
                label: const Text('Send to editor'),
              ),
            ],
          ),
          if (showResult) ...[
            const SizedBox(height: JockySpace.xl),
            const Divider(),
            const SizedBox(height: JockySpace.lg),
            if (execution.failure != null)
              FailureView(failure: execution.failure!)
            else if (execution.response?.result != null) ...[
              Row(
                children: [
                  const StatusChip(label: 'Observation returned', tone: StatusTone.ok),
                  const SizedBox(width: JockySpace.sm),
                  if (execution.record?.reportId != null)
                    MonoValue(
                      execution.record!.reportId,
                      fontSize: 11.5,
                      color: JockyColors.accent,
                    ),
                ],
              ),
              const SizedBox(height: JockySpace.md),
              ResultView(result: execution.response!.result!, displayUtc: displayUtc),
            ],
          ],
        ],
      ),
    );
  }

  Future<void> _run(ToolDefinition tool, String command) async {
    if (tool.destructive) {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          backgroundColor: JockyColors.surface,
          title: const Text('Overwrite this file?', style: TextStyle(fontSize: 15)),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(tool.destructiveWarning!, style: const TextStyle(fontSize: 12.5, height: 1.5)),
              const SizedBox(height: JockySpace.md),
              MonoValue(command, fontSize: 12),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: JockyColors.danger),
              onPressed: () => Navigator.of(context).pop(true),
              child: const Text('Overwrite the file'),
            ),
          ],
        ),
      );
      if (!(confirmed ?? false)) return;
    }

    await ref
        .read(executionControllerProvider.notifier)
        .execute(command, origin: ExecutionOrigin.guidedTool);
    if (mounted) setState(() {});
  }
}

class _ToolTile extends StatelessWidget {
  const _ToolTile({required this.tool, required this.active, required this.onTap});

  final ToolDefinition tool;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(JockyRadius.md),
      child: Container(
        margin: const EdgeInsets.only(bottom: 3),
        padding: const EdgeInsets.symmetric(
          horizontal: JockySpace.md,
          vertical: JockySpace.sm,
        ),
        decoration: BoxDecoration(
          color: active ? JockyColors.accentWash : Colors.transparent,
          borderRadius: BorderRadius.circular(JockyRadius.md),
          border: Border.all(
            color: active ? JockyColors.accent.withValues(alpha: 0.35) : Colors.transparent,
          ),
        ),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    tool.title,
                    style: TextStyle(
                      fontSize: 12.5,
                      fontWeight: active ? FontWeight.w600 : FontWeight.w500,
                      color: active ? JockyColors.text : JockyColors.textMuted,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    tool.referenceName,
                    style: const TextStyle(
                      fontSize: 10,
                      fontFamily: JockyType.mono,
                      color: JockyColors.textFaint,
                    ),
                  ),
                ],
              ),
            ),
            if (tool.destructive)
              const Tooltip(
                message: 'Modifies the target file',
                child: Icon(Icons.dangerous_outlined, size: 13, color: JockyColors.danger),
              ),
          ],
        ),
      ),
    );
  }
}
