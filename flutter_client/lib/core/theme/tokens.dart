import 'package:flutter/widgets.dart';

/// Design tokens for the JOCKY forensic workstation.
///
/// Dark-first, restrained cyan accent. Status colours are always paired with
/// a glyph or label in the UI so meaning never depends on colour alone.
abstract final class JockyColors {
  // Structural surfaces, darkest to lightest.
  static const canvas = Color(0xFF0A0D10);
  static const sidebar = Color(0xFF0F1317);
  static const surface = Color(0xFF12171C);
  static const surfaceRaised = Color(0xFF181E25);
  static const surfaceOverlay = Color(0xFF1D242C);

  static const border = Color(0xFF232B34);
  static const borderStrong = Color(0xFF33404C);

  // Text.
  static const text = Color(0xFFE3EAF2);
  static const textMuted = Color(0xFF94A3B3);
  static const textFaint = Color(0xFF64727F);

  // Accent — used sparingly: active nav, focus, primary action.
  static const accent = Color(0xFF3DD6D0);
  static const accentDim = Color(0xFF1E8F8A);
  static const accentWash = Color(0x1A3DD6D0);

  // Status.
  static const ok = Color(0xFF56C568);
  static const warn = Color(0xFFE0A33A);
  static const danger = Color(0xFFF0625C);
  static const info = Color(0xFF5CA8FF);
  static const neutral = Color(0xFF7C8A99);

  static const okWash = Color(0x1A56C568);
  static const warnWash = Color(0x1AE0A33A);
  static const dangerWash = Color(0x1AF0625C);
  static const infoWash = Color(0x1A5CA8FF);
}

abstract final class JockySpace {
  static const xs = 4.0;
  static const sm = 8.0;
  static const md = 12.0;
  static const lg = 16.0;
  static const xl = 24.0;
  static const xxl = 32.0;
}

abstract final class JockyRadius {
  static const sm = 4.0;
  static const md = 6.0;
  static const lg = 10.0;
}

abstract final class JockyType {
  /// Monospace is used for every machine-generated value: paths, digests,
  /// commands, PIDs. Analysts compare these character by character.
  static const mono = 'monospace';
}
