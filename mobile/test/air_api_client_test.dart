import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:air_model_engine/services/air_api_client.dart';

void main() {
  group('AirApiClient mobile approval', () {
    setUp(() => AirApiClient.setAccessToken(null));

    test('pending request does not authenticate the customer', () async {
      final client = AirApiClient(
        baseUrl: 'https://air.example',
        client: MockClient((request) async => http.Response(
          jsonEncode({'status': 'PENDING', 'message': 'Awaiting approval'}),
          200,
        )),
      );

      final result = await client.mobileLogin('+14155550123', 'device-identifier-0001');

      expect(result['status'], 'PENDING');
      expect(client.isAuthenticated, isFalse);
      client.dispose();
    });

    test('approved request stores token and sends it to protected endpoints', () async {
      final requests = <http.Request>[];
      final client = AirApiClient(
        baseUrl: 'https://air.example',
        client: MockClient((request) async {
          requests.add(request);
          if (request.url.path.endsWith('/auth/mobile-login')) {
            return http.Response(jsonEncode({
              'status': 'APPROVED',
              'access_token': 'approved-device-token',
            }), 200);
          }
          return http.Response(jsonEncode({'customer_id': 'request-1', 'status': 'APPROVED'}), 200);
        }),
      );

      await client.mobileLogin('+447700900123', 'device-identifier-0002');
      await client.me();

      expect(client.isAuthenticated, isTrue);
      expect(requests.last.headers['Authorization'], 'Bearer approved-device-token');
      client.dispose();
    });

    test('customer market-data access uses the authenticated customer endpoint', () async {
      final client = AirApiClient(
        baseUrl: 'https://air.example',
        client: MockClient((request) async {
          expect(request.url.path, '/api/v1/customer/market-data/access');
          expect(request.headers['Authorization'], 'Bearer market-token');
          return http.Response(jsonEncode({
            'effective_source': 'NSE',
            'connection_status': 'not_requested',
            'market_data_source': {'connection_message': 'NSE EOD default'},
          }), 200);
        }),
      );
      AirApiClient.setAccessToken('market-token');

      final result = await client.customerMarketDataAccess();

      expect(result['effective_source'], 'NSE');
      expect((result['market_data_source'] as Map)['connection_message'], 'NSE EOD default');
      client.dispose();
      AirApiClient.setAccessToken(null);
    });

    test('market intelligence pulse calls the authenticated customer endpoint', () async {
      final client = AirApiClient(
        baseUrl: 'https://air.example',
        client: MockClient((request) async {
          expect(request.url.path, '/api/v1/customer/market-intelligence/pulse');
          expect(request.headers['Authorization'], 'Bearer pulse-token');
          return http.Response(jsonEncode({
            'data_type': 'EOD',
            'breadth': {'status': 'available', 'advances': 12, 'declines': 8},
          }), 200);
        }),
      );
      AirApiClient.setAccessToken('pulse-token');

      final result = await client.marketIntelligencePulse();

      expect(result['data_type'], 'EOD');
      expect((result['breadth'] as Map)['advances'], 12);
      client.dispose();
      AirApiClient.setAccessToken(null);
    });

    test('AIR QOC qualification sends mode and account filters with auth', () async {
      final client = AirApiClient(
        baseUrl: 'https://air.example',
        client: MockClient((request) async {
          expect(request.url.path, '/api/v1/air-qoc/dhan/qualification/account-42');
          expect(request.url.queryParameters['mode'], 'POSITIONAL');
          expect(request.url.queryParameters['underlying_scrip'], '13');
          expect(request.url.queryParameters['expiry'], '2026-11-26');
          expect(request.headers['Authorization'], 'Bearer qoc-token');
          return http.Response(jsonEncode({
            'mode': 'POSITIONAL',
            'counts': {'QUALIFIED': 1},
            'signals': [{'classification': 'QUALIFIED', 'score': 84}],
          }), 200);
        }),
      );
      AirApiClient.setAccessToken('qoc-token');

      final result = await client.dhanQocQualification(
        'account-42', mode: 'POSITIONAL', underlyingScrip: '13', expiry: '2026-11-26');

      expect(result['mode'], 'POSITIONAL');
      expect((result['signals'] as List).single['score'], 84);
      client.dispose();
      AirApiClient.setAccessToken(null);
    });

    test('status check does not require a token', () async {
      final client = AirApiClient(
        baseUrl: 'https://air.example',
        client: MockClient((request) async {
          expect(request.url.queryParameters['mobile_e164'], '+919876543210');
          expect(request.url.queryParameters['device_id'], 'device-identifier-0003');
          return http.Response(jsonEncode({'status': 'PENDING'}), 200);
        }),
      );

      final result = await client.mobileStatus('+919876543210', 'device-identifier-0003');
      expect(result['status'], 'PENDING');
      expect(client.isAuthenticated, isFalse);
      client.dispose();
    });
  });
}
