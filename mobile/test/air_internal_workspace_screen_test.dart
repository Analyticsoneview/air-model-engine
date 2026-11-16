import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:air_model_engine/screens/air_internal_workspace_screen.dart';

void main() {
  testWidgets('internal workspace loads policy and displays distribution warning', (tester) async {
    final client = MockClient((request) async {
      expect(request.headers['authorization'], 'Bearer private-admin-token');
      if (request.url.path.endsWith('/policy')) {
        return http.Response(jsonEncode({
          'access': 'OWNER_ONLY',
          'external_distribution': 'DISABLED_PENDING_COMPLIANCE_APPROVAL',
        }), 200);
      }
      if (request.url.path.endsWith('/watchlists') || request.url.path.endsWith('/notes')) {
        return http.Response(jsonEncode({'items': []}), 200);
      }
      return http.Response('{}', 404);
    });

    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: SizedBox(
          height: 700,
          child: AirInternalWorkspaceScreen(
            apiBase: 'https://api.example.test',
            accessToken: 'private-admin-token',
            httpClient: client,
          ),
        ),
      ),
    ));
    await tester.pumpAndSettle();

    expect(find.text('INTERNAL — NOT FOR DISTRIBUTION'), findsOneWidget);
    expect(find.text('No private records yet. Add a watchlist or research note.'), findsOneWidget);
    expect(find.text('NEW WATCHLIST'), findsOneWidget);
  });
}
