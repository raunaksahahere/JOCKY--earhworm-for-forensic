import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// Workstation-wide keyboard intents.
class ExecuteCommandIntent extends Intent {
  const ExecuteCommandIntent();
}

class OpenPaletteIntent extends Intent {
  const OpenPaletteIntent();
}

class SelectEvidenceIntent extends Intent {
  const SelectEvidenceIntent();
}

class FocusSearchIntent extends Intent {
  const FocusSearchIntent();
}

class GoToDestinationIntent extends Intent {
  const GoToDestinationIntent(this.index);

  final int index;
}

/// Ctrl on Windows/Linux; the meta variants are registered too so the bindings
/// behave for anyone running the client on a Mac keyboard layout.
Map<ShortcutActivator, Intent> globalShortcuts() => {
      const SingleActivator(LogicalKeyboardKey.enter, control: true):
          const ExecuteCommandIntent(),
      const SingleActivator(LogicalKeyboardKey.enter, meta: true):
          const ExecuteCommandIntent(),
      const SingleActivator(LogicalKeyboardKey.keyK, control: true):
          const OpenPaletteIntent(),
      const SingleActivator(LogicalKeyboardKey.keyK, meta: true): const OpenPaletteIntent(),
      const SingleActivator(LogicalKeyboardKey.keyO, control: true):
          const SelectEvidenceIntent(),
      const SingleActivator(LogicalKeyboardKey.keyO, meta: true):
          const SelectEvidenceIntent(),
      const SingleActivator(LogicalKeyboardKey.keyF, control: true):
          const FocusSearchIntent(),
      const SingleActivator(LogicalKeyboardKey.keyF, meta: true): const FocusSearchIntent(),
      for (var i = 1; i <= 8; i++)
        SingleActivator(_digit(i), control: true): GoToDestinationIntent(i - 1),
    };

LogicalKeyboardKey _digit(int value) => switch (value) {
      1 => LogicalKeyboardKey.digit1,
      2 => LogicalKeyboardKey.digit2,
      3 => LogicalKeyboardKey.digit3,
      4 => LogicalKeyboardKey.digit4,
      5 => LogicalKeyboardKey.digit5,
      6 => LogicalKeyboardKey.digit6,
      7 => LogicalKeyboardKey.digit7,
      _ => LogicalKeyboardKey.digit8,
    };

/// Renders a shortcut as a keycap sequence, e.g. Ctrl + ↵.
class KeyHint extends StatelessWidget {
  const KeyHint(this.keys, {super.key, this.muted = true});

  final List<String> keys;
  final bool muted;

  @override
  Widget build(BuildContext context) {
    final color = muted ? const Color(0xFF64727F) : const Color(0xFF94A3B3);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (final key in keys) ...[
          Container(
            margin: const EdgeInsets.only(left: 3),
            padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
            decoration: BoxDecoration(
              border: Border.all(color: const Color(0xFF33404C)),
              borderRadius: BorderRadius.circular(3),
            ),
            child: Text(
              key,
              style: TextStyle(fontSize: 9.5, fontWeight: FontWeight.w600, color: color),
            ),
          ),
        ],
      ],
    );
  }
}
