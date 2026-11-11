import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../services/air_api_client.dart';

class AirServerSetupScreen extends StatefulWidget {
  const AirServerSetupScreen({super.key, required this.onConnected});

  final VoidCallback onConnected;

  @override
  State<AirServerSetupScreen> createState() => _AirServerSetupScreenState();
}

class _AirServerSetupScreenState extends State<AirServerSetupScreen> {
  static const _serverAddressKey = 'air_api_base_url';
  final _address = TextEditingController(text: AirApiClient.configuredBaseUrl ?? '');
  final _storage = FlutterSecureStorage();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _address.dispose();
    super.dispose();
  }

  String? _validateAddress(String value) {
    final uri = Uri.tryParse(value.trim());
    if (uri == null ||
        !uri.hasAuthority ||
        uri.host.isEmpty ||
        !{'http', 'https'}.contains(uri.scheme.toLowerCase()) ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment) {
      return 'Enter a valid http:// or https:// AIR server address.';
    }
    return null;
  }

  Future<void> _connect() async {
    final value = _address.text.trim();
    final validation = _validateAddress(value);
    if (validation != null) {
      setState(() => _error = validation);
      return;
    }

    final normalized = value.replaceFirst(RegExp(r'/+$'), '');
    setState(() {
      _busy = true;
      _error = null;
    });
    AirApiClient.configureBaseUrl(normalized);
    final api = AirApiClient();
    try {
      final health = await api.health();
      if (health['status'] != 'ok') {
        throw const AirApiException('The AIR server is reachable but not healthy.');
      }
      await _storage.write(key: _serverAddressKey, value: normalized);
      if (mounted) widget.onConnected();
    } catch (error) {
      AirApiClient.clearRuntimeBaseUrl();
      if (mounted) setState(() => _error = 'Could not connect to AIR: $error');
    } finally {
      api.dispose();
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: ListView(
              shrinkWrap: true,
              padding: const EdgeInsets.all(24),
              children: [
                Icon(Icons.hub_rounded, size: 54, color: theme.colorScheme.primary),
                const SizedBox(height: 18),
                const Text(
                  'CONNECT TO YOUR AIR SERVER',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 19, fontWeight: FontWeight.w900, letterSpacing: .5),
                ),
                const SizedBox(height: 10),
                Text(
                  'Enter the Windows PC address where AIR is running. Your phone and PC must be on the same trusted network.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: theme.colorScheme.onSurfaceVariant, height: 1.5),
                ),
                const SizedBox(height: 24),
                TextField(
                  controller: _address,
                  keyboardType: TextInputType.url,
                  autocorrect: false,
                  enableSuggestions: false,
                  decoration: const InputDecoration(
                    labelText: 'AIR API server address',
                    hintText: 'http://192.168.1.10:8000',
                    prefixIcon: Icon(Icons.dns_outlined),
                    border: OutlineInputBorder(),
                  ),
                  onSubmitted: (_) => _busy ? null : _connect(),
                ),
                const SizedBox(height: 10),
                Text(
                  'Do not enter localhost or 127.0.0.1 on your phone; those addresses point to the phone itself.',
                  style: TextStyle(fontSize: 12, color: theme.colorScheme.onSurfaceVariant, height: 1.4),
                ),
                const SizedBox(height: 8),
                Text(
                  'HTTP is intended for trusted-LAN lab testing only. Use HTTPS before exposing AIR beyond your private network.',
                  style: TextStyle(fontSize: 11, color: theme.colorScheme.onSurfaceVariant, height: 1.4),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 14),
                  Text(_error!, style: TextStyle(color: theme.colorScheme.error)),
                ],
                const SizedBox(height: 22),
                FilledButton.icon(
                  onPressed: _busy ? null : _connect,
                  icon: _busy
                      ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.link_rounded),
                  label: Text(_busy ? 'CHECKING SERVER…' : 'TEST AND SAVE SERVER'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
