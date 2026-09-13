import 'package:flutter/material.dart';

import '../../models/results/indicator.dart';
import '../status_chip.dart';

StatusTone toneForIndicator(IndicatorLevel level) => switch (level) {
      IndicatorLevel.info => StatusTone.info,
      IndicatorLevel.warning => StatusTone.warn,
      IndicatorLevel.critical => StatusTone.danger,
      IndicatorLevel.unknown => StatusTone.neutral,
    };

/// Triage labels from the backend heuristics. Rendered as neutral attention
/// markers — never as a malware verdict, which the backend does not make.
class IndicatorBadges extends StatelessWidget {
  const IndicatorBadges({super.key, required this.indicators, this.dense = true});

  final List<Indicator> indicators;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    if (indicators.isEmpty) return const SizedBox.shrink();
    return Wrap(
      spacing: 5,
      runSpacing: 4,
      children: [
        for (final indicator in indicators)
          StatusChip(
            label: indicator.label,
            tone: toneForIndicator(indicator.level),
            dense: dense,
            tooltip: '${indicator.detail}\n\nHeuristic label for analyst attention; '
                'not a verdict.',
          ),
      ],
    );
  }
}

/// Compact form for table cells: a count with the highest level's tone.
class IndicatorSummary extends StatelessWidget {
  const IndicatorSummary({super.key, required this.indicators});

  final List<Indicator> indicators;

  @override
  Widget build(BuildContext context) {
    if (indicators.isEmpty) {
      return const Text('—', style: TextStyle(color: Color(0xFF64727F), fontSize: 12));
    }
    final highest = indicators
        .map((i) => i.level)
        .reduce((a, b) => a.index > b.index && b != IndicatorLevel.unknown ? a : b);
    return Tooltip(
      message: indicators.map((i) => '${i.label}: ${i.detail}').join('\n'),
      child: StatusChip(
        label: indicators.length == 1 ? indicators.first.label : '${indicators.length} flags',
        tone: toneForIndicator(highest),
        dense: true,
      ),
    );
  }
}
