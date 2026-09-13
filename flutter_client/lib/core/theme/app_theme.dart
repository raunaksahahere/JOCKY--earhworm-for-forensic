import 'package:flutter/material.dart';

import 'tokens.dart';

/// Builds the workstation theme. [textScale] is applied by the caller via
/// MediaQuery, not here; this only defines colour and type structure.
ThemeData buildJockyTheme() {
  const scheme = ColorScheme.dark(
    primary: JockyColors.accent,
    onPrimary: Color(0xFF06211F),
    secondary: JockyColors.accentDim,
    onSecondary: JockyColors.text,
    surface: JockyColors.surface,
    onSurface: JockyColors.text,
    error: JockyColors.danger,
    onError: Color(0xFF2A0A09),
    outline: JockyColors.border,
    outlineVariant: JockyColors.borderStrong,
  );

  final base = ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    colorScheme: scheme,
    scaffoldBackgroundColor: JockyColors.canvas,
    canvasColor: JockyColors.canvas,
    dividerColor: JockyColors.border,
    splashFactory: NoSplash.splashFactory,
    visualDensity: VisualDensity.compact,
  );

  return base.copyWith(
    textTheme: base.textTheme
        .apply(bodyColor: JockyColors.text, displayColor: JockyColors.text)
        .copyWith(
          titleLarge: const TextStyle(
            fontSize: 19,
            fontWeight: FontWeight.w600,
            letterSpacing: -0.2,
            color: JockyColors.text,
          ),
          titleMedium: const TextStyle(
            fontSize: 14.5,
            fontWeight: FontWeight.w600,
            color: JockyColors.text,
          ),
          titleSmall: const TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.w700,
            letterSpacing: 0.9,
            color: JockyColors.textMuted,
          ),
          bodyMedium: const TextStyle(fontSize: 13, height: 1.45, color: JockyColors.text),
          bodySmall: const TextStyle(fontSize: 12, height: 1.4, color: JockyColors.textMuted),
          labelSmall: const TextStyle(fontSize: 11, color: JockyColors.textFaint),
        ),
    dividerTheme: const DividerThemeData(
      color: JockyColors.border,
      thickness: 1,
      space: 1,
    ),
    tooltipTheme: TooltipThemeData(
      waitDuration: const Duration(milliseconds: 500),
      decoration: BoxDecoration(
        color: JockyColors.surfaceOverlay,
        border: Border.all(color: JockyColors.borderStrong),
        borderRadius: BorderRadius.circular(JockyRadius.sm),
      ),
      textStyle: const TextStyle(fontSize: 12, color: JockyColors.text),
    ),
    scrollbarTheme: ScrollbarThemeData(
      thickness: const WidgetStatePropertyAll(9),
      thumbColor: WidgetStateProperty.resolveWith(
        (states) => states.contains(WidgetState.hovered)
            ? JockyColors.borderStrong
            : JockyColors.border,
      ),
      radius: const Radius.circular(4),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: JockyColors.surfaceRaised,
      isDense: true,
      contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
      hintStyle: const TextStyle(color: JockyColors.textFaint, fontSize: 13),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(JockyRadius.md),
        borderSide: const BorderSide(color: JockyColors.border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(JockyRadius.md),
        borderSide: const BorderSide(color: JockyColors.border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(JockyRadius.md),
        borderSide: const BorderSide(color: JockyColors.accent, width: 1.4),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: JockyColors.accentDim,
        foregroundColor: JockyColors.text,
        disabledBackgroundColor: JockyColors.surfaceOverlay,
        disabledForegroundColor: JockyColors.textFaint,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        textStyle: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(JockyRadius.md)),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: JockyColors.text,
        side: const BorderSide(color: JockyColors.borderStrong),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
        textStyle: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(JockyRadius.md)),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: JockyColors.accent,
        textStyle: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w500),
      ),
    ),
  );
}
