import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:air_model_engine/screens/air_admin_console_screen.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const storage = MethodChannel('plugins.it_nomads.com/flutter_secure_storage');

  testWidgets('Admin console loads support queue and updates ticket status', (tester) async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(storage, (call) async => null);
    final updates = <http.Request>[];
    final client = MockClient((request) async {
      final path = request.url.path;
      Map<String, dynamic> data = {};
      if (path.endsWith('/auth/login')) {
        data = {'access_token': 'local-test-session'};
      } else if (path.endsWith('/auth/me')) {
        data = {'role': 'ADMIN', 'must_change_password': false};
      } else if (path.endsWith('/access-requests')) {
        data = {'requests': []};
      } else if (path.endsWith('/access-decisions')) {
        data = {'decisions': []};
      } else if (path.endsWith('/marketing/customers')) {
        data = {'segment_counts': {}};
      } else if (path.endsWith('/marketing/offers')) {
        data = {'offers': []};
      } else if (path.endsWith('/customer-reports/daily')) {
        data = {'daily': []};
      } else if (path.endsWith('/admin/customers')) {
        data = {'customers': [], 'summary': {}};
      } else if (path.contains('/admin/support/tickets') && request.method == 'GET') {
        data = {'tickets': [{
          'ticket_id': 'ticket-123', 'customer_id': '+919876543210',
          'subject': 'Broker connection failed', 'category': 'BROKER',
          'status': 'OPEN', 'priority': 'NORMAL', 'updated_at': '2026-11-16T09:00:00Z',
          'events': [{'event_type':'TICKET_CREATED','actor_type':'CUSTOMER',
            'message':'My broker connection is not working.','created_at':'2026-11-16T08:00:00Z'}],
        }]};
      } else if (path.contains('/admin/support/tickets') && request.method == 'PUT') {
        updates.add(request);
        data = {'ticket': {}};
      }
      return http.Response(jsonEncode(data), 200);
    });

    await tester.pumpWidget(MaterialApp(home: AirAdminConsoleScreen(httpClient: client)));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Administrator email'), 'admin@example.test');
    await tester.enterText(find.widgetWithText(TextField, 'Password'), 'local-only');
    await tester.enterText(find.widgetWithText(TextField, 'Authenticator code'), '111111');
    await tester.tap(find.text('SIGN IN'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('SUPPORT'));
    await tester.tap(find.text('SUPPORT'));
    await tester.pumpAndSettle();
    expect(find.text('CUSTOMER SUPPORT QUEUE'), findsOneWidget);
    expect(find.text('Broker connection failed'), findsOneWidget);
    await tester.tap(find.byType(DropdownButton<String>).last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('IN PROGRESS').last);
    await tester.pumpAndSettle();
    expect(updates, hasLength(1));
    expect(jsonDecode(updates.single.body)['status'], 'IN_PROGRESS');

    client.close();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(storage, null);
  });
}
