import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:air_model_engine/services/air_api_client.dart';

void main() {
  group('AirApiClient', () {
    test('login stores bearer token and fetches broker catalog', () async {
      final requests = <http.Request>[];
      final client = AirApiClient(
        baseUrl: 'https://air.example',
        client: MockClient((request) async {
          requests.add(request);
          if (request.url.path.endsWith('/auth/login')) {
            return http.Response(jsonEncode({'access_token': 'jwt-token'}), 200);
          }
          return http.Response(jsonEncode({
            'brokers': [
              {'code': 'dhan', 'name': 'DhanHQ'}
            ]
          }), 200);
        }),
      );

      await client.login('user@example.com', 'password123');
      final catalog = await client.brokerCatalog();

      expect(client.isAuthenticated, isTrue);
      expect(catalog.single['code'], 'dhan');
      expect(requests[1].headers['Authorization'], 'Bearer jwt-token');
      client.dispose();
    });

    test('unauthorized response is surfaced and logout clears session', () async {
      final client = AirApiClient(
        baseUrl: 'https://air.example',
        client: MockClient((request) async => http.Response(
          jsonEncode({'detail': 'Invalid email or password'}),
          401,
        )),
      );
      await expectLater(
        client.login('user@example.com', 'bad'),
        throwsA(isA<AirApiException>()),
      );
      expect(client.isAuthenticated, isFalse);
      client.logout();
      expect(client.isAuthenticated, isFalse);
      client.dispose();
    });
  });
}
