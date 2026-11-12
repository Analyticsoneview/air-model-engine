import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

import '../services/air_api_client.dart';

class AirAdminConsoleScreen extends StatefulWidget {
  const AirAdminConsoleScreen({super.key});

  @override
  State<AirAdminConsoleScreen> createState() => _AirAdminConsoleScreenState();
}

class _AirAdminConsoleScreenState extends State<AirAdminConsoleScreen> {
  static const _storage = FlutterSecureStorage();
  late final String _apiBase = AirApiClient.configuredBaseUrl ?? 'http://127.0.0.1:8000';
  final _client = http.Client();
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _totp = TextEditingController();
  final _newEmail = TextEditingController();
  final _newPassword = TextEditingController();
  final _subscriptionCustomer = TextEditingController();
  final _requestSearch = TextEditingController();
  final _customerSearch = TextEditingController();
  final _offerName = TextEditingController();
  final _offerCode = TextEditingController();
  final _offerDiscount = TextEditingController(text: '10');
  final _offerStarts = TextEditingController();
  final _offerExpires = TextEditingController();
  final _offerTerms = TextEditingController();
  String? _token;
  String? _error;
  String _role = '';
  String _tab = 'overview';
  bool _busy = false;
  bool _mustChangePassword = false;
  String _newRole = 'ADMIN';
  String _subscriptionPlan = 'MONTHLY';
  String _requestFilter = 'PENDING';
  String _customerSegment = 'ALL';
  String _offerPlan = 'MONTHLY';
  List<Map<String, dynamic>> _admins = [];
  List<Map<String, dynamic>> _audit = [];
  List<Map<String, dynamic>> _requests = [];
  List<Map<String, dynamic>> _customers = [];
  List<Map<String, dynamic>> _offers = [];
  Map<String, dynamic> _segmentCounts = {};

  Uri _uri(String path) => Uri.parse('$_apiBase$path');
  Map<String, String> _headers({bool auth = true}) => {
    'Accept': 'application/json',
    'Content-Type': 'application/json',
    if (auth && _token != null) 'Authorization': 'Bearer $_token',
  };

