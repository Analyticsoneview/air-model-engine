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

  testWidgets('Admin console renders lifecycle summary and daily conversion report', (tester) async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(storage, (call) async => null);
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
      } else if (path == '/api/v1/admin/customers') {
        data = {'customers': [{
          'customer_id': '+919876543210',
          'first_registered_at': '2026-11-15T09:00:00+05:30',
          'first_approved_at': '2026-11-15T09:10:00+05:30',
          'first_rejected_at': null,
          'first_plan_availed_at': '2026-11-15T09:20:00+05:30',
          'customer_type': 'NEW', 'device_count': 2,
          'access_status': 'APPROVED', 'subscription_status': 'ACTIVE',
          'plan_code': 'MONTHLY',
          'subscription_expires_at': '2026-12-15T09:20:00+05:30',
        }], 'summary': {
          'new_customers': 7, 'existing_customers': 12,
          'pending_approvals': 3, 'no_plan_availed': 4,
        }};
      } else if (path.endsWith('/customer-reports/daily')) {
        data = {'daily': [{
          'date': '2026-11-15', 'new_registrations': 7,
          'existing_customer_requests': 2, 'approved': 5, 'rejected': 1,
          'pending': 3, 'first_time_plans_availed': 4,
          'approved_but_no_plan_availed': 2,
          'registration_cohort_approved': 5, 'registration_cohort_plan_availed': 4,
          'registration_to_approval_pct': 71.43, 'registration_to_plan_pct': 57.14,
          'approval_to_plan_pct': 80.0,
        }]};
      } else if (path == '/api/v1/admin/marketing/customers') {
        data = {'segment_counts': {}};
      } else if (path.endsWith('/marketing/offers')) {
        data = {'offers': []};
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
    await tester.ensureVisible(find.text('CUSTOMERS'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('CUSTOMERS'));
    await tester.pumpAndSettle();
    final verticalScroll = find.byWidgetPredicate(
      (widget) => widget is Scrollable && widget.axisDirection == AxisDirection.down,
    ).first;

    expect(find.text('NEW CUSTOMERS'), findsOneWidget);
    expect(find.text('7'), findsOneWidget);
    expect(find.text('EXISTING CUSTOMERS'), findsOneWidget);
    expect(find.text('12'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('INDEPENDENT LIFECYCLE DATE FILTERS'), 300, scrollable: verticalScroll);
    await tester.pumpAndSettle();
    await tester.tap(find.text('INDEPENDENT LIFECYCLE DATE FILTERS'));
    await tester.pumpAndSettle();
    expect(find.text('First registered date'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('DAILY CONVERSION REPORT'), 300, scrollable: verticalScroll);
    await tester.pumpAndSettle();
    await tester.tap(find.text('DAILY CONVERSION REPORT'));
    await tester.pumpAndSettle();
    expect(find.text('RUN REPORT'), findsOneWidget);
    expect(find.textContaining('1 customer(s) displayed'), findsOneWidget);
    await tester.scrollUntilVisible(find.textContaining('••••210'), 300, scrollable: verticalScroll);
    await tester.pumpAndSettle();
    await tester.tap(find.textContaining('••••210'));
    await tester.pumpAndSettle();
    expect(find.textContaining('First registered: 2026-11-15T09:00:00+05:30'), findsOneWidget);
    expect(find.textContaining('First approved: 2026-11-15T09:10:00+05:30'), findsOneWidget);
    expect(find.textContaining('First plan availed: 2026-11-15T09:20:00+05:30'), findsOneWidget);

    expect(find.text('2026-11-15'), findsAtLeastNWidgets(1));
    expect(find.textContaining('New: 7 · Existing requests: 2'), findsOneWidget);
    expect(find.textContaining('First plans: 4 · Approved, no plan: 2'), findsOneWidget);
    client.close();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(storage, null);
  });
}
