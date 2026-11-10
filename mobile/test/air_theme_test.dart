import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:air_model_engine/theme/air_theme.dart';

void main() {
  group('AIR theme system', () {
    test('dark theme uses the premium navy and gold palette', () {
      final theme = AirTheme.build(AirLook.dark);

      expect(theme.brightness, Brightness.dark);
      expect(theme.scaffoldBackgroundColor, AirPalette.navy);
      expect(theme.cardColor, AirPalette.navySurface);
      expect(theme.colorScheme.primary, AirPalette.gold);
    });

    test('light theme uses the clean light palette', () {
      final theme = AirTheme.build(AirLook.light);

      expect(theme.brightness, Brightness.light);
      expect(theme.scaffoldBackgroundColor, AirPalette.lightBackground);
      expect(theme.cardColor, Colors.white);
      expect(theme.colorScheme.primary, AirPalette.goldLight);
    });

    test('both themes retain the same semantic trading colours', () {
      for (final look in AirLook.values) {
        final theme = AirTheme.build(look);
        expect(theme.colorScheme.error, AirPalette.negative);
      }
      expect(AirPalette.positive, const Color(0xFF16A37B));
      expect(AirPalette.warning, const Color(0xFFE7A83E));
    });
  });
}
