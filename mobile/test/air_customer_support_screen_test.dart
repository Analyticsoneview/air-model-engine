import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:air_model_engine/screens/air_support_screen.dart';
import 'package:air_model_engine/services/air_api_client.dart';

void main() {
  testWidgets('Customer can create a support ticket and see it in their ticket list', (tester) async {
    AirApiClient.setAccessToken('customer-test-token');
    var created = false;
    final client = MockClient((request) async {
      if (request.method == 'POST' && request.url.path.endsWith('/customer/support/tickets')) {
        created = true;
        return http.Response(jsonEncode({'ticket': {
          'ticket_id': 'ticket-abc', 'customer_id': '+919876543210',
          'subject': 'Cannot connect broker', 'category': 'BROKER',
          'status': 'OPEN', 'events': [],
        }}), 201);
      }
      if (request.method == 'GET' && request.url.path.endsWith('/customer/support/tickets')) {
        return http.Response(jsonEncode({'tickets': created ? [{
          'ticket_id': 'ticket-abc', 'subject': 'Cannot connect broker',
          'category': 'BROKER', 'status': 'OPEN', 'events': [],
        }] : []}), 200);
      }
      return http.Response('{}', 404);
    });
    await tester.pumpWidget(MaterialApp(home: AirSupportScreen(apiClient: AirApiClient(client: client))));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Subject'), 'Cannot connect broker');
    await tester.enterText(find.widgetWithText(TextField, 'Describe the issue'),
        'My broker connection is failing when I open the account page.');
    await tester.tap(find.text('SUBMIT TICKET'));
    await tester.pumpAndSettle();
    expect(created, isTrue);
    expect(find.text('Cannot connect broker'), findsOneWidget);
    expect(find.textContaining('ticket-abc'), findsOneWidget);
    client.close();
    AirApiClient.setAccessToken(null);
  });
}
