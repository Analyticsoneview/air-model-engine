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
  List<Map<String, dynamic>> _accounts = [];
  String? _error;
  bool _loading = false;
  bool _authenticated = false;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _api.dispose();
    super.dispose();
  }

  Future<void> _login() async {
    setState(() { _loading = true; _error = null; });
    try {
      await _api.login(_email.text, _password.text);
      final accounts = await _api.accounts();
      if (!mounted) return;
      setState(() {
        _accounts = accounts;
        _authenticated = true;
      });
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
                }),
                child: const Text('SIGN OUT'),
              ),
            ]),
            const SizedBox(height: 14),
            const Text('BROKER ACCOUNTS', style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: .8)),
            const SizedBox(height: 8),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.lock_outline_rounded),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        'Broker accounts are assigned and managed only by AIR Admin. '
                        'This customer view is read-only; contact the administrator '
                        'to add, change or remove an account.',
                        style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
                      ),
                    ),
                  ],
                ),
              ),
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
                  trailing: Icon(
                    account['credentials_saved'] == true
                        ? Icons.verified_user_outlined
                        : Icons.lock_outline_rounded,
                    color: cs.onSurfaceVariant,
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
