import 'dart:convert';

import 'package:http/http.dart' as http;

class AirApiException implements Exception {
  const AirApiException(this.message);
  final String message;
  @override
  String toString() => message;
}

class AirApiClient {
  AirApiClient({http.Client? client, String? baseUrl})
      : _client = client ?? http.Client(),
        baseUrl = (baseUrl ??
                const String.fromEnvironment(
                  'AIR_API_BASE_URL',
                  defaultValue: 'http://127.0.0.1:8000',
                ))
            .replaceFirst(RegExp(r'/+$'), '');

  final http.Client _client;
  final String baseUrl;
  String? _accessToken;

  bool get isAuthenticated => _accessToken != null;
  void logout() => _accessToken = null;

  Map<String, String> get _headers => {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        if (_accessToken != null) 'Authorization': 'Bearer $_accessToken',
      };

  Future<Map<String, dynamic>> login(String email, String password) async {
    final response = await _client.post(
      Uri.parse('$baseUrl/api/v1/auth/login'),
      headers: _headers,
      body: jsonEncode({'email': email.trim(), 'password': password}),
    );
    final data = _decode(response);
    final token = data['access_token'];
    if (token is! String || token.isEmpty) {
      throw const AirApiException('The AIR server did not return an access token.');
    }
    _accessToken = token;
    return data;
  }

  Future<List<Map<String, dynamic>>> brokerCatalog() async {
    final response = await _client.get(
      Uri.parse('$baseUrl/api/v1/brokers/catalog'),
      headers: _headers,
    );
    final data = _decode(response);
    return (data['brokers'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .toList(growable: false);
  }

  Future<List<Map<String, dynamic>>> accounts() async {
    final response = await _client.get(
      Uri.parse('$baseUrl/api/v1/customer/accounts'),
      headers: _headers,
    );
    final data = _decode(response);
    return (data['accounts'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .toList(growable: false);
  }

  Future<Map<String, dynamic>> addAccount(String broker, String accountId) async {
    final response = await _client.post(
      Uri.parse('$baseUrl/api/v1/customer/accounts'),
      headers: _headers,
      body: jsonEncode({'broker': broker, 'account_id': accountId.trim()}),
    );
    return _decode(response);
  }


  Future<Map<String, dynamic>> saveCredentials(
      String broker, String accountId, Map<String, String> credentials) async {
    final response = await _client.put(
      Uri.parse('$baseUrl/api/v1/customer/accounts/$broker/$accountId/credentials'),
      headers: _headers,
      body: jsonEncode({'credentials': credentials}),
    );
    return _decode(response);
  }

  Map<String, dynamic> _decode(http.Response response) {
    Map<String, dynamic> body;
    try {
      body = jsonDecode(response.body) as Map<String, dynamic>;
    } catch (_) {
      throw AirApiException('AIR server returned an invalid response (${response.statusCode}).');
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw AirApiException(
        body['detail']?.toString() ?? 'AIR server request failed (${response.statusCode}).',
      );
    }
    return body;
  }

  void dispose() => _client.close();
}
