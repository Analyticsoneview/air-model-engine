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
    expect(find.text('Morning QOC'), findsOneWidget);
    expect(find.text('EXECUTION HISTORY'), findsOneWidget);
    expect(find.textContaining('SUCCEEDED'), findsOneWidget);
    expect(requests, hasLength(2));
    expect(requests.every((request) =>
        request.headers['Authorization'] == 'Bearer test-token'), isTrue);
  });
}
