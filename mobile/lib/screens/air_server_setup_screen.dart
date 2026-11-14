import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../services/air_api_client.dart';

enum _AirEnvironment { local, staging, production, custom }

class AirServerSetupScreen extends StatefulWidget {
  const AirServerSetupScreen({super.key, required this.onConnected});
  final VoidCallback onConnected;

  @override
  State<AirServerSetupScreen> createState() => _AirServerSetupScreenState();
}

class _AirServerSetupScreenState extends State<AirServerSetupScreen> {
  static const _serverAddressKey = 'air_api_base_url';
  static const _environmentKey = 'air_api_environment';
  final _address = TextEditingController();
  final _storage = const FlutterSecureStorage();
  _AirEnvironment _environment = _AirEnvironment.local;
  bool _busy = false;
  String? _error;

  String get _localDefault => kIsWeb ? 'http://localhost:8000' : '';
  String get _environmentLabel => switch (_environment) {
    _AirEnvironment.local => 'LOCAL DEVELOPMENT',
    _AirEnvironment.staging => 'STAGING',
    _AirEnvironment.production => 'AWS / PRODUCTION',
    _AirEnvironment.custom => 'CUSTOM SERVER',
  };

  @override
  void initState() {
    super.initState();
    _restoreSavedServer();
  }

  Future<void> _restoreSavedServer() async {
    try {
      final saved = await _storage.read(key: _serverAddressKey);
      final profile = await _storage.read(key: _environmentKey);
      if (!mounted) return;
      if (saved != null && saved.isNotEmpty) _address.text = saved;
      if (profile != null) {
        _environment = _AirEnvironment.values.firstWhere((e) => e.name == profile, orElse: () => _AirEnvironment.custom);
      }
      if (_address.text.isEmpty) _address.text = _localDefault;
      setState(() {});
    } catch (_) {
      if (_address.text.isEmpty) _address.text = _localDefault;
    }
  }

  @override
  void dispose() {
    _address.dispose();
    super.dispose();
  }

  void _selectEnvironment(_AirEnvironment value) {
    setState(() {
      _environment = value;
      _error = null;
      switch (value) {
        case _AirEnvironment.local:
          _address.text = _localDefault;
        case _AirEnvironment.staging:
        case _AirEnvironment.production:
        case _AirEnvironment.custom:
          _address.text = '';
      }
    });
  }

  String? _validateAddress(String value) {
    final uri = Uri.tryParse(value.trim());
    if (uri == null || !uri.hasAuthority || uri.host.isEmpty ||
        !{'http', 'https'}.contains(uri.scheme.toLowerCase()) ||
        uri.userInfo.isNotEmpty || uri.hasQuery || uri.hasFragment) {
      return 'Enter a valid AIR server URL, including http:// or https://.';
    }
    final loopback = {'localhost', '127.0.0.1', '::1'}.contains(uri.host.toLowerCase());
    if (!kIsWeb && loopback) {
      return 'On a phone, use your Windows PC LAN IP or a public HTTPS domain. Localhost points to the phone.';
    }
    if (_environment != _AirEnvironment.local && uri.scheme != 'https') {
      return 'Staging and production connections must use HTTPS.';
    }
    if (_environment == _AirEnvironment.local && !kIsWeb && uri.scheme != 'https') {
      final host = uri.host;
      final segments = host.split('.');
      final secondOctet = segments.length > 1 ? int.tryParse(segments[1]) : null;
      final privateLan = host.startsWith('192.168.') || host.startsWith('10.') ||
          (host.startsWith('172.') && secondOctet != null && secondOctet >= 16 && secondOctet <= 31);
      if (!privateLan) return 'For local HTTP, use a trusted private-LAN address. Use HTTPS for remote servers.';
    }
    return null;
  }

