import 'package:flutter/material.dart';

import '../../core/theme/tokens.dart';

/// Presentation-only syntax colouring.
///
/// This highlighter is **not** a validator. The Lark grammar in the Python
/// backend is the only authority on whether a command is well formed; this
/// controller never blocks input, never marks text as an error, and never
/// gates the execute button.
class CommandHighlightController extends TextEditingController {
  CommandHighlightController({super.text});

  /// Keyword shapes the backend's grammar uses. Colouring one of these does not
  /// assert that the command parses.
  static const _keywords = {
    'HASH', 'ENCRYPT', 'SYSTEM', 'INFO', 'PROCESSES', 'LIST', 'SEARCH', 'FILE',
    'FILES', 'IN',
  };

  @override
  TextSpan buildTextSpan({
    required BuildContext context,
    TextStyle? style,
    required bool withComposing,
  }) {
    final base = style ?? const TextStyle();
    final spans = <TextSpan>[];
    final buffer = StringBuffer();
    var index = 0;

    void flush() {
      if (buffer.isEmpty) return;
      final word = buffer.toString();
      spans.add(TextSpan(
        text: word,
        style: _keywords.contains(word)
            ? base.copyWith(color: JockyColors.accent, fontWeight: FontWeight.w700)
            : base.copyWith(color: JockyColors.text),
      ));
      buffer.clear();
    }

    while (index < text.length) {
      final char = text[index];
      if (char == '"' || char == "'") {
        flush();
        final close = text.indexOf(char, index + 1);
        final end = close == -1 ? text.length : close + 1;
        spans.add(TextSpan(
          text: text.substring(index, end),
          style: base.copyWith(color: JockyColors.warn),
        ));
        index = end;
        continue;
      }
      if (char == ' ' || char == '\t') {
        flush();
        spans.add(TextSpan(text: char, style: base));
        index++;
        continue;
      }
      buffer.write(char);
      index++;
    }
    flush();

    return TextSpan(style: base, children: spans);
  }
}
