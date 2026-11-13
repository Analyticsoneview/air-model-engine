import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:air_model_engine/screens/air_server_setup_screen.dart';
import 'package:air_model_engine/services/air_api_client.dart';

void main() {
  setUp(() => AirApiClient.clearRuntimeBaseUrl());

  test('browser localhost is a valid configured server address', () {
    AirApiClient.configureBaseUrl('http://localhost:8000/');
    expect(AirApiClient.configuredBaseUrl, 'http://localhost:8000');
  });

  test('existing API clients use the updated LAN server address', () {
    final api = AirApiClient();
    AirApiClient.configureBaseUrl('http://192.168.1.20:8000/');
    expect(api.baseUrl, 'http://192.168.1.20:8000');
    api.dispose();
  });

  testWidgets('server setup explains LAN address and rejects invalid URL', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: AirServerSetupScreen(onConnected: _noop),
    ));

    expect(find.text('Connect to your AIR server'), findsOneWidget);
    expect(find.text('Local development'), findsOneWidget);
    expect(find.text('AWS production'), findsOneWidget);
    expect(find.textContaining('localhost refers to the phone'), findsOneWidget);

    // Invoke the real button callback directly. The connection form is intentionally
    // scrollable, so hit-testing its off-screen button makes this test viewport-dependent.
    final button = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, 'TEST CONNECTION & CONTINUE'),
    );
    await tester.enterText(find.byType(TextField), 'not-a-server-address');
    button.onPressed!();
    await tester.pump();

    expect(
      find.text('Enter a valid AIR server URL, including http:// or https://.'),
      findsOneWidget,
    );

    await tester.enterText(find.byType(TextField), 'http://127.0.0.1:8000');
    final updatedButton = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, 'TEST CONNECTION & CONTINUE'),
    );
    updatedButton.onPressed!();
    await tester.pump();

    expect(
      find.text('On a phone, use your Windows PC LAN IP or a public HTTPS domain. Localhost points to the phone.'),
      findsOneWidget,
    );
  });
}

void _noop() {}
