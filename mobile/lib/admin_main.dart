import 'package:flutter/material.dart';

import 'screens/air_admin_console_screen.dart';
import 'theme/air_theme.dart';

/// Dedicated AIR administrator application entry point for trusted staff builds.
void main() => runApp(const AirAdminApp());

class AirAdminApp extends StatelessWidget {
  const AirAdminApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'AIR | Administrator Console',
    debugShowCheckedModeBanner: false,
    theme: AirTheme.build(AirLook.dark),
    home: const AirAdminConsoleScreen(),
  );
}
