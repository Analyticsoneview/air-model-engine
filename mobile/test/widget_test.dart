import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:air_model_engine/main.dart';

void main() {
  testWidgets('AIR User keeps the access gate and offers a bounded guest preview', (tester) async {
    await tester.pumpWidget(
      const AirModelEngineApp(initialServerUrl: 'http://127.0.0.1:8000'),
    );

    // The customer access gate must remain the root boundary while session
    // restoration is pending; the full application shell is not public.
    expect(find.text('ANALYTICAL INVESTMENT RESEARCH'), findsOneWidget);
    expect(find.text('International mobile number'), findsOneWidget);
    expect(find.text('Home'), findsNothing);
    expect(find.text('Markets'), findsNothing);
    expect(find.text('AIR QOC'), findsNothing);

    // Guest preview is an explicit entry point, not automatic shell access.
    expect(find.text('EXPLORE PUBLISHED STRATEGY PREVIEW'), findsOneWidget);
    expect(find.text('ADMINISTRATOR SIGN IN'), findsNothing);
  });
}
