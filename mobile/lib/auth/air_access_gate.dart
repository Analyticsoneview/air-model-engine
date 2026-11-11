import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../services/air_api_client.dart';
import '../screens/air_server_setup_screen.dart';
import '../screens/air_admin_console_screen.dart';

class AirAccessGate extends StatefulWidget {
  const AirAccessGate({super.key, required this.builder});
  final WidgetBuilder builder;

  @override
  State<AirAccessGate> createState() => _AirAccessGateState();
}

class _AirAccessGateState extends State<AirAccessGate> {
  static const _storage = FlutterSecureStorage();
  late AirApiClient _api;
  final _mobile = TextEditingController();
  String? _deviceId;
  String _status = 'NEW';
  String _message = 'Enter your international mobile number to open your AIR dashboard. Strategy access is activated separately through a subscription plan.';
  bool _busy = true;
  bool _approved = false;

  @override
  void initState() {
    super.initState();
    _api = AirApiClient();
    _restoreSession();
  }

  Future<void> _changeServer() async {
    await Navigator.of(context).push(MaterialPageRoute<void>(
      builder: (setupContext) => AirServerSetupScreen(
        onConnected: () => Navigator.of(setupContext).pop(),
      ),
    ));
    if (!mounted) return;
    // A bearer token belongs to the previous server; never forward it to a newly selected host.
    AirApiClient.setAccessToken(null);
    await _storage.delete(key: 'air_access_token');
    _api.dispose();
    _api = AirApiClient();
    setState(() {
      _busy = true;
      _approved = false;
      _status = 'NEW';
    });
    await _restoreSession();
  }

