import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:air_model_engine/screens/air_server_setup_screen.dart';
import 'package:air_model_engine/services/air_api_client.dart';

void main() {
  setUp(() => AirApiClient.clearRuntimeBaseUrl());

  testWidgets('server setup explains LAN address and rejects invalid URL', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: AirServerSetupScreen(onConnected: _noop),
    ));

    expect(find.text('CONNECT TO YOUR AIR SERVER'), findsOneWidget);
    expect(find.textContaining('localhost or 127.0.0.1'), findsOneWidget);

    await tester.enterText(find.byType(TextField), 'not-a-server-address');
    await tester.tap(find.text('TEST AND SAVE SERVER'));
    await tester.pump();

    expect(
      find.text('Enter a valid http:// or https:// AIR server address.'),
      findsOneWidget,
    );
  });
}

void _noop() {}
