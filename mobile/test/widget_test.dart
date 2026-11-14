import 'package:flutter_test/flutter_test.dart';
import 'package:air_model_engine/main.dart';

void main() {
  testWidgets('AIR phone onboarding gate renders before dashboard access', (tester) async {
    await tester.pumpWidget(const AirModelEngineApp(initialServerUrl: 'http://127.0.0.1:8000'));

    // This widget test deliberately verifies the first rendered state only.
    // Flutter's test binding intercepts HTTP and does not provide a real
    // secure-storage session, so asynchronous restoration is not a valid
    // prerequisite for asserting the initial onboarding screen.

    expect(find.text('ANALYTICAL INVESTMENT RESEARCH'), findsOneWidget);
    expect(find.text('Your market intelligence workspace.'), findsOneWidget);
    expect(find.text('International mobile number'), findsOneWidget);
    // Until session restoration completes, the request button is correctly
    // replaced by the loading indicator.
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(find.text('DASHBOARD ACCESS  •  SUBSCRIPTION-BASED STRATEGIES'), findsOneWidget);
    // Administrator authentication is deliberately not part of the customer gate.
    expect(find.text('ADMINISTRATOR SIGN IN'), findsNothing);
    expect(find.textContaining('Verify ownership before enabling payments'), findsOneWidget);
  });
}
