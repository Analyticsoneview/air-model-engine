import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:air_model_engine/screens/air_workflow_studio_screen.dart';

void main() {
  testWidgets('Workflow Studio loads workflows and execution history', (tester) async {
    final requests = <http.Request>[];
    final client = MockClient((request) async {
      requests.add(request);
      if (request.url.path.endsWith('/workflows')) {
        return http.Response(jsonEncode({
          'workflows': [{
            'workflow_id': 'workflow-1',
            'name': 'Morning QOC',
            'trigger_type': 'TIME',
            'version': 2,
            'execution_mode': 'RESEARCH_ONLY',
            'enabled': true,
          }]
        }), 200);
      }
      if (request.url.path.endsWith('/runs')) {
        return http.Response(jsonEncode({
          'runs': [{
            'run_id': 'run-1',
            'status': 'SUCCEEDED',
            'execution_mode': 'RESEARCH_ONLY',
            'started_at': '2026-11-16T09:18:00+05:30',
          }]
        }), 200);
      }
      return http.Response('{}', 200);
    });

    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AirWorkflowStudioScreen(
          apiBase: 'http://air.test',
          accessToken: 'test-token',
          httpClient: client,
        ),
      ),
    ));
    await tester.pumpAndSettle();

    expect(find.text('AIR WORKFLOW STUDIO'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('Morning QOC'), 350,
        scrollable: find.byType(Scrollable).first);
    expect(find.text('Morning QOC'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('EXECUTION HISTORY'), 350,
        scrollable: find.byType(Scrollable).first);
    expect(find.text('EXECUTION HISTORY'), findsOneWidget);
    expect(find.textContaining('SUCCEEDED'), findsOneWidget);
    expect(requests, hasLength(3));
    expect(requests.every((request) =>
        request.headers['Authorization'] == 'Bearer test-token'), isTrue);
  });
  testWidgets('Workflow Studio creates a customer-scoped QOC time/event workflow', (tester) async {
    tester.view.physicalSize = const Size(1000, 1800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final created = <Map<String, dynamic>>[];
    final client = MockClient((request) async {
      if (request.method == 'POST' && request.url.path == '/api/v1/admin/workflows') {
        created.add(Map<String, dynamic>.from(jsonDecode(request.body) as Map));
        return http.Response(jsonEncode({
          'workflow_id': 'workflow-new',
          'name': 'Morning QOC',
          'version': 1,
          'enabled': false,
        }), 201);
      }
      if (request.url.path.endsWith('/workflows/runs')) {
        return http.Response(jsonEncode({'runs': []}), 200);
      }
      return http.Response(jsonEncode({'workflows': []}), 200);
    });

    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AirWorkflowStudioScreen(
          apiBase: 'http://air.test',
          accessToken: 'test-token',
          httpClient: client,
        ),
      ),
    ));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).at(0), 'Morning QOC');
    await tester.enterText(find.byType(TextField).at(2), 'customer-123');
    await tester.enterText(find.byType(TextField).at(3), 'broker-account-1');
    await tester.tap(find.text('CREATE WORKFLOW'));
    await tester.pumpAndSettle();

    expect(created, hasLength(1));
    expect(created.single['trigger_type'], 'EVENT');
    expect(created.single['trigger_config']['customer_id'], 'customer-123');
    expect(created.single['workflow_spec']['steps'][0]['action'], 'qoc.qualify');
    expect(created.single['workflow_spec']['steps'][0]['params']['account_id'], 'broker-account-1');
    expect(created.single['execution_mode'], 'RESEARCH_ONLY');
  });


  testWidgets('Workflow Studio exposes per-workflow append-only audit history', (tester) async {
    final client = MockClient((request) async {
      if (request.url.path.endsWith('/workflows/audit')) {
        return http.Response(jsonEncode({'audit': [{
          'action': 'CREATED',
          'actor_id': 'admin-1',
          'workflow_version': 1,
          'created_at': '2026-11-16T09:18:00Z',
          'payload': {'name': 'Morning QOC'},
        }]}), 200);
      }
      if (request.url.path.endsWith('/workflows')) {
        return http.Response(jsonEncode({'workflows': [{
          'workflow_id': 'workflow-1', 'name': 'Morning QOC',
          'trigger_type': 'TIME', 'version': 1,
          'execution_mode': 'RESEARCH_ONLY', 'enabled': false,
        }]}), 200);
      }
      if (request.url.path.endsWith('/runs')) {
        return http.Response(jsonEncode({'runs': []}), 200);
      }
      return http.Response(jsonEncode({'sessions': []}), 200);
    });
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: AirWorkflowStudioScreen(
        apiBase: 'http://air.test', accessToken: 'test-token', httpClient: client,
      )),
    ));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Morning QOC'), 350,
        scrollable: find.byType(Scrollable).first);
    final popup = find.byType(PopupMenuButton<String>);
    expect(popup, findsOneWidget);
    await tester.ensureVisible(popup);
    await tester.pumpAndSettle();
    await tester.tap(popup);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Audit history'));
    await tester.pumpAndSettle();
    expect(find.text('APPEND-ONLY WORKFLOW AUDIT'), findsOneWidget);
    expect(find.text('CREATED · admin-1'), findsOneWidget);
  });


  testWidgets('Workflow Studio preserves the selected strategy trigger', (tester) async {
    final created = <Map<String, dynamic>>[];
    final client = MockClient((request) async {
      if (request.method == 'POST' && request.url.path == '/api/v1/admin/workflows') {
        created.add(Map<String, dynamic>.from(jsonDecode(request.body) as Map));
        return http.Response(jsonEncode({'workflow_id': 'strategy-workflow', 'version': 1}), 201);
      }
      if (request.url.path.endsWith('/runs')) {
        return http.Response(jsonEncode({'runs': []}), 200);
      }
      if (request.url.path.endsWith('/calendar')) {
        return http.Response(jsonEncode({'sessions': []}), 200);
      }
      return http.Response(jsonEncode({'workflows': []}), 200);
    });
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: AirWorkflowStudioScreen(
        apiBase: 'http://air.test', accessToken: 'test-token', httpClient: client,
      )),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.byType(DropdownButtonFormField<String>).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Strategy based').last);
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).at(2), 'ORB_MORNING');
    await tester.enterText(find.byType(TextField).at(3), 'customer-123');
    final createButton = find.text('CREATE WORKFLOW');
    await tester.ensureVisible(createButton);
    await tester.pumpAndSettle();
    await tester.tap(createButton);
    await tester.pumpAndSettle();
    expect(created, hasLength(1));
    expect(created.single['trigger_type'], 'STRATEGY');
    expect(created.single['trigger_config']['strategy'], 'ORB_MORNING');
  });

}
