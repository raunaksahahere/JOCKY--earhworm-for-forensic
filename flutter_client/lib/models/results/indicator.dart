import '../../core/utils/json.dart';

/// A neutral triage label produced by `analysis/indicators.py`.
/// These are heuristics for analyst attention, never a verdict.
enum IndicatorLevel { info, warning, critical, unknown }

IndicatorLevel indicatorLevelFrom(String? raw) => switch (raw) {
      'info' => IndicatorLevel.info,
      'warning' => IndicatorLevel.warning,
      'critical' => IndicatorLevel.critical,
      _ => IndicatorLevel.unknown,
    };

class Indicator {
  const Indicator({
    required this.level,
    required this.label,
    required this.detail,
    required this.rawLevel,
  });

  final IndicatorLevel level;
  final String label;
  final String detail;
  final String rawLevel;

  factory Indicator.fromJson(Map<String, dynamic> json) => Indicator(
        level: indicatorLevelFrom(asStringOrNull(json['level'])),
        label: asString(json['label'], fallback: 'Indicator'),
        detail: asString(json['detail']),
        rawLevel: asString(json['level'], fallback: 'unknown'),
      );

  static List<Indicator> listFrom(Object? value) =>
      asMapList(value).map(Indicator.fromJson).toList(growable: false);
}
