import 'package:flutter_test/flutter_test.dart';
import 'package:air_model_engine/main.dart';

void main() {
  testWidgets('AIR mobile approval gate renders before dashboard access', (tester) async {
    await tester.pumpWidget(const AirModelEngineApp());
    await tester.pumpAndSettle();

    expect(find.text('ANALYTICAL INVESTMENT RESEARCH'), findsOneWidget);
    expect(find.text('Your market intelligence workspace.'), findsOneWidget);
    expect(find.text('International mobile number'), findsOneWidget);
    expect(find.text('REQUEST AIR ACCESS'), findsOneWidget);
    expect(find.text('NO OTP  •  NO WHATSAPP  •  NO PASSWORD'), findsOneWidget);
  });
}
