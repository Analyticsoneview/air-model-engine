import 'package:flutter_test/flutter_test.dart';
import 'package:air_model_engine/main.dart';

void main() {
  testWidgets('AIR phone onboarding gate renders before dashboard access', (tester) async {
    await tester.pumpWidget(const AirModelEngineApp(initialServerUrl: 'http://127.0.0.1:8000'));

    // The gate initially restores the saved customer session. Wait for that
    // asynchronous step so the test checks the actionable first-use state.
    await tester.pumpAndSettle();

    expect(find.text('ANALYTICAL INVESTMENT RESEARCH'), findsOneWidget);
    expect(find.text('Your market intelligence workspace.'), findsOneWidget);
    expect(find.text('International mobile number'), findsOneWidget);
    expect(find.text('REQUEST ACCESS'), findsOneWidget);
    expect(find.text('DASHBOARD ACCESS  •  SUBSCRIPTION-BASED STRATEGIES'), findsOneWidget);
    // Administrator authentication is deliberately not part of the customer gate.
    expect(find.text('ADMINISTRATOR SIGN IN'), findsNothing);
    expect(find.textContaining('Verify ownership before enabling payments'), findsOneWidget);
  });
}
