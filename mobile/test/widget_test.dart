import 'package:flutter_test/flutter_test.dart';
import 'package:air_model_engine/main.dart';

void main() {
  testWidgets('AIR mobile approval gate renders before dashboard access', (tester) async {
    await tester.pumpWidget(const AirModelEngineApp());

    // The gate starts an asynchronous secure-storage session restore and shows
    // an indeterminate progress indicator while it runs. pumpAndSettle() can
    // never settle while that indicator is active, so verify the stable gate
    // content on the first frame instead.
    expect(find.text('ANALYTICAL INVESTMENT RESEARCH'), findsOneWidget);
    expect(find.text('Your market intelligence workspace.'), findsOneWidget);
    expect(find.text('International mobile number'), findsOneWidget);
    expect(find.text('NO OTP  •  NO WHATSAPP  •  NO PASSWORD'), findsOneWidget);
  });
}
