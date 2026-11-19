import 'package:flutter_test/flutter_test.dart';
import 'package:air_model_engine/main.dart';

void main() {
  testWidgets('AIR User opens the guest dashboard without phone onboarding', (tester) async {
    await tester.pumpWidget(
      const AirModelEngineApp(initialServerUrl: 'http://127.0.0.1:8000'),
    );

    // A configured server should open the application shell directly.
    expect(find.text('Home'), findsOneWidget);
    expect(find.text('Intelligence'), findsOneWidget);
    expect(find.text('Markets'), findsOneWidget);
    expect(find.text('AIR QOC'), findsOneWidget);
    expect(find.text('More'), findsOneWidget);

    // Guest browsing must not be blocked by the retired OTP/onboarding gate.
    expect(find.text('International mobile number'), findsNothing);
    expect(find.text('DASHBOARD ACCESS  •  SUBSCRIPTION-BASED STRATEGIES'), findsNothing);
    expect(find.text('ADMINISTRATOR SIGN IN'), findsNothing);
  });
}
