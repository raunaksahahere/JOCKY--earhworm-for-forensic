import 'package:flutter/material.dart';

import '../core/errors/failure.dart';
import '../core/theme/tokens.dart';
import 'mono_value.dart';
import 'status_chip.dart';

StatusTone toneForFailure(FailureKind kind) => switch (kind) {
      FailureKind.commandSyntax || FailureKind.commandValidation => StatusTone.warn,
      FailureKind.cancelled => StatusTone.neutral,
      FailureKind.unsupportedCapability => StatusTone.info,
      _ => StatusTone.danger,
    };

/// Full failure presentation: what failed, the engine's own words, the error
/// code, and what to do next. Never a generic message.
class FailureView extends StatelessWidget {
  const FailureView({super.key, required this.failure, this.onRetry, this.compact = false});

  final JockyFailure failure;
  final VoidCallback? onRetry;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final tone = toneForFailure(failure.kind);
    final color = statusColor(tone);

    return Container(
      padding: const EdgeInsets.all(JockySpace.md),
      decoration: BoxDecoration(
        color: statusWash(tone),
        border: Border.all(color: color.withValues(alpha: 0.4)),
        borderRadius: BorderRadius.circular(JockyRadius.md),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(statusIcon(tone), size: 15, color: color),
              const SizedBox(width: JockySpace.sm),
              Expanded(
                child: Text(
                  failure.headline,
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: color),
                ),
              ),
              if (failure.code != null)
                StatusChip(label: failure.code!, tone: tone, dense: true, icon: Icons.tag),
              if (onRetry != null) ...[
                const SizedBox(width: JockySpace.sm),
                TextButton.icon(
                  onPressed: onRetry,
                  icon: const Icon(Icons.refresh, size: 14),
                  label: const Text('Retry'),
                ),
              ],
            ],
          ),
          const SizedBox(height: JockySpace.sm),
          // The engine's own message, verbatim.
          SelectableText(
            failure.message,
            style: const TextStyle(fontSize: 12.5, height: 1.5, color: JockyColors.text),
          ),
          if (!compact) ...[
            const SizedBox(height: JockySpace.sm),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(Icons.arrow_right_alt, size: 14, color: JockyColors.textMuted),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    failure.remediation,
                    style: const TextStyle(
                      fontSize: 11.5,
                      height: 1.5,
                      color: JockyColors.textMuted,
                    ),
                  ),
                ),
              ],
            ),
            if (failure.detail != null) ...[
              const SizedBox(height: JockySpace.sm),
              MonoValue(
                failure.detail,
                fontSize: 10.5,
                color: JockyColors.textFaint,
                maxLines: 3,
              ),
            ],
          ],
        ],
      ),
    );
  }
}

/// Collector warnings from a result. These do not mean failure — they mean the
/// observation is partial — so they are presented distinctly from errors.
class WarningList extends StatelessWidget {
  const WarningList({super.key, required this.warnings, this.title = 'Collector warnings'});

  final List<String> warnings;
  final String title;

  @override
  Widget build(BuildContext context) {
    if (warnings.isEmpty) return const SizedBox.shrink();
    return Container(
      padding: const EdgeInsets.all(JockySpace.md),
      decoration: BoxDecoration(
        color: JockyColors.warnWash,
        border: Border.all(color: JockyColors.warn.withValues(alpha: 0.35)),
        borderRadius: BorderRadius.circular(JockyRadius.md),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.warning_amber_outlined, size: 14, color: JockyColors.warn),
              const SizedBox(width: 6),
              Text(
                '$title (${warnings.length})',
                style: const TextStyle(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w600,
                  color: JockyColors.warn,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          for (final warning in warnings)
            Padding(
              padding: const EdgeInsets.only(bottom: 3, left: 20),
              child: Text(
                '• $warning',
                style: const TextStyle(fontSize: 12, height: 1.45, color: JockyColors.text),
              ),
            ),
        ],
      ),
    );
  }
}

/// Shown where the UI has a place for a capability the backend does not expose.
/// The boundary stays visible instead of being faked or hidden.
class CapabilityGap extends StatelessWidget {
  const CapabilityGap({super.key, required this.capability, required this.explanation});

  final String capability;
  final String explanation;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(JockySpace.md),
      decoration: BoxDecoration(
        color: JockyColors.surfaceRaised,
        border: Border.all(color: JockyColors.border),
        borderRadius: BorderRadius.circular(JockyRadius.md),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.link_off, size: 14, color: JockyColors.info),
          const SizedBox(width: JockySpace.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  capability,
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: JockyColors.text,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  explanation,
                  style: const TextStyle(
                    fontSize: 11.5,
                    height: 1.5,
                    color: JockyColors.textMuted,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
