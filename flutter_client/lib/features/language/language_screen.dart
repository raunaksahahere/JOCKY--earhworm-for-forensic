import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/navigation.dart';
import '../../core/errors/failure.dart';
import '../../core/theme/tokens.dart';
import '../../repositories/language_repository.dart';
import '../../state/providers.dart';
import '../../widgets/failure_view.dart';
import '../../widgets/mono_value.dart';
import '../../widgets/panel.dart';
import '../../widgets/status_chip.dart';
import 'language_examples.dart';

/// The JOCKY .x investigation editor.
///
/// This is the language as the investigator meets it: write a program, compile
/// it, read the IR and the plan the compiler produced, then run it. Nothing on
/// this screen interprets the language itself — every result comes back from
/// the engine's compiler, which is the same one a collection runs through, so
/// what is shown here is what will actually execute.
class LanguageScreen extends ConsumerStatefulWidget {
  const LanguageScreen({super.key});

  @override
  ConsumerState<LanguageScreen> createState() => _LanguageScreenState();
}

class _LanguageScreenState extends ConsumerState<LanguageScreen> {
  late final TextEditingController _editor =
      TextEditingController(text: jockyExamples.first.source);
  String _exampleName = jockyExamples.first.name;
  String _platform = 'linux';

  CompiledProgram? _compiled;
  JockyFailure? _failure;
  bool _busy = false;
  String? _startedInvestigation;

  @override
  void dispose() {
    _editor.dispose();
    super.dispose();
  }

