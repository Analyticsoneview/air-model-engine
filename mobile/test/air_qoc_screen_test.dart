import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:air_model_engine/screens/air_qoc_screen.dart';

void main() {
  testWidgets('AIR QOC starts with a read-only connection and no fabricated signals',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(home: AirQocScreen()));

    expect(find.text('AIR QOC · OPTIONS DATA'), findsOneWidget);
    expect(find.text('READ-ONLY DATA CONNECTION'), findsOneWidget);
    expect(find.text('SIGN IN TO AIR'), findsNothing);
    expect(find.textContaining('Sign in to AIR using your approved mobile-number session'), findsOneWidget);
    expect(find.textContaining('Do not enter your AIR credentials again here.'), findsOneWidget);
    expect(find.text('RUN AIR QOC QUALIFICATION'), findsNothing);
  });
}