  Future<Map<String, dynamic>> _request(String method, String path, {Map<String, dynamic>? body, bool auth = true}) async {
    final uri = _uri(path);
    final headers = _headers(auth: auth);
    late http.Response response;
    switch (method) {
      case 'POST': response = await _client.post(uri, headers: headers, body: body == null ? null : jsonEncode(body)); break;
      case 'PUT': response = await _client.put(uri, headers: headers, body: body == null ? null : jsonEncode(body)); break;
      default: response = await _client.get(uri, headers: headers);
    }
    final decoded = jsonDecode(response.body);
    final data = decoded is Map<String, dynamic> ? decoded : <String, dynamic>{};
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(data['detail']?.toString() ?? 'AIR API returned HTTP ${response.statusCode}');
    }
    return data;
  }

  @override
  void initState() {
    super.initState();
    _restore();
  }

  Future<void> _restore() async {
    final saved = await _storage.read(key: 'air_admin_access_token');
    if (saved == null || saved.isEmpty) return;
    _token = saved;
    try {
      final me = await _request('GET', '/api/v1/admin/auth/me');
      _role = me['role']?.toString() ?? '';
      _mustChangePassword = me['must_change_password'] == true;
      if (!_mustChangePassword) await _load();
      if (mounted) setState(() {});
    } catch (_) {
      await _storage.delete(key: 'air_admin_access_token');
      _token = null;
    }
  }

  Future<void> _login() async {
    if (_email.text.trim().isEmpty || _password.text.isEmpty || _totp.text.trim().length != 6) {
      setState(() => _error = 'Enter administrator email, password and current six-digit authenticator code.');
      return;
    }
    setState(() { _busy = true; _error = null; });
    try {
      final result = await _request('POST', '/api/v1/admin/auth/login', auth: false, body: {
        'email': _email.text.trim(), 'password': _password.text, 'totp_code': _totp.text.trim(),
      });
      _token = result['access_token']?.toString();
      if (_token == null || _token!.isEmpty) throw Exception('Admin API did not return a session token.');
      await _storage.write(key: 'air_admin_access_token', value: _token);
      final me = await _request('GET', '/api/v1/admin/auth/me');
      _role = me['role']?.toString() ?? '';
      _mustChangePassword = me['must_change_password'] == true;
      if (!_mustChangePassword) {
        await _load();
      } else if (mounted) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) _changePassword();
        });
      }
    } catch (e) {
      _error = e.toString();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _load() async {
    if (_token == null) return;
    final requestPath = _requestFilter == 'ALL'
        ? '/api/v1/admin/access-requests'
        : '/api/v1/admin/access-requests?status=$_requestFilter';
    final requestResults = await Future.wait([
      _request('GET', requestPath),
      if (_role == 'SUPER_ADMIN') _request('GET', '/api/v1/admin/users') else Future.value(<String,dynamic>{'admins': []}),
      if (_role == 'SUPER_ADMIN') _request('GET', '/api/v1/admin/audit?limit=100') else Future.value(<String,dynamic>{'events': []}),
    ]);
    _requests = (requestResults[0]['requests'] as List? ?? []).whereType<Map>().map((e) => Map<String,dynamic>.from(e)).toList();
    _admins = (requestResults[1]['admins'] as List? ?? []).whereType<Map>().map((e) => Map<String,dynamic>.from(e)).toList();
    _audit = (requestResults[2]['events'] as List? ?? []).whereType<Map>().map((e) => Map<String,dynamic>.from(e)).toList();
    if (_role == 'SUPER_ADMIN' || _role == 'ADMIN') {
      final growthResults = await Future.wait([
        _request('GET', '/api/v1/admin/marketing/customers?segment=$_customerSegment&search=${Uri.encodeQueryComponent(_customerSearch.text.trim())}&limit=500'),
        _request('GET', '/api/v1/admin/marketing/offers'),
      ]);
      _customers = (growthResults[0]['customers'] as List? ?? []).whereType<Map>().map((e) => Map<String,dynamic>.from(e)).toList();
      _segmentCounts = Map<String,dynamic>.from(growthResults[0]['segment_counts'] as Map? ?? {});
      _offers = (growthResults[1]['offers'] as List? ?? []).whereType<Map>().map((e) => Map<String,dynamic>.from(e)).toList();
    }
  }

  Future<void> _refresh() async {
    setState(() { _busy = true; _error = null; });
    try { await _load(); } catch (e) { _error = e.toString(); }
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _createAdmin() async {
    if (_role != 'SUPER_ADMIN') return;
    final email = _newEmail.text.trim();
    if (email.isEmpty) return;
    setState(() { _busy = true; _error = null; });
    try {
      final result = await _request('POST', '/api/v1/admin/users', body: {'email': email, 'role': _newRole});
      final password = result['temporary_password']?.toString() ?? '';
      final uri = result['totp_provisioning_uri']?.toString() ?? '';
      if (mounted) {
        await showDialog<void>(
          context: context,
          builder: (ctx) => AlertDialog(
            title: const Text('Administrator created'),
            content: SelectableText(
              'Temporary password (share securely once):\n$password\n\nAuthenticator setup URI:\n$uri',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('CLOSE'),
              ),
            ],
          ),
        );
      }
      _newEmail.clear();
      await _load();
    } catch (e) { _error = e.toString(); }
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _assignSubscription() async {
    if (!{'SUPER_ADMIN', 'ADMIN'}.contains(_role)) return;
    final customerId = _subscriptionCustomer.text.trim();
    if (customerId.isEmpty) {
      setState(() => _error = "Enter the customer E.164 mobile identity.");
      return;
    }
    setState(() { _busy = true; _error = null; });
    try {
      final result = await _request(
        'POST',
        '/api/v1/admin/subscriptions/assign',
        body: {'customer_id': customerId, 'plan_code': _subscriptionPlan},
      );
      _subscriptionCustomer.clear();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Activated ${result['plan_code']} for ${result['customer_id']}.'),
        ));
      }
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _review(Map<String,dynamic> row, String status) async {
    final noteController = TextEditingController();
    final mobile = row['mobile_e164']?.toString() ?? 'this customer';
    final accepted = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('$status access request?'),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('$status access for $mobile on device ${row['device_id'] ?? '—'}?'),
          if (status == 'BLOCKED') ...[
            const SizedBox(height: 8),
            const Text('Blocking revokes active sessions for this device. The customer will lose access immediately.'),
          ],
          const SizedBox(height: 12),
          TextField(controller: noteController, maxLength: 500, maxLines: 2,
            decoration: const InputDecoration(labelText: 'Administrator note (optional)', border: OutlineInputBorder())),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('CANCEL')),
          FilledButton(
            style: status == 'BLOCKED' ? FilledButton.styleFrom(backgroundColor: Theme.of(ctx).colorScheme.error) : null,
            onPressed: () => Navigator.pop(ctx, true), child: Text('CONFIRM $status')),
        ],
      ),
    );
    final note = noteController.text.trim();
    noteController.dispose();
    if (accepted != true || !mounted) return;
    setState(() { _busy = true; _error = null; });
    try {
      await _request('PUT', '/api/v1/admin/access-requests/${row['request_id']}', body: {'status': status, 'note': note});
      await _load();
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$mobile access status updated to $status.')));
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _changePassword() async {
    final current = TextEditingController();
    final next = TextEditingController();
    final accepted = await showDialog<bool>(context: context, builder: (ctx) => AlertDialog(
      title: const Text('Change administrator password'),
      content: Column(mainAxisSize: MainAxisSize.min, children: [
        TextField(controller: current, obscureText: true, decoration: const InputDecoration(labelText: 'Current password')),
        TextField(controller: next, obscureText: true, decoration: const InputDecoration(labelText: 'New password (12+ characters)')),
      ]),
      actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('CANCEL')),
        FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('UPDATE'))],
    ));
    if (accepted != true) { current.dispose(); next.dispose(); return; }
    try {
      await _request('PUT', '/api/v1/admin/auth/password', body: {'current_password': current.text, 'new_password': next.text});
      _mustChangePassword = false;
      await _load();
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Password changed. Other sessions were revoked.')));
    } catch (e) { if (mounted) setState(() => _error = e.toString()); }
    current.dispose(); next.dispose();
  }

  Future<void> _logout() async {
    try { await _request('POST', '/api/v1/admin/auth/logout'); } catch (_) {}
    await _storage.delete(key: 'air_admin_access_token');
    if (mounted) setState(() { _token = null; _role = ''; _admins = []; _audit = []; _requests = []; });
  }

  @override
  void dispose() {
    _client.close(); _email.dispose(); _password.dispose(); _totp.dispose();
    _newEmail.dispose(); _newPassword.dispose(); _subscriptionCustomer.dispose();
    _requestSearch.dispose(); _customerSearch.dispose();
    _offerName.dispose(); _offerCode.dispose(); _offerDiscount.dispose();
    _offerStarts.dispose(); _offerExpires.dispose(); _offerTerms.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final authenticated = _token != null;
    return Scaffold(
      appBar: AppBar(title: const Text('AIR ADMIN CONSOLE'), actions: [
        if (authenticated) IconButton(tooltip: 'Refresh', onPressed: _busy ? null : _refresh, icon: const Icon(Icons.refresh)),
        if (authenticated) IconButton(tooltip: 'Change password', onPressed: _changePassword, icon: const Icon(Icons.key)),
        if (authenticated) IconButton(tooltip: 'Sign out', onPressed: _logout, icon: const Icon(Icons.logout)),
      ]),
      body: SafeArea(child: authenticated ? _dashboard() : _loginForm()),
    );
  }

  Widget _loginForm() => Center(child: SingleChildScrollView(padding: const EdgeInsets.all(24), child: ConstrainedBox(
    constraints: const BoxConstraints(maxWidth: 440), child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const Icon(Icons.admin_panel_settings_outlined, size: 56, color: Color(0xFFE5B85C)),
      const SizedBox(height: 16),
      const Text('SECURE ADMINISTRATOR ACCESS', textAlign: TextAlign.center, style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: 1)),
      const SizedBox(height: 22),
      TextField(controller: _email, keyboardType: TextInputType.emailAddress, decoration: const InputDecoration(labelText: 'Administrator email')),
      const SizedBox(height: 12),
      TextField(controller: _password, obscureText: true, decoration: const InputDecoration(labelText: 'Password')),
      const SizedBox(height: 12),
      TextField(controller: _totp, keyboardType: TextInputType.number, maxLength: 6, decoration: const InputDecoration(labelText: 'Authenticator code')),
      if (_error != null) Padding(padding: const EdgeInsets.symmetric(vertical: 10), child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
      FilledButton(onPressed: _busy ? null : _login, child: _busy ? const CircularProgressIndicator() : const Text('SIGN IN')),
      const SizedBox(height: 12),
      const Text('Separate administrator identity · TOTP MFA · 20-minute session', textAlign: TextAlign.center, style: TextStyle(fontSize: 11, color: Colors.grey)),
    ]),
  )));

  Widget _dashboard() => Column(children: [
    ListTile(title: const Text('ADMINISTRATOR SESSION', style: TextStyle(fontWeight: FontWeight.w900)),
      subtitle: Text('Role: $_role · 20-minute API session'), trailing: const Icon(Icons.verified_user_outlined)),
    if (_mustChangePassword) Card(color: Theme.of(context).colorScheme.errorContainer, child: ListTile(leading: const Icon(Icons.lock_reset), title: const Text('Password rotation required'), subtitle: const Text('Change the temporary password before using administrator functions.'), trailing: TextButton(onPressed: _changePassword, child: const Text('CHANGE')))),
    if (_error != null) Padding(padding: const EdgeInsets.all(12), child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
    SingleChildScrollView(scrollDirection: Axis.horizontal, child: Row(children: [
      for (final item in ['overview','admins','requests','audit', if (_role == 'SUPER_ADMIN' || _role == 'ADMIN') 'subscriptions', if (_role == 'SUPER_ADMIN' || _role == 'ADMIN') 'customers', if (_role == 'SUPER_ADMIN' || _role == 'ADMIN') 'offers'])
        Padding(padding: const EdgeInsets.symmetric(horizontal: 4), child: ChoiceChip(label: Text(item.toUpperCase()), selected: _tab == item, onSelected: (_) => setState(() => _tab = item))),
    ])),
    Expanded(child: _tab == 'overview' ? _overview() : _tab == 'admins' ? _adminUsers() : _tab == 'requests' ? _accessRequests() : _tab == 'subscriptions' ? _subscriptions() : _tab == 'customers' ? _customerRegistry() : _tab == 'offers' ? _marketingOffers() : _auditView()),
  ]);


  String _maskCustomer(String value) {
    if (value.length < 7) return '••••';
    return '${value.substring(0, 3)}••••${value.substring(value.length - 3)}';
  }

  Future<void> _createMarketingOffer() async {
    if (_role != 'ADMIN' && _role != 'SUPER_ADMIN') return;
    final discount = double.tryParse(_offerDiscount.text.trim());
    if (_offerName.text.trim().isEmpty || _offerCode.text.trim().isEmpty ||
        discount == null || _offerStarts.text.trim().isEmpty || _offerExpires.text.trim().isEmpty) {
      setState(() => _error = 'Complete offer name, code, discount and validity dates.');
      return;
    }
    setState(() { _busy = true; _error = null; });
    try {
      final result = await _request('POST', '/api/v1/admin/marketing/offers', body: {
        'name': _offerName.text.trim(),
        'offer_code': _offerCode.text.trim(),
        'plan_code': _offerPlan,
        'discount_percent': discount,
        'starts_at': _offerStarts.text.trim(),
        'expires_at': _offerExpires.text.trim(),
        'terms': _offerTerms.text.trim(),
      });
      _offerName.clear(); _offerCode.clear(); _offerTerms.clear();
      await _load();
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result['message']?.toString() ?? 'Offer saved as draft.')));
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _reviewMarketingOffer(String offerId, String action) async {
    if (_role != 'SUPER_ADMIN') return;
    final approved = await showDialog<bool>(context: context, builder: (ctx) => AlertDialog(
      title: Text(action == 'approve' ? 'Approve promotional offer?' : 'Revoke promotional offer?'),
      content: Text(action == 'approve'
          ? 'This approves the offer definition. It does not send a campaign or contact any customer.'
          : 'This revokes the approved offer. No customer messages will be sent.'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('CANCEL')),
        FilledButton(onPressed: () => Navigator.pop(ctx, true), child: Text(action.toUpperCase())),
      ],
    ));
    if (approved != true || !mounted) return;
    setState(() { _busy = true; _error = null; });
    try {
      await _request('POST', '/api/v1/admin/marketing/offers/$offerId/$action');
      await _load();
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _customerRegistry() {
    final segments = const [
      ('ALL', 'All customers'),
      ('NEVER_SUBSCRIBED', 'Never subscribed'),
      ('EXPIRED', 'Expired'),
      ('CANCELLED', 'Cancelled'),
      ('INACTIVE', 'Previously subscribed · inactive'),
      ('ACTIVE', 'Active subscribers'),
      ('PENDING_ACCESS', 'Pending access'),
      ('OPTED_OUT', 'Opted out'),
      ('NOT_GRANTED', 'No marketing consent'),
    ];
    return ListView(padding: const EdgeInsets.all(16), children: [
      const Text('CUSTOMER GROWTH · REGISTRY', style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: .6)),
      const SizedBox(height: 5),
      const Text('One row per mobile identity. Customers with multiple devices are deduplicated. Promotional consent is customer-controlled; no consent is assumed.'),
      const SizedBox(height: 12),
      Wrap(spacing: 8, runSpacing: 8, children: [
        for (final key in ['ALL','NEVER_SUBSCRIBED','EXPIRED','CANCELLED','INACTIVE','ACTIVE','PENDING_ACCESS','ELIGIBLE_FOR_PROMOTIONS','NOT_GRANTED','OPTED_OUT'])
          Chip(label: Text('${key.replaceAll('_',' ')} · ${_segmentCounts[key] ?? 0}')),
      ]),
      const SizedBox(height: 12),
      DropdownButtonFormField<String>(
        initialValue: _customerSegment,
        decoration: const InputDecoration(labelText: 'Customer segment', border: OutlineInputBorder()),
        items: [for (final s in segments) DropdownMenuItem(value: s.$1, child: Text(s.$2))],
        onChanged: _busy ? null : (value) async {
          if (value == null) return;
          setState(() { _customerSegment = value; _busy = true; _error = null; });
          try { await _load(); } catch (e) { _error = e.toString(); }
          if (mounted) setState(() => _busy = false);
        },
      ),
      const SizedBox(height: 8),
      TextField(
        controller: _customerSearch,
        decoration: InputDecoration(labelText: 'Search mobile identity', prefixIcon: const Icon(Icons.search),
          suffixIcon: IconButton(onPressed: () { _customerSearch.clear(); _refresh(); }, icon: const Icon(Icons.close)),
          border: const OutlineInputBorder()),
        onSubmitted: (_) => _refresh(),
      ),
      const SizedBox(height: 8),
      OutlinedButton.icon(onPressed: _busy ? null : _refresh, icon: const Icon(Icons.refresh), label: const Text('REFRESH CUSTOMERS')),
      Text('${_customers.length} customer(s) displayed', style: Theme.of(context).textTheme.labelMedium),
      if (_customers.isEmpty) const Card(child: Padding(padding: EdgeInsets.all(24), child: Center(child: Text('No customers match this segment.')))),
      for (final customer in _customers)
        Card(child: ExpansionTile(
          title: Text(_maskCustomer(customer['customer_id']?.toString() ?? ''), style: const TextStyle(fontWeight: FontWeight.w800)),
          subtitle: Text('${customer['subscription_status']} · Access: ${customer['access_status']}'),
          childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          children: [
            SelectableText('Customer: ${customer['customer_id']}'),
            Align(alignment: Alignment.centerLeft, child: Text('Registered: ${customer['registered_at'] ?? '—'}')),
            Align(alignment: Alignment.centerLeft, child: Text('Devices: ${customer['device_count'] ?? 0}')),
            Align(alignment: Alignment.centerLeft, child: Text('Plan: ${customer['plan_code'] ?? 'None'}')),
            Align(alignment: Alignment.centerLeft, child: Text('Expiry: ${customer['subscription_expires_at'] ?? '—'}')),
            Align(alignment: Alignment.centerLeft, child: Text('Marketing: ${customer['marketing_status'] ?? 'NOT_GRANTED'}')),
            Align(alignment: Alignment.centerLeft, child: Text('Consent date: ${customer['consent_updated_at'] ?? '—'}')),
          ],
        )),
    ]);
  }

  Widget _marketingOffers() => ListView(padding: const EdgeInsets.all(16), children: [
    const Text('PROMOTIONAL OFFER MANAGEMENT', style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: .6)),
    const SizedBox(height: 5),
    const Text('Create draft offers for AIR plans. Offers require explicit Super Admin approval. Approval does not send messages or activate subscriptions.'),
    const SizedBox(height: 14),
    Card(child: Padding(padding: const EdgeInsets.all(14), child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const Text('CREATE OFFER DRAFT', style: TextStyle(fontWeight: FontWeight.w800)),
      const SizedBox(height: 10),
      TextField(controller: _offerName, decoration: const InputDecoration(labelText: 'Offer name', border: OutlineInputBorder())),
      const SizedBox(height: 8),
      TextField(controller: _offerCode, textCapitalization: TextCapitalization.characters, decoration: const InputDecoration(labelText: 'Offer code', border: OutlineInputBorder())),
      const SizedBox(height: 8),
      DropdownButtonFormField<String>(
        initialValue: _offerPlan, decoration: const InputDecoration(labelText: 'Applicable plan', border: OutlineInputBorder()),
        items: const [
          DropdownMenuItem(value: 'DAILY', child: Text('Daily')),
          DropdownMenuItem(value: 'MONTHLY', child: Text('Monthly')),
          DropdownMenuItem(value: 'SIX_MONTHS', child: Text('6 Months')),
          DropdownMenuItem(value: 'YEARLY', child: Text('Yearly')),
        ],
        onChanged: _busy ? null : (value) { if (value != null) setState(() => _offerPlan = value); },
      ),
      const SizedBox(height: 8),
      TextField(controller: _offerDiscount, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: const InputDecoration(labelText: 'Discount (%) · max 90', border: OutlineInputBorder())),
      const SizedBox(height: 8),
      TextField(controller: _offerStarts, decoration: const InputDecoration(labelText: 'Starts at (ISO-8601)', hintText: '2026-12-01T00:00:00Z', border: OutlineInputBorder())),
      const SizedBox(height: 8),
      TextField(controller: _offerExpires, decoration: const InputDecoration(labelText: 'Expires at (ISO-8601)', hintText: '2026-12-31T23:59:59Z', border: OutlineInputBorder())),
      const SizedBox(height: 8),
      TextField(controller: _offerTerms, maxLines: 3, maxLength: 1000, decoration: const InputDecoration(labelText: 'Terms and conditions', border: OutlineInputBorder())),
      FilledButton.icon(onPressed: _busy ? null : _createMarketingOffer, icon: const Icon(Icons.save_outlined), label: const Text('SAVE OFFER DRAFT')),
    ]))),
    const SizedBox(height: 12),
    const Text('SAVED OFFERS', style: TextStyle(fontWeight: FontWeight.w800)),
    if (_offers.isEmpty) const Text('No promotional offers have been created.'),
    for (final offer in _offers)
      Card(child: Padding(padding: const EdgeInsets.all(14), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(offer['name']?.toString() ?? '', style: const TextStyle(fontWeight: FontWeight.w800))),
          Chip(label: Text(offer['status']?.toString() ?? 'DRAFT')),
        ]),
        Text('Code: ${offer['offer_code']} · ${offer['discount_percent']}% off'),
        Text('Plan: ${offer['plan_code']}'),
        Text('Validity: ${offer['starts_at']} → ${offer['expires_at']}'),
        if ((offer['terms']?.toString() ?? '').isNotEmpty) Text('Terms: ${offer['terms']}'),
        if (_role == 'SUPER_ADMIN' && offer['status'] == 'DRAFT')
          Align(alignment: Alignment.centerRight, child: FilledButton(onPressed: _busy ? null : () => _reviewMarketingOffer(offer['offer_id'].toString(), 'approve'), child: const Text('SUPER ADMIN APPROVE'))),
        if (_role == 'SUPER_ADMIN' && offer['status'] == 'APPROVED')
          Align(alignment: Alignment.centerRight, child: TextButton(onPressed: _busy ? null : () => _reviewMarketingOffer(offer['offer_id'].toString(), 'revoke'), child: const Text('REVOKE OFFER'))),
      ]))),
  ]);

  Widget _overview() => ListView(padding: const EdgeInsets.all(16), children: [
    _metric('Administrators', _admins.length), _metric('Pending customer requests', _requests.length), _metric('Recent audit events', _audit.length),
    const Card(child: ListTile(leading: Icon(Icons.lock_outline), title: Text('Broker order execution'), subtitle: Text('Not controlled or enabled by this admin console. Execution remains separately permissioned and disabled by default.'))),
  ]);

  Widget _metric(String label, int value) => Card(child: ListTile(title: Text(label), trailing: Text('$value', style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w900))));

  Widget _adminUsers() => ListView(padding: const EdgeInsets.all(16), children: [
    if (_role == 'SUPER_ADMIN') ...[
      TextField(controller: _newEmail, decoration: const InputDecoration(labelText: 'New administrator email')),
      const SizedBox(height: 8),
      DropdownButtonFormField<String>(initialValue: _newRole, decoration: const InputDecoration(labelText: 'Administrator role'),
        items: const [DropdownMenuItem(value: 'ADMIN', child: Text('Admin')), DropdownMenuItem(value: 'RESEARCH_ADMIN', child: Text('Research Admin'))],
        onChanged: (value) { if (value != null) setState(() => _newRole = value); }),
      const SizedBox(height: 8), FilledButton(onPressed: _busy ? null : _createAdmin, child: const Text('CREATE ADMIN')),
    ],
    const SizedBox(height: 12),
    for (final a in _admins) Card(child: ListTile(
      title: Text(a['email']?.toString() ?? ''), subtitle: Text('${a['role']} · ${a['is_active'] == 1 ? 'ACTIVE' : 'INACTIVE'}'),
      trailing: _role == 'SUPER_ADMIN' ? PopupMenuButton<String>(
        onSelected: (action) async {
          setState(() { _busy = true; _error = null; });
          try {
            final id = a['admin_id'].toString();
            if (action == 'toggle') {
              await _request('PUT', '/api/v1/admin/users/$id/status', body: {'active': a['is_active'] != 1});
            } else {
              await _request('PUT', '/api/v1/admin/users/$id/role', body: {'role': action});
            }
            await _load();
          } catch (e) { _error = e.toString(); }
          if (mounted) setState(() => _busy = false);
        },
        itemBuilder: (_) => [
          PopupMenuItem(value: 'toggle', child: Text(a['is_active'] == 1 ? 'Deactivate' : 'Activate')),
          const PopupMenuItem(value: 'ADMIN', child: Text('Set Admin role')),
          const PopupMenuItem(value: 'RESEARCH_ADMIN', child: Text('Set Research Admin role')),
        ],
      ) : Text(a['admin_id']?.toString().substring(0,8) ?? ''),
    )),
  ]);

  Widget _subscriptions() => ListView(padding: const EdgeInsets.all(16), children: [
    const Text('CUSTOMER SUBSCRIPTION ACTIVATION', style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: .5)),
    const SizedBox(height: 8),
    const Text('Activate a plan for an approved customer. The customer identity must match the E.164 mobile number used to sign in. Online payments and automatic renewals are not enabled.'),
    const SizedBox(height: 16),
    TextField(
      controller: _subscriptionCustomer,
      keyboardType: TextInputType.phone,
      decoration: const InputDecoration(
        labelText: 'Customer mobile / identity (E.164)',
        hintText: '+91XXXXXXXXXX',
        border: OutlineInputBorder(),
      ),
    ),
    const SizedBox(height: 12),
    DropdownButtonFormField<String>(
      initialValue: _subscriptionPlan,
      decoration: const InputDecoration(labelText: 'Subscription plan', border: OutlineInputBorder()),
      items: const [
        DropdownMenuItem(value: 'DAILY', child: Text('Daily · 1 day')),
        DropdownMenuItem(value: 'MONTHLY', child: Text('Monthly · 30 days')),
        DropdownMenuItem(value: 'SIX_MONTHS', child: Text('6 months · 180 days')),
        DropdownMenuItem(value: 'YEARLY', child: Text('Yearly · 365 days')),
      ],
      onChanged: _busy ? null : (value) { if (value != null) setState(() => _subscriptionPlan = value); },
    ),
    const SizedBox(height: 12),
    FilledButton.icon(
      onPressed: _busy ? null : _assignSubscription,
      icon: const Icon(Icons.workspace_premium_outlined),
      label: const Text('ACTIVATE SUBSCRIPTION'),
    ),
  ]);

  Widget _accessRequests() {
    final query = _requestSearch.text.trim().toLowerCase();
    final rows = _requests.where((r) {
      final haystack = '${r['mobile_e164'] ?? ''} ${r['device_id'] ?? ''} ${r['request_id'] ?? ''}'.toLowerCase();
      return query.isEmpty || haystack.contains(query);
    }).toList();
    return ListView(padding: const EdgeInsets.all(16), children: [
      const Text('CUSTOMER DEVICE ACCESS', style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: .6)),
      const SizedBox(height: 5),
      const Text('Review customer requests, inspect device identity and manage access. Blocking revokes active sessions for the selected device.'),
      const SizedBox(height: 14),
      Wrap(spacing: 10, runSpacing: 10, crossAxisAlignment: WrapCrossAlignment.center, children: [
        SizedBox(width: 220, child: DropdownButtonFormField<String>(
          initialValue: _requestFilter,
          decoration: const InputDecoration(labelText: 'Request status', border: OutlineInputBorder(), isDense: true),
          items: const [
            DropdownMenuItem(value: 'PENDING', child: Text('Pending')),
            DropdownMenuItem(value: 'APPROVED', child: Text('Approved')),
            DropdownMenuItem(value: 'REJECTED', child: Text('Rejected')),
            DropdownMenuItem(value: 'BLOCKED', child: Text('Blocked')),
            DropdownMenuItem(value: 'ALL', child: Text('All requests')),
          ],
          onChanged: _busy ? null : (value) async {
            if (value == null) return;
            setState(() { _requestFilter = value; _busy = true; _error = null; });
            try { await _load(); } catch (e) { _error = e.toString(); }
            if (mounted) setState(() => _busy = false);
          },
        )),
        SizedBox(width: 300, child: TextField(
          controller: _requestSearch, onChanged: (_) => setState(() {}),
          decoration: InputDecoration(labelText: 'Search mobile, device or request ID', prefixIcon: const Icon(Icons.search),
            suffixIcon: IconButton(tooltip: 'Clear search', onPressed: () { _requestSearch.clear(); setState(() {}); }, icon: const Icon(Icons.close)),
            border: const OutlineInputBorder(), isDense: true),
        )),
        OutlinedButton.icon(onPressed: _busy ? null : _refresh, icon: const Icon(Icons.refresh), label: const Text('REFRESH')),
      ]),
      const SizedBox(height: 12),
      Text('${rows.length} request(s) shown', style: Theme.of(context).textTheme.labelMedium),
      if (rows.isEmpty) const Card(child: Padding(padding: EdgeInsets.all(24), child: Center(child: Text('No matching customer access requests.')))),
      for (final r in rows) ...[
        const SizedBox(height: 8),
        Card(child: Padding(padding: const EdgeInsets.all(14), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: SelectableText(r['mobile_e164']?.toString() ?? 'Unknown customer', style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16))),
            _requestStatusBadge(r['status']?.toString() ?? 'UNKNOWN'),
          ]),
          const SizedBox(height: 8),
          SelectableText('Device ID: ${r['device_id'] ?? '—'}'),
          if (r['created_at'] != null) Text('Submitted: ${r['created_at']}'),
          if ((r['reviewer_note']?.toString() ?? '').isNotEmpty) Text('Admin note: ${r['reviewer_note']}'),
          if (_role != 'RESEARCH_ADMIN' && (r['status'] == 'PENDING' || r['status'] == 'APPROVED')) ...[
            const SizedBox(height: 12),
            Wrap(spacing: 8, runSpacing: 6, children: [
              if (r['status'] == 'PENDING') FilledButton.tonalIcon(onPressed: _busy ? null : () => _review(r, 'APPROVED'), icon: const Icon(Icons.check_circle_outline), label: const Text('APPROVE')),
              OutlinedButton.icon(onPressed: _busy ? null : () => _review(r, 'REJECTED'), icon: const Icon(Icons.cancel_outlined), label: const Text('REJECT')),
              OutlinedButton.icon(style: OutlinedButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error),
                onPressed: _busy ? null : () => _review(r, 'BLOCKED'), icon: const Icon(Icons.block), label: const Text('BLOCK DEVICE')),
            ]),
          ],
        ]))),
      ],
    ]);
  }

  Widget _requestStatusBadge(String status) {
    final color = switch (status) {
      'APPROVED' => Colors.green,
      'REJECTED' || 'BLOCKED' => Theme.of(context).colorScheme.error,
      _ => Colors.orange,
    };
    return Container(padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration: BoxDecoration(color: color.withValues(alpha: .12), borderRadius: BorderRadius.circular(20)),
      child: Text(status, style: TextStyle(color: color, fontSize: 10, fontWeight: FontWeight.w900)));
  }

  Widget _auditView() => ListView(padding: const EdgeInsets.all(16), children: [
    for (final e in _audit) Card(child: ListTile(title: Text(e['action']?.toString() ?? ''), subtitle: Text('${e['created_at']} · target ${e['target_admin_id'] ?? '—'}'))),
  ]);
}
