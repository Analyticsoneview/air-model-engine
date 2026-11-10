import 'dart:convert';

import 'package:http/http.dart' as http;

class AirApiException implements Exception {
  const AirApiException(this.message);
  final String message;
  @override
  String toString() => message;
}

class AirApiClient {
  static const _configuredBaseUrl = String.fromEnvironment('AIR_API_BASE_URL');

  static String _normalizeBaseUrl(String value) {
    var normalized = value;
    while (normalized.endsWith('/')) {
      normalized = normalized.substring(0, normalized.length - 1);
    }
    return normalized;
  }

  AirApiClient({http.Client? client, String? baseUrl})
      : _client = client ?? http.Client(),
        baseUrl = _normalizeBaseUrl(
          baseUrl ??
              (_configuredBaseUrl.isEmpty
                  ? 'http://127.0.0.1:8000'
                  : _configuredBaseUrl),
        );

  final http.Client _client;
  final String baseUrl;
  static String? _sharedAccessToken;
  String? get _accessToken => _sharedAccessToken;

  static void setAccessToken(String? token) => _sharedAccessToken = token;

  bool get isAuthenticated => _accessToken != null;
  void logout() => _sharedAccessToken = null;

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
    _sharedAccessToken = token;
    return data;
  }

  Future<Map<String, dynamic>> mobileLogin(String mobileE164, String deviceId) async {
    final response = await _client.post(
      Uri.parse('$baseUrl/api/v1/auth/mobile-login'),
      headers: _headers,
      body: jsonEncode({'mobile_e164': mobileE164.trim(), 'device_id': deviceId}),
    );
    final data = _decode(response);
    final token = data['access_token'];
    if (data['status'] == 'APPROVED' && token is String && token.isNotEmpty) {
      _sharedAccessToken = token;
    } else {
      _sharedAccessToken = null;
    }
    return data;
  }

  Future<Map<String, dynamic>> mobileStatus(String mobileE164, String deviceId) async {
    final uri = Uri.parse('$baseUrl/api/v1/auth/mobile-status').replace(
      queryParameters: {'mobile_e164': mobileE164.trim(), 'device_id': deviceId},
    );
    return _decode(await _client.get(uri, headers: _headers));
  }

  Future<List<Map<String, dynamic>>> subscriptionPlans() async {
    final data = _decode(await _client.get(
      Uri.parse('$baseUrl/api/v1/subscription/plans'),
      headers: _headers,
    ));
    return (data['plans'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>().toList(growable: false);
  }

  Future<Map<String, dynamic>> mySubscription() async {
    return _decode(await _client.get(
      Uri.parse('$baseUrl/api/v1/subscription/me'),
      headers: _headers,
    ));
  }

  Future<Map<String, dynamic>> me() async {
    return _decode(await _client.get(
      Uri.parse('$baseUrl/api/v1/auth/me'),
      headers: _headers,
    ));
  }

  Future<List<Map<String, dynamic>>> operatorAccessRequests({String? status}) async {
    final uri = Uri.parse('$baseUrl/api/v1/operator/access-requests').replace(
      queryParameters: status == null ? null : {'status': status},
    );
    final data = _decode(await _client.get(uri, headers: _headers));
    return (data['requests'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>().toList(growable: false);
  }

  Future<Map<String, dynamic>> reviewOperatorAccessRequest(
      String requestId, String status, {String note = ''}) async {
    final response = await _client.put(
      Uri.parse('$baseUrl/api/v1/operator/access-requests/$requestId'),
      headers: _headers,
      body: jsonEncode({'status': status, 'note': note}),
    );
    return _decode(response);
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

  Future<Map<String, dynamic>> brokerLoginUrl(String broker, String accountId) async {
    final path = switch (broker) {
      'zerodha' => 'zerodha',
      'upstox' => 'upstox',
      'fyers' => 'fyers',
      _ => throw ArgumentError('OAuth login URL is not available for $broker'),
    };
    return _decode(await _client.get(
      Uri.parse('$baseUrl/api/v1/customer/accounts/$path/'
          '${Uri.encodeComponent(accountId)}/login-url'),
      headers: _headers,
    ));
  }

  Future<Map<String, dynamic>> brokerExchange(
      String broker, String accountId, String code, {String? state}) async {
    final path = switch (broker) {
      'zerodha' => 'zerodha',
      'upstox' => 'upstox',
      'fyers' => 'fyers',
      _ => throw ArgumentError('OAuth exchange is not available for $broker'),
    };
    final payload = switch (broker) {
      'zerodha' => {'request_token': code},
      'upstox' => {'code': code, 'state': state ?? ''},
      'fyers' => {'auth_code': code, 'state': state ?? ''},
      _ => <String, String>{},
    };
    return _decode(await _client.post(
      Uri.parse('$baseUrl/api/v1/customer/accounts/$path/'
          '${Uri.encodeComponent(accountId)}/exchange'),
      headers: _headers,
      body: jsonEncode(payload),
    ));
  }

  Future<Map<String, dynamic>> verifyDhan(String accountId) async {
    return _decode(await _client.post(
      Uri.parse('$baseUrl/api/v1/customer/accounts/dhan/'
          '${Uri.encodeComponent(accountId)}/verify'),
      headers: _headers,
    ));
  }

  Future<Map<String, dynamic>> loginAngel(String accountId, String totp) async {
    return _decode(await _client.post(
      Uri.parse('$baseUrl/api/v1/customer/accounts/angel-one/'
          '${Uri.encodeComponent(accountId)}/login'),
      headers: _headers,
      body: jsonEncode({'totp': totp}),
    ));
  }

  Future<List<Map<String, dynamic>>> operatorBrokerAccounts() async {
    final data = _decode(await _client.get(
      Uri.parse('$baseUrl/api/v1/operator/broker-accounts'),
      headers: _headers,
    ));
    return (data['accounts'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>().toList(growable: false);
  }

  Future<Map<String, dynamic>> operatorMarketDataSources() async {
    return _decode(await _client.get(
      Uri.parse('$baseUrl/api/v1/operator/market-data/sources'),
      headers: _headers,
    ));
  }

  Future<Map<String, dynamic>> operatorSaveMarketInstrument({
    required String provider,
    required String accountId,
    required String exchange,
    required String symbol,
    required String token,
    required String segment,
  }) async {
    return _decode(await _client.post(
      Uri.parse('$baseUrl/api/v1/operator/market-data/instruments'),
      headers: _headers,
      body: jsonEncode({
        'provider': provider,
        'account_id': accountId,
        'exchange': exchange,
        'symbol': symbol,
        'token': token,
        'segment': segment,
      }),
    ));
  }

  Future<List<Map<String, dynamic>>> operatorMarketInstruments({
    String? provider,
    String? accountId,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/operator/market-data/instruments')
        .replace(queryParameters: {
      if (provider != null) 'provider': provider,
      if (accountId != null) 'account_id': accountId,
    });
    final data = _decode(await _client.get(uri, headers: _headers));
    return (data['instruments'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>().toList(growable: false);
  }

  Future<Map<String, dynamic>> operatorExecutionPolicy() async {
    return _decode(await _client.get(
      Uri.parse('$baseUrl/api/v1/operator/execution-policy'),
      headers: _headers,
    ));
  }

  Future<Map<String, dynamic>> updateOperatorExecutionPolicy({
    required bool masterAutoEnabled,
    required Map<String, bool> strategies,
  }) async {
    return _decode(await _client.put(
      Uri.parse('$baseUrl/api/v1/operator/execution-policy'),
      headers: _headers,
      body: jsonEncode({
        'master_auto_enabled': masterAutoEnabled,
        'strategies': strategies,
      }),
    ));
  }

  Future<Map<String, dynamic>> refreshBrokerMasters() async {
    return _decode(await _client.post(
      Uri.parse('$baseUrl/api/v1/operator/market-data/masters/refresh'),
      headers: _headers,
    ));
  }

  Future<Map<String, dynamic>> brokerMasterStatus() async {
    return _decode(await _client.get(
      Uri.parse('$baseUrl/api/v1/operator/market-data/master-status'),
      headers: _headers,
    ));
  }

  Future<Map<String, dynamic>> operatorConfigureMarketDataFailover(
      String channel, bool enabled, List<Map<String, String>> candidates) async {
    return _decode(await _client.put(
      Uri.parse('$baseUrl/api/v1/operator/market-data/sources/$channel/failover'),
      headers: _headers,
      body: jsonEncode({'enabled': enabled, 'candidates': candidates}),
    ));
  }

  Future<Map<String, dynamic>> operatorVerifyMarketDataSource(
      String channel, {int waitSeconds = 12}) async {
    return _decode(await _client.post(
      Uri.parse('$baseUrl/api/v1/operator/market-data/verify/$channel')
          .replace(queryParameters: {'wait_seconds': waitSeconds.toString()}),
      headers: _headers,
    ));
  }

  Future<Map<String, dynamic>> operatorSelectMarketDataSource(
      String channel, String provider, {String? accountId, bool enabled = true}) async {
    return _decode(await _client.put(
      Uri.parse('$baseUrl/api/v1/operator/market-data/sources/$channel'),
      headers: _headers,
      body: jsonEncode({
        'provider': provider,
        'account_id': accountId,
        'enabled': enabled,
      }),
    ));
  }

  Future<Map<String, dynamic>> operatorAssignBrokerAccount(
      String customerId, String broker, String accountId) async {
    return _decode(await _client.post(
      Uri.parse('$baseUrl/api/v1/operator/broker-accounts'),
      headers: _headers,
      body: jsonEncode({
        'customer_id': customerId.trim(),
        'broker': broker,
        'account_id': accountId.trim(),
      }),
    ));
  }

  Future<Map<String, dynamic>> operatorSetCustomerMarketDataAccess(
      String customerId, {required String tier, required bool brokerDataEnabled}) async {
    return _decode(await _client.put(
      Uri.parse('$baseUrl/api/v1/operator/customers/'
          '${Uri.encodeComponent(customerId)}/market-data-access'),
      headers: _headers,
      body: jsonEncode({
        'tier': tier,
        'broker_data_enabled': brokerDataEnabled,
      }),
    ));
  }

  Future<Map<String, dynamic>> operatorSetCustomerMarketDataSelection(
      String customerId, String broker, String accountId) async {
    return _decode(await _client.put(
      Uri.parse('$baseUrl/api/v1/operator/customers/'
          '${Uri.encodeComponent(customerId)}/market-data-selection'),
      headers: _headers,
      body: jsonEncode({
        'provider': broker,
        'account_id': accountId,
      }),
    ));
  }

  Future<Map<String, dynamic>> operatorSaveBrokerCredentials(
      String customerId, String broker, String accountId,
      Map<String, String> credentials) async {
    return _decode(await _client.put(
      Uri.parse('$baseUrl/api/v1/operator/broker-accounts/'
          '${Uri.encodeComponent(customerId)}/${Uri.encodeComponent(broker)}/'
          '${Uri.encodeComponent(accountId)}/credentials'),
      headers: _headers,
      body: jsonEncode({'credentials': credentials}),
    ));
  }

  Future<Map<String, dynamic>> operatorRemoveBrokerAccount(
      String customerId, String broker, String accountId) async {
    return _decode(await _client.delete(
      Uri.parse('$baseUrl/api/v1/operator/broker-accounts/'
          '${Uri.encodeComponent(customerId)}/${Uri.encodeComponent(broker)}/'
          '${Uri.encodeComponent(accountId)}'),
      headers: _headers,
    ));
  }

  Future<Map<String, dynamic>> operatorTelegramDestinations() async {
    return _decode(await _client.get(
      Uri.parse('$baseUrl/api/v1/operator/telegram/destinations'),
      headers: _headers,
    ));
  }

  Future<Map<String, dynamic>> operatorSaveTelegramDestination({
    int? id,
    required String name,
    required String chatId,
    required String destinationType,
    required List<String> strategies,
    required bool enabled,
  }) async {
    final body = jsonEncode({
      'name': name.trim(),
      'chat_id': chatId.trim(),
      'destination_type': destinationType,
      'strategies': strategies,
      'enabled': enabled,
    });
    final response = id == null
        ? await _client.post(
            Uri.parse('$baseUrl/api/v1/operator/telegram/destinations'),
            headers: _headers,
            body: body,
          )
        : await _client.put(
            Uri.parse('$baseUrl/api/v1/operator/telegram/destinations/$id'),
            headers: _headers,
            body: body,
          );
    return _decode(response);
  }

  Future<Map<String, dynamic>> operatorDeleteTelegramDestination(int id) async {
    return _decode(await _client.delete(
      Uri.parse('$baseUrl/api/v1/operator/telegram/destinations/$id'),
      headers: _headers,
    ));
  }

  Future<Map<String, dynamic>> operatorTestTelegramDestination({int? id}) async {
    final uri = Uri.parse('$baseUrl/api/v1/operator/telegram/test').replace(
      queryParameters: id == null ? null : {'destination_id': id.toString()},
    );
    return _decode(await _client.post(uri, headers: _headers));
  }

  Future<Map<String, dynamic>> nseDataStatus() async {
    return _decode(await _client.get(
      Uri.parse('$baseUrl/api/v1/nse-data/status'),
      headers: _headers,
    ));
  }

  Future<Map<String, dynamic>> nseDataRows({
    required String market,
    String? symbol,
    String? startDate,
    String? endDate,
    String? instrumentType,
    int limit = 100,
  }) async {
    final query = <String, String>{
      'market': market,
      'limit': limit.toString(),
      if (symbol != null && symbol.trim().isNotEmpty) 'symbol': symbol.trim(),
      if (startDate != null) 'start_date': startDate,
      if (endDate != null) 'end_date': endDate,
      if (instrumentType != null && instrumentType.isNotEmpty) 'instrument_type': instrumentType,
    };
    final uri = Uri.parse('$baseUrl/api/v1/nse-data/rows').replace(queryParameters: query);
    return _decode(await _client.get(uri, headers: _headers));
  }

  Future<Map<String, dynamic>> triggerNseBootstrap() async {
    return _decode(await _client.post(
      Uri.parse('$baseUrl/api/v1/nse-data/bootstrap'),
      headers: _headers,
    ));
  }

  Future<Map<String, dynamic>> modelEngineLedger({int limit = 500}) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/api/v1/model-engine/ledger?limit=$limit'),
      headers: _headers,
    );
    return _decode(response);
  }

  Future<Map<String, dynamic>> modelEngineMaster({int limit = 2000}) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/api/v1/model-engine/master?limit=$limit'),
      headers: _headers,
    );
    return _decode(response);
  }


  Future<Map<String, dynamic>> orbStatus() async => _decode(await _client.get(
    Uri.parse('$baseUrl/api/v1/orb/status'), headers: _headers));

  Future<Map<String, dynamic>> orbSubscribe(List<String> symbols) async => _decode(
    await _client.post(Uri.parse('$baseUrl/api/v1/orb/subscribe'),
      headers: _headers, body: jsonEncode({'symbols': symbols})));

  Future<Map<String, dynamic>> modelEnginePnlCalendar({int? year, int? month}) async {
    final query = <String, String>{
      if (year != null) 'year': year.toString(),
      if (month != null) 'month': month.toString(),
    };
    final uri = Uri.parse('$baseUrl/api/v1/model-engine/pnl-calendar')
        .replace(queryParameters: query.isEmpty ? null : query);
    return _decode(await _client.get(uri, headers: _headers));
  }

  Future<Map<String, dynamic>> reportEmail() async => _decode(await _client.get(
    Uri.parse('$baseUrl/api/v1/customer/reports/email'), headers: _headers));

  Future<Map<String, dynamic>> requestReportEmailVerification(String email) async => _decode(
    await _client.post(Uri.parse('$baseUrl/api/v1/customer/reports/email/verification'),
      headers: _headers, body: jsonEncode({'email': email.trim()})));

  Future<Map<String, dynamic>> confirmReportEmailVerification(String code) async => _decode(
    await _client.post(Uri.parse('$baseUrl/api/v1/customer/reports/email/verification/confirm'),
      headers: _headers, body: jsonEncode({'code': code.trim()})));

  Future<Map<String, dynamic>> accountReportHistory() async => _decode(await _client.get(
    Uri.parse('$baseUrl/api/v1/customer/reports/history'), headers: _headers));

  Future<Map<String, dynamic>> runAccountReports() async => _decode(await _client.post(
    Uri.parse('$baseUrl/api/v1/customer/reports/run'), headers: _headers));

  Future<Map<String, dynamic>> settlementComparison({int limit = 500}) async {
    final uri = Uri.parse('$baseUrl/api/v1/model-engine/settlement-comparison')
        .replace(queryParameters: {'limit': limit.toString()});
    return _decode(await _client.get(uri, headers: _headers));
  }

  Future<Map<String, dynamic>> physicalSettlement() async {
    final response = await _client.get(
      Uri.parse('$baseUrl/api/v1/model-engine/physical-settlement'),
      headers: _headers,
    );
    return _decode(response);
  }

  Future<Map<String, dynamic>> expiryScan({int maxDte = 45, int limit = 500}) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/api/v1/model-engine/expiryscan?max_dte=$maxDte&limit=$limit'),
      headers: _headers,
    );
    return _decode(response);
  }

  Future<Map<String, dynamic>> dhanFnoUniverse() async {
    final response = await _client.get(
      Uri.parse('$baseUrl/api/v1/air-qoc/dhan/universe'),
      headers: _headers,
    );
    return _decode(response);
  }

  Future<Map<String, dynamic>> dhanDataStatus(String accountId) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/api/v1/air-qoc/dhan/status/$accountId'),
      headers: _headers,
    );
    return _decode(response);
  }

  Future<List<String>> dhanExpiryList(String accountId, int underlyingScrip,
      String underlyingSegment) async {
    final response = await _client.post(
      Uri.parse('$baseUrl/api/v1/air-qoc/dhan/expiry-list/$accountId'),
      headers: _headers,
      body: jsonEncode({
        'underlying_scrip': underlyingScrip,
        'underlying_segment': underlyingSegment,
      }),
    );
    final data = _decode(response);
    return (data['expiries'] as List<dynamic>? ?? const [])
        .whereType<String>().toList(growable: false);
  }

  Future<Map<String, dynamic>> dhanOptionChain(String accountId,
      int underlyingScrip, String underlyingSegment, String expiry) async {
    final response = await _client.post(
      Uri.parse('$baseUrl/api/v1/air-qoc/dhan/option-chain/$accountId'),
      headers: _headers,
      body: jsonEncode({
        'underlying_scrip': underlyingScrip,
        'underlying_segment': underlyingSegment,
        'expiry': expiry,
      }),
    );
    return _decode(response);
  }

  Future<Map<String, dynamic>> runQocEodCapture() async {
    final response = await _client.post(
      Uri.parse('$baseUrl/api/v1/air-qoc/run-eod-capture'),
      headers: _headers,
    );
    return _decode(response);
  }

  Future<List<Map<String, dynamic>>> dhanObservations(String accountId) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/api/v1/air-qoc/dhan/observations/$accountId'),
      headers: _headers,
    );
    final data = _decode(response);
    return (data['observations'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>().toList(growable: false);
  }

  Map<String, dynamic> _decode(http.Response response) {
    Map<String, dynamic> body;
    try {
      body = jsonDecode(response.body) as Map<String, dynamic>;
    } catch (_) {
      throw AirApiException('AIR server returned an invalid response (\${response.statusCode}).');
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw AirApiException(
        body['detail']?.toString() ?? 'AIR server request failed (\${response.statusCode}).',
      );
    }
    return body;
  }

  void dispose() => _client.close();
}
