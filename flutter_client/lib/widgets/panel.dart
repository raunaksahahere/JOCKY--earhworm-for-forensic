import 'package:flutter/material.dart';

import '../core/theme/tokens.dart';

/// The primary structural container. Panels are bordered regions with a dense
/// header, not floating cards — the workstation reads as one surface.
class Panel extends StatelessWidget {
  const Panel({
    super.key,
    required this.child,
    this.title,
    this.subtitle,
    this.actions = const [],
    this.leading,
    this.padding = const EdgeInsets.all(JockySpace.lg),
    this.scrollable = false,
  });

  final Widget child;
  final String? title;
  final String? subtitle;
  final List<Widget> actions;
  final Widget? leading;
  final EdgeInsets padding;
  final bool scrollable;

  @override
  Widget build(BuildContext context) {
    final body = Padding(padding: padding, child: child);

    // A panel is used both inside a bounded region (an Expanded row cell, a
    // sized detail pane) and inside a scrolling column. The body may only take
    // a flex slot in the first case; giving it one under an unbounded height
    // would force an infinite constraint.
    return LayoutBuilder(
      builder: (context, constraints) {
        final header = title == null
            ? null
            : PanelHeader(
                title: title!,
                subtitle: subtitle,
                actions: actions,
                leading: leading,
              );
        final content = scrollable && constraints.hasBoundedHeight
            ? SingleChildScrollView(child: body)
            : body;

        return DecoratedBox(
          decoration: BoxDecoration(
            color: JockyColors.surface,
            border: Border.all(color: JockyColors.border),
            borderRadius: BorderRadius.circular(JockyRadius.lg),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            mainAxisSize: MainAxisSize.min,
            children: [
              ?header,
              if (constraints.hasBoundedHeight)
                Flexible(child: content)
              else
                content,
            ],
          ),
        );
      },
    );
  }
}

class PanelHeader extends StatelessWidget {
  const PanelHeader({
    super.key,
    required this.title,
    this.subtitle,
    this.actions = const [],
    this.leading,
  });

  final String title;
  final String? subtitle;
  final List<Widget> actions;
  final Widget? leading;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(JockySpace.lg, JockySpace.md, JockySpace.md, JockySpace.md),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: JockyColors.border)),
      ),
      child: Row(
        children: [
          if (leading != null) ...[leading!, const SizedBox(width: JockySpace.sm)],
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(title, style: Theme.of(context).textTheme.titleMedium),
                if (subtitle != null) ...[
                  const SizedBox(height: 2),
                  Text(subtitle!, style: Theme.of(context).textTheme.bodySmall),
                ],
              ],
            ),
          ),
          ...actions,
        ],
      ),
    );
  }
}

/// A small uppercase label that groups fields inside a panel.
class SectionLabel extends StatelessWidget {
  const SectionLabel(this.text, {super.key, this.trailing});

  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: JockySpace.sm),
      child: Row(
        children: [
          Text(text.toUpperCase(), style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(width: JockySpace.sm),
          const Expanded(child: Divider(color: JockyColors.border)),
          if (trailing != null) ...[const SizedBox(width: JockySpace.sm), trailing!],
        ],
      ),
    );
  }
}
