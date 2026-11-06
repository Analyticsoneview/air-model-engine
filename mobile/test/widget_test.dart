import 'package:flutter_test/flutter_test.dart';
import 'package:air_model_engine/main.dart';

void main() {
  testWidgets('AIR Model Engine dashboard renders', (tester) async {
    await tester.pumpWidget(const AirModelEngineApp());
    expect(find.text('AIR MODEL ENGINE'), findsOneWidget);
    expect(find.text('MARKET PULSE'), findsOneWidget);
  });
}
