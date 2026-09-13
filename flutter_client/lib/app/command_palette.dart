import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/theme/tokens.dart';
import '../state/providers.dart';
import 'navigation.dart';

class _PaletteEntry {
  const _PaletteEntry({
    required this.label,
    required this.group,
    required this.detail,
    required this.onSelect,
    required this.icon,
  });

  final String label;
  final String group;
  final String detail;
  final VoidCallback onSelect;
  final IconData icon;
}

/// Ctrl+K palette: jump to a section, or load a backend-published command
/// example into the editor.
///
/// Selecting a command **loads** it. Nothing in this palette executes anything
/// — an analyst must always see a command before it reaches the engine.
Future<void> showCommandPalette(BuildContext context, WidgetRef ref) async {
  final reference = ref.read(commandReferenceProvider).value;
  final entries = <_PaletteEntry>[
    for (final destination in JockyDestination.values)
      _PaletteEntry(
        label: destination.label,
        group: 'Navigate',
        detail: destination.description,
        icon: destination.icon,
        onSelect: () => context.go(destination.path),
      ),
    if (reference != null)
      for (final command in reference.$1.entries)
        _PaletteEntry(
          label: command.example,
          group: 'Load command',
          detail: '${command.name} — ${command.syntax}',
          icon: Icons.terminal_outlined,
          onSelect: () {
            ref.read(commandDraftProvider.notifier).set(command.example);
            context.go(JockyDestination.commandCenter.path);
          },
        ),
  ];

  await showDialog<void>(
    context: context,
    barrierColor: const Color(0xAA05070A),
    builder: (context) => _PaletteDialog(entries: entries),
  );
}

class _PaletteDialog extends StatefulWidget {
  const _PaletteDialog({required this.entries});

  final List<_PaletteEntry> entries;

  @override
  State<_PaletteDialog> createState() => _PaletteDialogState();
}

class _PaletteDialogState extends State<_PaletteDialog> {
  final _controller = TextEditingController();
  final _focus = FocusNode();
  int _highlighted = 0;

  @override
  void dispose() {
    _controller.dispose();
    _focus.dispose();
    super.dispose();
  }

  List<_PaletteEntry> get _filtered {
    final query = _controller.text.trim().toLowerCase();
    if (query.isEmpty) return widget.entries;
    return widget.entries
        .where((e) =>
            e.label.toLowerCase().contains(query) ||
            e.detail.toLowerCase().contains(query) ||
            e.group.toLowerCase().contains(query))
        .toList(growable: false);
  }

  void _select(List<_PaletteEntry> entries) {
    if (entries.isEmpty) return;
    final entry = entries[_highlighted.clamp(0, entries.length - 1)];
    Navigator.of(context).pop();
    entry.onSelect();
  }

  @override
  Widget build(BuildContext context) {
    final entries = _filtered;

    return Dialog(
      alignment: Alignment.topCenter,
      insetPadding: const EdgeInsets.only(top: 90, left: 24, right: 24),
      backgroundColor: JockyColors.surfaceRaised,
      shape: RoundedRectangleBorder(
        side: const BorderSide(color: JockyColors.borderStrong),
        borderRadius: BorderRadius.circular(JockyRadius.lg),
      ),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 620, maxHeight: 440),
        child: Shortcuts(
          shortcuts: const {
            SingleActivator(LogicalKeyboardKey.arrowDown): _MoveIntent(1),
            SingleActivator(LogicalKeyboardKey.arrowUp): _MoveIntent(-1),
          },
          child: Actions(
            actions: {
              _MoveIntent: CallbackAction<_MoveIntent>(
                onInvoke: (intent) {
                  setState(() {
                    final count = entries.length;
                    if (count == 0) return;
                    _highlighted = (_highlighted + intent.delta) % count;
                    if (_highlighted < 0) _highlighted += count;
                  });
                  return null;
                },
              ),
            },
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Padding(
                  padding: const EdgeInsets.all(JockySpace.md),
                  child: TextField(
                    controller: _controller,
                    focusNode: _focus,
                    autofocus: true,
                    onChanged: (_) => setState(() => _highlighted = 0),
                    onSubmitted: (_) => _select(entries),
                    decoration: const InputDecoration(
                      hintText: 'Jump to a section, or load a command example…',
                      prefixIcon: Icon(Icons.search, size: 16, color: JockyColors.textFaint),
                    ),
                  ),
                ),
                const Divider(height: 1),
                Flexible(
                  child: entries.isEmpty
                      ? const Padding(
                          padding: EdgeInsets.all(JockySpace.xl),
                          child: Text(
                            'Nothing matches that.',
                            style: TextStyle(color: JockyColors.textFaint, fontSize: 12),
                          ),
                        )
                      : ListView.builder(
                          shrinkWrap: true,
                          itemCount: entries.length,
                          itemBuilder: (context, index) {
                            final entry = entries[index];
                            final highlighted = index == _highlighted;
                            return InkWell(
                              onTap: () {
                                setState(() => _highlighted = index);
                                _select(entries);
                              },
                              child: Container(
                                color:
                                    highlighted ? JockyColors.accentWash : Colors.transparent,
                                padding: const EdgeInsets.symmetric(
                                  horizontal: JockySpace.lg,
                                  vertical: JockySpace.sm,
                                ),
                                child: Row(
                                  children: [
                                    Icon(entry.icon,
                                        size: 14,
                                        color: highlighted
                                            ? JockyColors.accent
                                            : JockyColors.textFaint),
                                    const SizedBox(width: JockySpace.md),
                                    Expanded(
                                      child: Column(
                                        crossAxisAlignment: CrossAxisAlignment.start,
                                        children: [
                                          Text(
                                            entry.label,
                                            maxLines: 1,
                                            overflow: TextOverflow.ellipsis,
                                            style: TextStyle(
                                              fontSize: 12.5,
                                              fontFamily: entry.group == 'Load command'
                                                  ? JockyType.mono
                                                  : null,
                                              color: JockyColors.text,
                                            ),
                                          ),
                                          Text(
                                            entry.detail,
                                            maxLines: 1,
                                            overflow: TextOverflow.ellipsis,
                                            style: const TextStyle(
                                              fontSize: 10.5,
                                              color: JockyColors.textFaint,
                                            ),
                                          ),
                                        ],
                                      ),
                                    ),
                                    const SizedBox(width: JockySpace.md),
                                    Text(
                                      entry.group,
                                      style: const TextStyle(
                                        fontSize: 9.5,
                                        letterSpacing: 0.6,
                                        color: JockyColors.textFaint,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            );
                          },
                        ),
                ),
                const Divider(height: 1),
                const Padding(
                  padding: EdgeInsets.symmetric(
                      horizontal: JockySpace.lg, vertical: JockySpace.sm),
                  child: SizedBox(
                    width: double.infinity,
                    child: Text(
                      'Selecting a command loads it into the editor. It is not executed.',
                      style: TextStyle(fontSize: 10.5, color: JockyColors.textFaint),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _MoveIntent extends Intent {
  const _MoveIntent(this.delta);

  final int delta;
}
