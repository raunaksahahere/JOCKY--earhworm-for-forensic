import 'package:flutter/material.dart';

import '../core/theme/tokens.dart';

enum StatusTone { ok, warn, danger, info, neutral, accent }

Color statusColor(StatusTone tone) => switch (tone) {
      StatusTone.ok => JockyColors.ok,
      StatusTone.warn => JockyColors.warn,
      StatusTone.danger => JockyColors.danger,
      StatusTone.info => JockyColors.info,
      StatusTone.neutral => JockyColors.neutral,
      StatusTone.accent => JockyColors.accent,
    };

Color statusWash(StatusTone tone) => switch (tone) {
      StatusTone.ok => JockyColors.okWash,
      StatusTone.warn => JockyColors.warnWash,
      StatusTone.danger => JockyColors.dangerWash,
      StatusTone.info => JockyColors.infoWash,
      StatusTone.neutral => const Color(0x147C8A99),
      StatusTone.accent => JockyColors.accentWash,
    };

IconData statusIcon(StatusTone tone) => switch (tone) {
      StatusTone.ok => Icons.check_circle_outline,
      StatusTone.warn => Icons.warning_amber_outlined,
      StatusTone.danger => Icons.error_outline,
      StatusTone.info => Icons.info_outline,
      StatusTone.neutral => Icons.remove_circle_outline,
      StatusTone.accent => Icons.bolt_outlined,
    };

/// Status is always carried by an icon *and* a label, never by colour alone.
class StatusChip extends StatelessWidget {
  const StatusChip({
    super.key,
    required this.label,
    required this.tone,
    this.icon,
    this.tooltip,
    this.dense = false,
  });

  final String label;
  final StatusTone tone;
  final IconData? icon;
  final String? tooltip;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final color = statusColor(tone);
    final chip = Container(
      padding: EdgeInsets.symmetric(horizontal: dense ? 6 : 8, vertical: dense ? 2 : 4),
      decoration: BoxDecoration(
        color: statusWash(tone),
        border: Border.all(color: color.withValues(alpha: 0.45)),
        borderRadius: BorderRadius.circular(JockyRadius.sm),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon ?? statusIcon(tone), size: dense ? 11 : 13, color: color),
          const SizedBox(width: 5),
          // Chips appear in fixed-width table cells; the label ellipsizes there
          // rather than clipping, and the full text stays in the tooltip.
          Flexible(
            child: Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: dense ? 10.5 : 11.5,
                fontWeight: FontWeight.w600,
                color: color,
                letterSpacing: 0.2,
              ),
            ),
          ),
        ],
      ),
    );
    return tooltip == null ? chip : Tooltip(message: tooltip!, child: chip);
  }
}
