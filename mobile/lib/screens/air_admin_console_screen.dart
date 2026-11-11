import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

class AirAdminConsoleScreen extends StatefulWidget {
  const AirAdminConsoleScreen({super.key});

  @override
  State<AirAdminConsoleScreen> createState() => _AirAdminConsoleScreenState();
}

class _AirAdminConsoleScreenState extends State<AirAdminConsoleScreen> {
  static const _storage = FlutterSecureStorage();
  static const _apiBase = String.fromEnvironment('AIR_API_BASE_URL', defaultValue: 'http://127.0.0.1:8000');
  final _client = http.Client();
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _totp = TextEditingController();
  final _newEmail = TextEditingController();
  final _newPassword = TextEditingController();
  String? _token;
  String? _error;
  String _role = '';
  String _tab = 'overview';
  bool _busy = false;
  bool _mustChangePassword = false;
  String _newRole = 'ADMIN';
  List<Map<String, dynamic>> _admins = [];
  List<Map<String, dynamic>> _audit = [];
  List<Map<String, dynamic>> _requests = [];

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
    final requestResults = await Future.wait([
      _request('GET', '/api/v1/admin/access-requests?status=PENDING'),
      if (_role == 'SUPER_ADMIN') _request('GET', '/api/v1/admin/users') else Future.value(<String,dynamic>{'admins': []}),
      if (_role == 'SUPER_ADMIN') _request('GET', '/api/v1/admin/audit?limit=100') else Future.value(<String,dynamic>{'events': []}),
    ]);
    _requests = (requestResults[0]['requests'] as List? ?? []).whereType<Map>().map((e) => Map<String,dynamic>.from(e)).toList();
    _admins = (requestResults[1]['admins'] as List? ?? []).whereType<Map>().map((e) => Map<String,dynamic>.from(e)).toList();
    _audit = (requestResults[2]['events'] as List? ?? []).whereType<Map>().map((e) => Map<String,dynamic>.from(e)).toList();
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
      if (mounted) await showDialog<void>(context: context, builder: (ctx) => AlertDialog(
        title: const Text('Administrator created'),
        content: SelectableText('Temporary password (share securely once):\n$password\n\nAuthenticator setup URI:\n$uri'),
        actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('CLOSE'))],
      ));
      _newEmail.clear();
      await _load();
    } catch (e) { _error = e.toString(); }
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _review(Map<String,dynamic> row, String status) async {
    setState(() { _busy = true; _error = null; });
    try {
      await _request('PUT', '/api/v1/admin/access-requests/${row['request_id']}', body: {'status': status, 'note': 'Reviewed in AIR Admin'});
      await _load();
    } catch (e) { _error = e.toString(); }
    if (mounted) setState(() => _busy = false);
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
    _newEmail.dispose(); _newPassword.dispose();
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
      for (final item in ['overview','admins','requests','audit'])
        Padding(padding: const EdgeInsets.symmetric(horizontal: 4), child: ChoiceChip(label: Text(item.toUpperCase()), selected: _tab == item, onSelected: (_) => setState(() => _tab = item))),
    ])),
    Expanded(child: _tab == 'overview' ? _overview() : _tab == 'admins' ? _adminUsers() : _tab == 'requests' ? _accessRequests() : _auditView()),
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
      DropdownButtonFormField<String>(value: _newRole, decoration: const InputDecoration(labelText: 'Administrator role'),
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

  Widget _accessRequests() => ListView(padding: const EdgeInsets.all(16), children: [
    if (_requests.isEmpty) const Text('No pending customer access requests.'),
    for (final r in _requests) Card(child: ListTile(
      title: Text(r['mobile_e164']?.toString() ?? 'Unknown customer'),
      subtitle: Text('Device: ${r['device_id'] ?? '—'}'),
      isThreeLine: true,
      trailing: _role == 'RESEARCH_ADMIN' ? const Text('READ ONLY') : Wrap(children: [
        IconButton(tooltip: 'Approve', onPressed: _busy ? null : () => _review(r,'APPROVED'), icon: const Icon(Icons.check_circle_outline)),
        IconButton(tooltip: 'Reject', onPressed: _busy ? null : () => _review(r,'REJECTED'), icon: const Icon(Icons.block_outlined)),
      ]),
    )),
  ]);

  Widget _auditView() => ListView(padding: const EdgeInsets.all(16), children: [
    for (final e in _audit) Card(child: ListTile(title: Text(e['action']?.toString() ?? ''), subtitle: Text('${e['created_at']} · target ${e['target_admin_id'] ?? '—'}'))),
  ]);
}