  Future<void> _restoreSession() async {
    try {
      final token = await _storage.read(key: 'air_access_token');
      final savedMobile = await _storage.read(key: 'air_mobile_e164');
      var deviceId = await _storage.read(key: 'air_device_id');
      if (deviceId == null || deviceId.length < 16) {
        final random = Random.secure();
        deviceId = List<int>.generate(32, (_) => random.nextInt(16))
            .map((v) => v.toRadixString(16)).join();
        await _storage.write(key: 'air_device_id', value: deviceId);
      }
      _deviceId = deviceId;
      if (savedMobile != null) {
        _mobile.text = savedMobile;
        if (token == null || token.isEmpty) {
          final savedStatus = await _api.mobileStatus(savedMobile, deviceId);
          _status = savedStatus['status']?.toString() ?? 'NEW';
          if (_status == 'PENDING') _message = 'Your earlier access request is pending. Contact AIR support to migrate this device to the new customer access flow.';
        }
      }
      if (token != null && token.isNotEmpty) {
        AirApiClient.setAccessToken(token);
        try {
          await _api.me();
          _approved = true;
        } on AirApiException {
          AirApiClient.setAccessToken(null);
          await _storage.delete(key: 'air_access_token');
          _message = 'Your saved access is no longer active. Check your approval status.';
        }
      }
    } catch (_) {
      _message = 'Unable to restore your AIR session. Please try again.';
    }
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _requestOrCheck({bool checkOnly = false}) async {
    final mobile = _mobile.text.trim();
    if (!RegExp(r'^\+[1-9][0-9]{7,14}$').hasMatch(mobile)) {
      setState(() {
        _status = 'INVALID';
        _message = 'Enter a valid international number, including + and country code (example: +14155550123).';
      });
      return;
    }
    if (_deviceId == null) return;
    setState(() => _busy = true);
    try {
      final result = checkOnly
          ? await _api.mobileStatus(mobile, _deviceId!)
          : await _api.mobileLogin(mobile, _deviceId!);
      var status = result['status']?.toString() ?? 'UNKNOWN';
      if (status == 'APPROVED' && result['access_token'] == null) {
        final login = await _api.mobileLogin(mobile, _deviceId!);
        status = login['status']?.toString() ?? status;
        if (login['access_token'] is String) {
          await _storage.write(key: 'air_access_token', value: login['access_token'] as String);
          await _storage.write(key: 'air_mobile_e164', value: mobile);
          _approved = true;
        }
      } else if (status == 'APPROVED' && result['access_token'] is String) {
        await _storage.write(key: 'air_access_token', value: result['access_token'] as String);
        await _storage.write(key: 'air_mobile_e164', value: mobile);
        _approved = true;
      }
      if (status == 'PENDING') {
        _message = 'This device has an older pending access request. Contact AIR support to activate the new customer onboarding.';
      } else if (status == 'APPROVED' && _approved) {
        _message = 'Your AIR dashboard is ready. Choose a subscription to unlock strategies.';
      } else if (status == 'REJECTED') {
        _message = 'This AIR access request was not approved. Please contact the AIR administrator.';
      } else if (status == 'BLOCKED') {
        _message = 'This device has been blocked from AIR. Please contact the AIR administrator.';
      } else if (status == 'NOT_SUBMITTED') {
        _message = 'No request found for this device. Submit your access request first.';
      }
      setState(() => _status = status);
    } on AirApiException catch (error) {
      setState(() {
        _status = 'ERROR';
        _message = error.message;
      });
    } catch (_) {
      setState(() {
        _status = 'ERROR';
        _message = 'Could not connect to AIR. Check your connection and try again.';
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _mobile.dispose();
    _api.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_approved) return widget.builder(context);
    final pending = _status == 'PENDING';
    final approvedStatus = _status == 'APPROVED';
    final denied = _status == 'REJECTED' || _status == 'BLOCKED';
    return Scaffold(
      body: Container(
        width: double.infinity,
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xFF080D16), Color(0xFF111D30), Color(0xFF080D16)],
          ),
        ),
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 440),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Container(
                      width: 66, height: 66,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                        color: const Color(0xFFE5B85C).withValues(alpha: .12),
                        borderRadius: BorderRadius.circular(20),
                        border: Border.all(color: const Color(0xFFE5B85C).withValues(alpha: .5)),
                      ),
                      child: const Text('AIR', style: TextStyle(color: Color(0xFFE5B85C), fontSize: 23, fontWeight: FontWeight.w900, letterSpacing: 2)),
                    ),
                    const SizedBox(height: 24),
                    const Text('ANALYTICAL INVESTMENT RESEARCH', style: TextStyle(color: Color(0xFFE5B85C), fontSize: 10, fontWeight: FontWeight.w800, letterSpacing: 1.4)),
                    const SizedBox(height: 8),
                    const Text('Your market intelligence workspace.', style: TextStyle(color: Colors.white, fontSize: 25, fontWeight: FontWeight.w800)),
                    const SizedBox(height: 10),
                    const Text('Enter your international mobile number to access your AIR dashboard. Choose a subscription later to unlock strategy workspaces.', style: TextStyle(color: Color(0xFFB6C2D2), height: 1.5, fontSize: 13)),
                    const SizedBox(height: 26),
                    TextField(
                      controller: _mobile,
                      enabled: !_busy && !denied,
                      keyboardType: TextInputType.phone,
                      style: const TextStyle(color: Colors.white, fontSize: 16),
                      decoration: InputDecoration(
                        labelText: 'International mobile number',
                        hintText: '+14155550123',
                        hintStyle: const TextStyle(color: Color(0xFF7E8CA0)),
                        labelStyle: const TextStyle(color: Color(0xFFB6C2D2)),
                        prefixIcon: const Icon(Icons.public_rounded, color: Color(0xFFE5B85C)),
                        filled: true,
                        fillColor: const Color(0xFF1A2638),
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide.none),
                      ),
                    ),
                    const SizedBox(height: 16),
                    if (!pending && !approvedStatus)
                      FilledButton(
                        onPressed: _busy || denied ? null : () => _requestOrCheck(),
                        style: FilledButton.styleFrom(
                          backgroundColor: const Color(0xFFE5B85C),
                          foregroundColor: const Color(0xFF111827),
                          padding: const EdgeInsets.symmetric(vertical: 16),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                        ),
                        child: _busy ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Text('CONTINUE TO AIR', style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: .7)),
                      ),
                    if (pending || approvedStatus)
                      OutlinedButton.icon(
                        onPressed: _busy ? null : () => _requestOrCheck(checkOnly: true),
                        icon: const Icon(Icons.refresh_rounded),
                        label: const Text('CHECK APPROVAL STATUS'),
                        style: OutlinedButton.styleFrom(foregroundColor: const Color(0xFFE5B85C), padding: const EdgeInsets.symmetric(vertical: 15), side: const BorderSide(color: Color(0x66E5B85C))),
                      ),
                    if (pending || approvedStatus || denied || _status == 'ERROR' || _status == 'INVALID')
                      Container(
                        margin: const EdgeInsets.only(top: 20),
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: (pending ? const Color(0xFFB9852C) : denied ? const Color(0xFF8F3434) : const Color(0xFF247B5B)).withValues(alpha: .14),
                          borderRadius: BorderRadius.circular(14),
                          border: Border.all(color: (pending ? const Color(0xFFE5B85C) : denied ? const Color(0xFFE16C6C) : const Color(0xFF45C994)).withValues(alpha: .45)),
                        ),
                        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Icon(pending ? Icons.hourglass_top_rounded : denied ? Icons.lock_outline_rounded : Icons.info_outline_rounded, color: pending ? const Color(0xFFE5B85C) : denied ? const Color(0xFFE16C6C) : const Color(0xFF45C994)),
                          const SizedBox(width: 12),
                          Expanded(child: Text(_message, style: const TextStyle(color: Colors.white, height: 1.45, fontSize: 12))),
                        ]),
                      ),
                    const SizedBox(height: 18),
                    TextButton.icon(
                      onPressed: _busy ? null : _changeServer,
                      icon: const Icon(Icons.dns_outlined, color: Color(0xFFE5B85C)),
                      label: const Text('CHANGE AIR SERVER', style: TextStyle(color: Color(0xFFE5B85C), fontWeight: FontWeight.w800)),
                    ),
                    TextButton.icon(
                      onPressed: _busy ? null : () => Navigator.of(context).push(
                        MaterialPageRoute<void>(builder: (_) => const AirAdminConsoleScreen()),
                      ),
                      icon: const Icon(Icons.admin_panel_settings_outlined, color: Color(0xFFE5B85C)),
                      label: const Text('ADMINISTRATOR SIGN IN', style: TextStyle(color: Color(0xFFE5B85C), fontWeight: FontWeight.w800)),
                    ),
                    const SizedBox(height: 14),
                    const SizedBox(height: 10),
                    const Text('DASHBOARD ACCESS  •  SUBSCRIPTION-BASED STRATEGIES', textAlign: TextAlign.center, style: TextStyle(color: Color(0xFF7E8CA0), fontSize: 9, letterSpacing: 1, fontWeight: FontWeight.w700)),
                    const SizedBox(height: 8),
                    const Text('Phone number identifies your customer profile. Verify ownership before enabling payments, broker credentials or trading permissions.', textAlign: TextAlign.center, style: TextStyle(color: Color(0xFF7E8CA0), fontSize: 10)),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
