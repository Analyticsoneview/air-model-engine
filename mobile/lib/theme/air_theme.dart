import 'package:flutter/material.dart';

enum AirLook { dark, light }

/// AIR's shared premium design tokens and Material 3 theme factory.
abstract final class AirPalette {
  static const navy = Color(0xFF101827);
  static const navySurface = Color(0xFF182438);
  static const navyElevated = Color(0xFF202E42);
  static const gold = Color(0xFFD6AA52);
  static const goldLight = Color(0xFFA97B25);
  static const positive = Color(0xFF16A37B);
  static const negative = Color(0xFFE05252);
  static const warning = Color(0xFFE7A83E);
  static const darkText = Color(0xFFF5F7FA);
  static const darkMuted = Color(0xFFAAB6C8);
  static const lightBackground = Color(0xFFF4F6FA);
  static const lightText = Color(0xFF172235);
  static const lightMuted = Color(0xFF66758A);
  static const lightBorder = Color(0xFFDFE5ED);
}

abstract final class AirSpacing {
  static const double xxs = 4;
  static const double xs = 8;
  static const double sm = 12;
  static const double md = 16;
  static const double lg = 24;
  static const double xl = 32;
}

abstract final class AirRadii {
  static const double card = 16;
  static const double control = 12;
  static const double pill = 999;
}

abstract final class AirTheme {
  static ThemeData build(AirLook look) {
    final isLight = look == AirLook.light;
    final background = isLight ? AirPalette.lightBackground : AirPalette.navy;
    final surface = isLight ? Colors.white : AirPalette.navySurface;
    final elevated = isLight ? const Color(0xFFEDF1F6) : AirPalette.navyElevated;
    final foreground = isLight ? AirPalette.lightText : AirPalette.darkText;
    final muted = isLight ? AirPalette.lightMuted : AirPalette.darkMuted;
    final accent = isLight ? AirPalette.goldLight : AirPalette.gold;
    final baseScheme = ColorScheme.fromSeed(
      seedColor: accent,
      brightness: isLight ? Brightness.light : Brightness.dark,
    );
    final scheme = baseScheme.copyWith(
      primary: accent,
      onPrimary: isLight ? Colors.white : AirPalette.navy,
      secondary: muted,
      onSecondary: foreground,
      surface: surface,
      onSurface: foreground,
      error: AirPalette.negative,
      outline: isLight ? AirPalette.lightBorder : const Color(0xFF344258),
    );

    return ThemeData(
      useMaterial3: true,
      brightness: isLight ? Brightness.light : Brightness.dark,
      colorScheme: scheme,
      scaffoldBackgroundColor: background,
      canvasColor: background,
      cardColor: surface,
      dividerColor: isLight ? AirPalette.lightBorder : const Color(0xFF344258),
      fontFamily: 'Roboto',
      visualDensity: VisualDensity.standard,
      appBarTheme: AppBarTheme(
        backgroundColor: background,
        foregroundColor: foreground,
        elevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          color: foreground,
          fontSize: 18,
          fontWeight: FontWeight.w700,
          letterSpacing: .1,
        ),
      ),
      cardTheme: CardTheme(
        color: surface,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AirRadii.card),
          side: BorderSide(
            color: isLight ? AirPalette.lightBorder : const Color(0xFF344258),
          ),
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: surface,
        indicatorColor: accent.withValues(alpha: .16),
        labelTextStyle: WidgetStateProperty.resolveWith(
          (states) => TextStyle(
            fontSize: 11,
            fontWeight: states.contains(WidgetState.selected)
                ? FontWeight.w700
                : FontWeight.w500,
            color: states.contains(WidgetState.selected) ? accent : muted,
          ),
        ),
      ),
      navigationRailTheme: NavigationRailThemeData(
        backgroundColor: surface,
        indicatorColor: accent.withValues(alpha: .16),
        selectedIconTheme: IconThemeData(color: accent),
        unselectedIconTheme: IconThemeData(color: muted),
        selectedLabelTextStyle: TextStyle(
          color: accent,
          fontWeight: FontWeight.w700,
          fontSize: 12,
        ),
        unselectedLabelTextStyle: TextStyle(color: muted, fontSize: 12),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: elevated,
        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AirRadii.control),
          borderSide: BorderSide(color: scheme.outline),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AirRadii.control),
          borderSide: BorderSide(color: scheme.outline),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AirRadii.control),
          borderSide: BorderSide(color: accent, width: 1.5),
        ),
        hintStyle: TextStyle(color: muted),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size(44, 48),
          backgroundColor: accent,
          foregroundColor: isLight ? Colors.white : AirPalette.navy,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AirRadii.control),
          ),
          textStyle: const TextStyle(fontWeight: FontWeight.w700),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size(44, 48),
          foregroundColor: foreground,
          side: BorderSide(color: scheme.outline),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AirRadii.control),
          ),
        ),
      ),
      textTheme: Typography.material2021(
        platform: TargetPlatform.android,
        colorScheme: scheme,
      ).black.apply(
        bodyColor: foreground,
        displayColor: foreground,
        fontFamily: 'Roboto',
      ),
    );
  }
}
