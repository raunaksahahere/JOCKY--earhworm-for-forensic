import 'package:flutter/material.dart';

import '../core/theme/tokens.dart';

/// Empty states explain *why* there is nothing here and what to do next.
/// A blank panel in a forensic tool is indistinguishable from a failure.
class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    required this.icon,
    required this.title,
    required this.description,
    this.action,
    this.compact = false,
  });

  final IconData icon;
  final String title;
  final String description;
  final Widget? action;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: EdgeInsets.all(compact ? JockySpace.lg : JockySpace.xxl),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 380),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: compact ? 22 : 30, color: JockyColors.textFaint),
              SizedBox(height: compact ? JockySpace.sm : JockySpace.md),
              Text(
                title,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 13.5,
                  fontWeight: FontWeight.w600,
                  color: JockyColors.textMuted,
                ),
              ),
              const SizedBox(height: JockySpace.xs),
              Text(
                description,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 12,
                  height: 1.5,
                  color: JockyColors.textFaint,
                ),
              ),
              if (action != null) ...[const SizedBox(height: JockySpace.lg), action!],
            ],
          ),
        ),
      ),
    );
  }
}