  Future<void> _connect() async {
    if (_busy) return;
    final value = _address.text.trim();
    final validation = _validateAddress(value);
    if (validation != null) {
      setState(() => _error = validation);
      return;
    }
    final normalized = value.replaceFirst(RegExp(r'/+$'), '');
    setState(() { _busy = true; _error = null; });
    AirApiClient? api;
    try {
      AirApiClient.setAccessToken(null);
      await _storage.delete(key: 'air_access_token');
      AirApiClient.configureBaseUrl(normalized);
      api = AirApiClient();
      final health = await api.health();
      if (health['status'] != 'ok') {
        throw const AirApiException('The AIR API responded but is not healthy.');
      }
      await _storage.write(key: _serverAddressKey, value: normalized);
      await _storage.write(key: _environmentKey, value: _environment.name);
      if (mounted) widget.onConnected();
    } catch (error) {
      AirApiClient.clearRuntimeBaseUrl();
      if (mounted) setState(() => _error = 'Connection failed: $error');
    } finally {
      api?.dispose();
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _environmentCard(_AirEnvironment value, String title, String detail, IconData icon) {
    final selected = _environment == value;
    final colors = Theme.of(context).colorScheme;
    return InkWell(
      borderRadius: BorderRadius.circular(14),
      onTap: _busy ? null : () => _selectEnvironment(value),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 180),
        padding: const EdgeInsets.all(13),
        decoration: BoxDecoration(
          color: selected ? colors.primary.withValues(alpha: .12) : colors.surface,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: selected ? colors.primary : colors.outlineVariant, width: selected ? 1.5 : 1),
        ),
        child: Row(children: [
          Icon(icon, color: selected ? colors.primary : colors.onSurfaceVariant, size: 22),
          const SizedBox(width: 11),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: const TextStyle(fontWeight: FontWeight.w800)),
            const SizedBox(height: 3),
            Text(detail, style: TextStyle(fontSize: 11, color: colors.onSurfaceVariant)),
          ])),
          if (selected) Icon(Icons.check_circle_rounded, color: colors.primary, size: 19),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 760),
            child: ListView(
              shrinkWrap: true,
              padding: const EdgeInsets.fromLTRB(22, 28, 22, 32),
              children: [
                Row(children: [
                  Container(width: 46, height: 46,
                    decoration: BoxDecoration(color: colors.primary.withValues(alpha: .14), borderRadius: BorderRadius.circular(14)),
                    child: Icon(Icons.hub_rounded, color: colors.primary, size: 26)),
                  const SizedBox(width: 12),
                  const Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('AIR', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900, letterSpacing: 1.4)),
                    Text('Analytical Investment Research', style: TextStyle(fontSize: 11)),
                  ])),
                  const Chip(label: Text('SERVER SETUP', style: TextStyle(fontSize: 10, fontWeight: FontWeight.w800))),
                ]),
                const SizedBox(height: 30),
                Text('Connect to your AIR server', style: theme.textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w900)),
                const SizedBox(height: 7),
                Text('Choose where AIR is running. Move from local development to private staging and AWS without changing the app.', style: TextStyle(color: colors.onSurfaceVariant, height: 1.5)),
                const SizedBox(height: 22),
                Card(child: Padding(padding: const EdgeInsets.all(17), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Text('DEPLOYMENT ENVIRONMENT', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w900, letterSpacing: .9)),
                  const SizedBox(height: 12),
                  _environmentCard(_AirEnvironment.local, 'Local development', 'This computer or trusted LAN', Icons.laptop_mac_rounded),
                  const SizedBox(height: 9),
                  _environmentCard(_AirEnvironment.staging, 'Staging environment', 'Pre-release testing over HTTPS', Icons.science_outlined),
                  const SizedBox(height: 9),
                  _environmentCard(_AirEnvironment.production, 'AWS production', 'Customer-facing production endpoint', Icons.cloud_outlined),
                  const SizedBox(height: 9),
                  _environmentCard(_AirEnvironment.custom, 'Custom server', 'Another approved AIR server', Icons.dns_outlined),
                  const SizedBox(height: 20),
                  Text('$_environmentLabel · API ADDRESS', style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w900, letterSpacing: .7)),
                  const SizedBox(height: 8),
                  TextField(controller: _address, keyboardType: TextInputType.url, autocorrect: false, enableSuggestions: false,
                    decoration: InputDecoration(hintText: kIsWeb ? 'http://localhost:8000' : 'https://api.your-domain.com',
                      prefixIcon: const Icon(Icons.link_rounded), border: const OutlineInputBorder()),
                    onChanged: (_) { if (_error != null) setState(() => _error = null); },
                    onSubmitted: (_) => _connect()),
                  const SizedBox(height: 8),
                  Text(kIsWeb
                    ? 'For this browser on your AIR PC, localhost:8000 is valid. For a phone, enter the PC LAN address instead.'
                    : 'On Android, localhost refers to the phone. Use your PC LAN IP for local testing or HTTPS for remote environments.',
                    style: TextStyle(fontSize: 11, color: colors.onSurfaceVariant, height: 1.45)),
                  if (_environment == _AirEnvironment.production || _environment == _AirEnvironment.staging) ...[
                    const SizedBox(height: 10),
                    Row(children: [
                      Icon(Icons.verified_user_outlined, color: colors.primary, size: 17),
                      const SizedBox(width: 7),
                      Expanded(child: Text('HTTPS is mandatory. Production secrets are never stored in this screen.', style: TextStyle(fontSize: 11, color: colors.onSurfaceVariant))),
                    ]),
                  ],
                  if (_error != null) ...[
                    const SizedBox(height: 13),
                    Container(padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(color: colors.errorContainer, borderRadius: BorderRadius.circular(10)),
                      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Icon(Icons.error_outline, color: colors.error, size: 19), const SizedBox(width: 8),
                        Expanded(child: Text(_error!, style: TextStyle(color: colors.onErrorContainer, fontSize: 12))),
                      ])),
                  ],
                  const SizedBox(height: 18),
                  SizedBox(width: double.infinity, child: FilledButton.icon(
                    onPressed: _busy ? null : _connect,
                    icon: _busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.link_rounded),
                    label: Text(_busy ? 'CHECKING SERVER…' : 'TEST CONNECTION & CONTINUE'))),
                ]))),
                const SizedBox(height: 14),
                Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Icon(Icons.shield_outlined, size: 17, color: colors.onSurfaceVariant), const SizedBox(width: 8),
                  Expanded(child: Text('AIR checks server health before saving. Switching servers clears the active access token so credentials are not sent to another environment.', style: TextStyle(fontSize: 11, color: colors.onSurfaceVariant, height: 1.45))),
                ]),
                const SizedBox(height: 20),
                Center(child: Text('INTELLIGENCE. PRECISION. CONTROL.', style: TextStyle(fontSize: 10, letterSpacing: 1.4, fontWeight: FontWeight.w800, color: colors.onSurfaceVariant))),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
