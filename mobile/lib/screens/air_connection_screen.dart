import 'package:flutter/material.dart';

import '../services/air_api_client.dart';

class AirConnectionScreen extends StatefulWidget {
  const AirConnectionScreen({super.key});

  @override
  State<AirConnectionScreen> createState() => _AirConnectionScreenState();
}

class _AirConnectionScreenState extends State<AirConnectionScreen> {
  final AirApiClient _api = AirApiClient();
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _accountId = TextEditingController();
  List<Map<String, dynamic>> _brokers = [];
  List<Map<String, dynamic>> _accounts = [];
  String? _selectedBroker;
  String? _error;
  bool _loading = false;
  bool _authenticated = false;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _accountId.dispose();
    _api.dispose();
    super.dispose();
  }

  Future<void> _login() async {
    setState(() { _loading = true; _error = null; });
    try {
      await _api.login(_email.text, _password.text);
      final brokers = await _api.brokerCatalog();
      final accounts = await _api.accounts();
      if (!mounted) return;
      setState(() {
        _brokers = brokers;
        _accounts = accounts;
        _authenticated = true;
        _selectedBroker = _brokers.isNotEmpty ? _brokers.first['code'] as String : null;
      });
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _addAccount() async {
    final broker = _selectedBroker;
    if (broker == null || _accountId.text.trim().isEmpty) return;
    setState(() { _loading = true; _error = null; });
    try {
      await _api.addAccount(broker, _accountId.text);
      final accounts = await _api.accounts();
      if (!mounted) return;
      setState(() {
        _accounts = accounts;
        _accountId.clear();
      });
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }


  Future<void> _editCredentials(Map<String, dynamic> account) async {
    final broker = account['broker'] as String;
    final accountId = account['account_id'] as String;
    final fields = <String, List<String>>{
      'angelone': ['api_key', 'pin'],
      'dhan': ['client_id', 'access_token'],
      'zerodha': ['api_key', 'api_secret'],
      'upstox': ['client_id', 'client_secret', 'redirect_uri'],
      'fyers': ['app_id', 'app_secret', 'redirect_uri'],
    }[broker] ?? const <String>[];
    if (fields.isEmpty) return;
    final controllers = {
      for (final field in fields) field: TextEditingController(),
    };
    final values = await showDialog<Map<String, String>>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text('Secure $broker credentials'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: fields.map((field) => Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: TextField(
                controller: controllers[field],
                obscureText: field.contains('secret') || field == 'pin' || field.contains('token'),
                decoration: InputDecoration(
                  labelText: field.replaceAll('_', ' ').toUpperCase(),
                  border: const OutlineInputBorder(),
                ),
              ),
            )).toList(),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('CANCEL'),
          ),
          FilledButton(
            onPressed: () {
              final result = <String, String>{
                for (final field in fields)
                  if (controllers[field]!.text.trim().isNotEmpty)
                    field: controllers[field]!.text.trim(),
              };
              if (result.length != fields.length) return;
              Navigator.pop(dialogContext, result);
            },
            child: const Text('SAVE ENCRYPTED'),
          ),
        ],
      ),
    );
    for (final controller in controllers.values) {
      controller.dispose();
    }
    if (values == null) return;
    setState(() { _loading = true; _error = null; });
    try {
      await _api.saveCredentials(broker, accountId, values);
      final accounts = await _api.accounts();
      if (!mounted) return;
      setState(() => _accounts = accounts);
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: const Text('AIR CONNECTIONS')),
      body: ListView(
        padding: const EdgeInsets.all(18),
        children: [
          Text('Connect your AIR account to the self-hosted backend.',
              style: TextStyle(color: cs.onSurfaceVariant)),
          const SizedBox(height: 14),
          if (!_authenticated) ...[
            TextField(
              controller: _email,
              keyboardType: TextInputType.emailAddress,
              autofillHints: const [AutofillHints.username],
              decoration: const InputDecoration(labelText: 'AIR email', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _password,
              obscureText: true,
              autofillHints: const [AutofillHints.password],
              decoration: const InputDecoration(labelText: 'Password', border: OutlineInputBorder()),
              onSubmitted: (_) => _loading ? null : _login(),
            ),
            const SizedBox(height: 12),
            FilledButton(
              onPressed: _loading ? null : _login,
              child: Text(_loading ? 'CONNECTING…' : 'SIGN IN'),
            ),
          ] else ...[
            Row(children: [
              const Icon(Icons.verified_user_outlined, color: Colors.green),
              const SizedBox(width: 8),
              const Expanded(child: Text('AIR account authenticated')),
              TextButton(
                onPressed: () => setState(() {
                  _api.logout();
                  _authenticated = false;
                  _accounts = [];
                  _brokers = [];
                }),
                child: const Text('SIGN OUT'),
              ),
            ]),
            const SizedBox(height: 14),
            const Text('BROKER ACCOUNTS', style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: .8)),
            const SizedBox(height: 8),
            DropdownButtonFormField<String>(
              initialValue: _selectedBroker,
              decoration: const InputDecoration(labelText: 'Broker', border: OutlineInputBorder()),
              items: _brokers.map((broker) => DropdownMenuItem<String>(
                value: broker['code'] as String,
                child: Text(broker['name'] as String? ?? broker['code'] as String),
              )).toList(),
              onChanged: (value) => setState(() => _selectedBroker = value),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _accountId,
              decoration: const InputDecoration(labelText: 'Broker account ID', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 10),
            OutlinedButton.icon(
              onPressed: _loading ? null : _addAccount,
              icon: const Icon(Icons.add_link),
              label: const Text('REGISTER BROKER ACCOUNT'),
            ),
            const SizedBox(height: 14),
            if (_accounts.isEmpty)
              const Text('No broker accounts registered yet.')
            else
              ..._accounts.map((account) => Card(
                child: ListTile(
                  leading: const Icon(Icons.account_balance),
                  title: Text('${account['broker']} · ${account['account_id']}'),
                  subtitle: Text(account['credentials_saved'] == true
                      ? 'Encrypted credentials saved'
                      : 'Account registered · credentials not saved'),
                  trailing: IconButton(
                    tooltip: 'Save encrypted broker credentials',
                    onPressed: _loading ? null : () => _editCredentials(account),
                    icon: Icon(
                      account['credentials_saved'] == true
                          ? Icons.verified_user_outlined
                          : Icons.vpn_key_outlined,
                      color: cs.primary,
                    ),
                  ),
                ),
              )),
            const SizedBox(height: 14),
            Text(
              'Registering an account does not connect a live feed or enable order placement. Broker authorization and verification must be completed separately.',
              style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
            ),
          ],
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(_error!, style: TextStyle(color: cs.error)),
          ],
          if (_loading) const Padding(
            padding: EdgeInsets.only(top: 12),
            child: LinearProgressIndicator(),
          ),
        ],
      ),
    );
  }
}
