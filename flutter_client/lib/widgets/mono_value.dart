import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/theme/tokens.dart';
import '../core/utils/format.dart';

/// Machine-generated values — digests, paths, commands, PIDs — are always
/// monospaced, selectable and copyable. Analysts compare these by character.
class MonoValue extends StatelessWidget {
  const MonoValue(
    this.value, {
    super.key,
    this.maxLines = 1,
    this.fontSize = 12,
    this.color = JockyColors.text,
    this.elide,
    this.copyable = false,
    this.semanticsLabel,
  });

  final String? value;
  final int maxLines;
  final double fontSize;
  final Color color;

  /// When set, the middle of the value is elided for display while the full
  /// value stays in the tooltip and on the clipboard.
  final int? elide;
  final bool copyable;
  final String? semanticsLabel;

  @override
  Widget build(BuildContext context) {
    final raw = value;
    if (raw == null || raw.isEmpty) {
      return const Text(
        unavailableMarker,
        style: TextStyle(color: JockyColors.textFaint, fontSize: 12),
        semanticsLabel: 'not available',
      );
    }

    final display = elide == null ? raw : elideMiddle(raw, max: elide!);
    final text = SelectableText(
      display,
      maxLines: maxLines,
      style: TextStyle(
        fontFamily: JockyType.mono,
        fontSize: fontSize,
        height: 1.4,
        color: color,
      ),
      semanticsLabel: semanticsLabel ?? raw,
    );

    final body = display == raw ? text : Tooltip(message: raw, child: text);
    if (!copyable) return body;

    return Row(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Flexible(child: body),
        const SizedBox(width: 4),
        CopyButton(value: raw),
      ],
    );
  }
}

class CopyButton extends StatefulWidget {
  const CopyButton({super.key, required this.value, this.label});

  final String value;
  final String? label;

  @override
  State<CopyButton> createState() => _CopyButtonState();
}

class _CopyButtonState extends State<CopyButton> {
  bool _copied = false;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: _copied ? 'Copied' : 'Copy ${widget.label ?? 'value'}',
      child: IconButton(
        onPressed: () async {
          await Clipboard.setData(ClipboardData(text: widget.value));
          if (!mounted) return;
          setState(() => _copied = true);
          await Future<void>.delayed(const Duration(milliseconds: 1200));
          if (mounted) setState(() => _copied = false);
        },
        icon: Icon(
          _copied ? Icons.check : Icons.copy_all_outlined,
          size: 13,
          color: _copied ? JockyColors.ok : JockyColors.textFaint,
        ),
        style: IconButton.styleFrom(
          minimumSize: const Size(24, 24),
          padding: EdgeInsets.zero,
          tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        ),
        constraints: const BoxConstraints(minWidth: 24, minHeight: 24),
        splashRadius: 12,
      ),
    );
  }
}

/// Label/value row used throughout detail panes.
class DataField extends StatelessWidget {
  const DataField({
    super.key,
    required this.label,
    this.value,
    this.child,
    this.mono = true,
    this.labelWidth = 150,
    this.copyable = false,
  });

  final String label;
  final String? value;
  final Widget? child;
  final bool mono;
  final double labelWidth;
  final bool copyable;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: JockySpace.sm),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: labelWidth,
            child: Padding(
              padding: const EdgeInsets.only(top: 1),
              child: Text(
                label,
                style: const TextStyle(
                  fontSize: 11.5,
                  color: JockyColors.textMuted,
                  height: 1.5,
                ),
              ),
            ),
          ),
          const SizedBox(width: JockySpace.md),
          Expanded(
            child: child ??
                (mono
                    ? MonoValue(value, copyable: copyable, maxLines: 4)
                    : Text(
                        value == null || value!.isEmpty ? unavailableMarker : value!,
                        style: TextStyle(
                          fontSize: 12.5,
                          height: 1.45,
                          color: value == null || value!.isEmpty
                              ? JockyColors.textFaint
                              : JockyColors.text,
                        ),
                      )),
          ),
        ],
      ),
    );
  }
}