  Future<void> _compile() async {
    setState(() {
      _busy = true;
      _failure = null;
      _startedInvestigation = null;
    });
    try {
      final compiled = await ref
          .read(languageRepositoryProvider)
          .compile(_editor.text, platform: _platform);
      if (mounted) setState(() => _compiled = compiled);
    } on JockyFailure catch (failure) {
      // A program error is the compiler answering, not the app breaking: the
      // previous IR is cleared so nothing stale is read as current.
      if (mounted) {
        setState(() {
          _failure = failure;
          _compiled = null;
        });
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _run() async {
    setState(() {
      _busy = true;
      _failure = null;
    });
    try {
      final caseId = ref.read(apiClientProvider).activeCaseId;
      final id = await ref.read(languageRepositoryProvider).run(
            program: _editor.text,
            title: 'JOCKY .x investigation',
            caseId: caseId,
          );
      if (mounted) setState(() => _startedInvestigation = id);
    } on JockyFailure catch (failure) {
      if (mounted) setState(() => _failure = failure);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _loadExample(JockyExample example) {
    setState(() {
      _editor.text = example.source;
      _exampleName = example.name;
      _compiled = null;
      _failure = null;
      _startedInvestigation = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, constraints) {
      final narrow = constraints.maxWidth < 1000;
      final editor = _buildEditor(context);
      final output = _buildOutput(context);
      if (narrow) {
        return ListView(
          padding: const EdgeInsets.all(JockySpace.lg),
          children: [
            SizedBox(height: 420, child: editor),
            const SizedBox(height: JockySpace.lg),
            output,
          ],
        );
      }
      return Padding(
        padding: const EdgeInsets.all(JockySpace.lg),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(flex: 5, child: editor),
            const SizedBox(width: JockySpace.lg),
            Expanded(flex: 4, child: SingleChildScrollView(child: output)),
          ],
        ),
      );
    });
  }

  Widget _buildEditor(BuildContext context) {
    return Panel(
      title: 'JOCKY .x Investigation',
      subtitle: 'A program states what the investigation needs. It cannot name a '
          'command to run.',
      padding: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // The controls live in the body rather than the panel header: there
          // are four of them, and a header row cannot wrap.
          Padding(
            padding: const EdgeInsets.fromLTRB(
                JockySpace.lg, JockySpace.md, JockySpace.lg, 0),
            child: Wrap(
              spacing: JockySpace.sm,
              runSpacing: JockySpace.sm,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                PopupMenuButton<JockyExample>(
                  tooltip: 'Load an example program',
                  onSelected: _loadExample,
                  itemBuilder: (context) => [
                    for (final example in jockyExamples)
                      PopupMenuItem(
                        value: example,
                        child: Text('${example.name}.x  —  ${example.summary}'),
                      ),
                  ],
                  child: const _ToolbarButton(
                      icon: Icons.folder_open_outlined, label: 'Examples'),
                ),
                DropdownButton<String>(
                  value: _platform,
                  underline: const SizedBox.shrink(),
                  items: const [
                    DropdownMenuItem(value: 'linux', child: Text('Plan for linux')),
                    DropdownMenuItem(value: 'windows', child: Text('Plan for windows')),
                  ],
                  onChanged: _busy
                      ? null
                      : (value) {
                          if (value != null) setState(() => _platform = value);
                        },
                ),
                FilledButton.icon(
                  onPressed: _busy ? null : _compile,
                  icon: const Icon(Icons.play_circle_outline, size: 18),
                  label: const Text('Compile'),
                ),
                OutlinedButton.icon(
                  // Running an uncompiled program is how an investigator
                  // discovers a syntax error halfway through a collection.
                  onPressed: _busy || _compiled == null ? null : _run,
                  icon: const Icon(Icons.bolt_outlined, size: 18),
                  label: const Text('Run investigation'),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(
                JockySpace.lg, JockySpace.md, JockySpace.lg, 0),
            child: Text('examples/$_exampleName.x',
                style: const TextStyle(
                    fontFamily: JockyType.mono,
                    fontSize: 11,
                    color: JockyColors.textFaint)),
          ),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.all(JockySpace.lg),
              child: TextField(
                controller: _editor,
                maxLines: null,
                expands: true,
                textAlignVertical: TextAlignVertical.top,
                style: const TextStyle(
                    fontFamily: JockyType.mono, fontSize: 12.5, height: 1.5),
                decoration: const InputDecoration(
                  filled: true,
                  fillColor: JockyColors.canvas,
                  border: OutlineInputBorder(),
                  hintText: 'CASE "..."\nTARGET "host"\nCOLLECT PROCESSES\nREPORT SUMMARY',
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildOutput(BuildContext context) {
    final failure = _failure;
    final compiled = _compiled;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (failure != null)
          Panel(
            title: 'Compilation failed',
            child: FailureView(failure: failure, onRetry: _compile),
          )
        else if (compiled == null)
          const Panel(
            title: 'Not compiled yet',
            child: Text(
              'Compile the program to see the intermediate representation it '
              'produces and the execution plan built from it. Nothing is '
              'collected until the investigation is run.',
              style: TextStyle(color: JockyColors.textMuted),
            ),
          )
        else ...[
          _statusPanel(compiled),
          const SizedBox(height: JockySpace.lg),
          _textPanel('Intermediate representation',
              'Platform-neutral. It names what the investigation needs, never how '
                  'an operating system provides it.',
              compiled.explanation),
          const SizedBox(height: JockySpace.lg),
          _textPanel('Execution plan — ${compiled.platform}',
              'Built from the IR by the platform adapter. Every task names a '
                  'collector this build implements.',
              compiled.planExplanation),
          if (compiled.conditionalSkips.isNotEmpty) ...[
            const SizedBox(height: JockySpace.lg),
            _skipPanel(
              'Skipped by the program',
              'The program guarded these with WHEN, and the guard is not true on '
                  '${compiled.platform}. This build could have collected them.',
              compiled.conditionalSkips,
              StatusTone.info,
            ),
          ],
          if (compiled.unsupported.isNotEmpty) ...[
            const SizedBox(height: JockySpace.lg),
            _skipPanel(
              'Not available on ${compiled.platform}',
              'This build has no collector for these sources on this platform. '
                  'They are named rather than dropped.',
              compiled.unsupported,
              StatusTone.warn,
            ),
          ],
        ],
        if (_startedInvestigation != null) ...[
          const SizedBox(height: JockySpace.lg),
          Panel(
            title: 'Investigation started',
            child: Row(
              children: [
                Expanded(child: MonoValue(_startedInvestigation, copyable: true)),
                TextButton(
                  onPressed: () => context.go(
                      '${JockyDestination.investigations.path}/$_startedInvestigation'),
                  child: const Text('Open'),
                ),
              ],
            ),
          ),
        ],
      ],
    );
  }

  Widget _statusPanel(CompiledProgram compiled) => Panel(
        title: 'Compiled',
        child: Wrap(
          spacing: JockySpace.sm,
          runSpacing: JockySpace.sm,
          children: [
            const StatusChip(
                label: 'Semantics validated', tone: StatusTone.ok, icon: Icons.check_circle_outline),
            StatusChip(label: 'IR v${compiled.irVersion}', tone: StatusTone.neutral),
            StatusChip(label: 'Plan v${compiled.planVersion}', tone: StatusTone.neutral),
            StatusChip(
                label: '${compiled.collections.length} collection(s)', tone: StatusTone.neutral),
            StatusChip(label: '${compiled.readyTaskCount} ready task(s)', tone: StatusTone.accent),
            for (final playbook in compiled.playbooks)
              StatusChip(label: 'playbook $playbook', tone: StatusTone.info),
            if (!compiled.platformValidated)
              const StatusChip(
                label: 'Platform NOT VALIDATED on a real host',
                tone: StatusTone.warn,
                icon: Icons.warning_amber_outlined,
                tooltip: 'No plan built by this adapter has been executed against a real '
                    'host of this platform.',
              ),
          ],
        ),
      );

  Widget _textPanel(String title, String subtitle, String body) => Panel(
        title: title,
        subtitle: subtitle,
        actions: [
          IconButton(
            tooltip: 'Copy',
            iconSize: 18,
            onPressed: () => Clipboard.setData(ClipboardData(text: body)),
            icon: const Icon(Icons.copy_all_outlined),
          ),
        ],
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.all(JockySpace.md),
          decoration: BoxDecoration(
            color: JockyColors.canvas,
            borderRadius: BorderRadius.circular(JockyRadius.sm),
            border: Border.all(color: JockyColors.border),
          ),
          child: SelectableText(
            body,
            style: const TextStyle(
                fontFamily: JockyType.mono, fontSize: 11.5, height: 1.45),
          ),
        ),
      );

  Widget _skipPanel(
    String title,
    String subtitle,
    List<Map<String, dynamic>> rows,
    StatusTone tone,
  ) =>
      Panel(
        title: title,
        subtitle: subtitle,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (final row in rows)
              Padding(
                padding: const EdgeInsets.only(bottom: JockySpace.sm),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    StatusChip(label: '${row['source']}', tone: tone, dense: true),
                    const SizedBox(width: JockySpace.sm),
                    Expanded(
                      child: Text('${row['detail'] ?? ''}',
                          style: const TextStyle(
                              fontSize: 12, color: JockyColors.textMuted)),
                    ),
                  ],
                ),
              ),
          ],
        ),
      );
}

class _ToolbarButton extends StatelessWidget {
  const _ToolbarButton({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          border: Border.all(color: JockyColors.borderStrong),
          borderRadius: BorderRadius.circular(JockyRadius.sm),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(icon, size: 16, color: JockyColors.textMuted),
          const SizedBox(width: 6),
          Text(label, style: const TextStyle(fontSize: 12, color: JockyColors.text)),
        ]),
      );
}
