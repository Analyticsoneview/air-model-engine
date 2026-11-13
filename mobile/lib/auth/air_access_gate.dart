import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../services/air_api_client.dart';
import '../screens/air_server_setup_screen.dart';

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
                constraints: const BoxConstraints(maxWidth: 1040),
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
                    const Text('A clearer view of the markets. A more disciplined way to research.', style: TextStyle(color: Color(0xFFE5B85C), fontSize: 16, fontWeight: FontWeight.w700, height: 1.35)),
                    const SizedBox(height: 10),
                    const Text('Bring market context, options research and portfolio insight into one focused workspace. AIR presents research tools and evidence to support your decisions; it does not promise returns or remove investment risk.', style: TextStyle(color: Color(0xFFB6C2D2), height: 1.55, fontSize: 13)),
                    const SizedBox(height: 20),
                    Wrap(spacing: 10, runSpacing: 10, children: const [
                      _AirValuePill(icon: Icons.insights_rounded, title: 'Market intelligence'),
                      _AirValuePill(icon: Icons.radar_rounded, title: 'AIR QOC research'),
                      _AirValuePill(icon: Icons.query_stats_rounded, title: 'Portfolio insights'),
                    ]),
                    const SizedBox(height: 24),
                    LayoutBuilder(builder: (context, constraints) {
                      final wide = constraints.maxWidth > 680;
                      final form = _AirOnboardingPanel(
                        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                          const Text('GET STARTED', style: TextStyle(color: Color(0xFFE5B85C), fontSize: 10, fontWeight: FontWeight.w900, letterSpacing: 1.2)),
                          const SizedBox(height: 8),
                          const Text('Your AIR access', style: TextStyle(color: Colors.white, fontSize: 21, fontWeight: FontWeight.w800)),
                          const SizedBox(height: 8),
                          const Text('Use your international mobile number to request or restore access on this device.', style: TextStyle(color: Color(0xFFB6C2D2), fontSize: 12, height: 1.4)),
                          const SizedBox(height: 18),
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

class _AirValuePill extends StatelessWidget {
  const _AirValuePill({required this.icon, required this.title});
  final IconData icon;
  final String title;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
    decoration: BoxDecoration(color: const Color(0xFF1A2638), borderRadius: BorderRadius.circular(30), border: Border.all(color: const Color(0xFF344258))),
    child: Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(icon, size: 16, color: const Color(0xFFE5B85C)),
      const SizedBox(width: 7),
      Text(title, style: const TextStyle(color: Color(0xFFD8E0EA), fontSize: 11, fontWeight: FontWeight.w700)),
    ]),
  );
}

class _AirOnboardingPanel extends StatelessWidget {
  const _AirOnboardingPanel({required this.child});
  final Widget child;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(22),
    decoration: BoxDecoration(color: const Color(0xFF111C2C), borderRadius: BorderRadius.circular(22), border: Border.all(color: const Color(0xFF344258)), boxShadow: const [BoxShadow(color: Color(0x44000000), blurRadius: 28, offset: Offset(0, 12))]),
    child: child,
  );
}

class _AirJourneyPanel extends StatelessWidget {
  const _AirJourneyPanel();
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(22),
    decoration: BoxDecoration(color: const Color(0xFF111C2C).withValues(alpha: .72), borderRadius: BorderRadius.circular(22), border: Border.all(color: const Color(0xFF344258))),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: const [
      Text('RESEARCH WITH CONTEXT', style: TextStyle(color: Color(0xFFE5B85C), fontSize: 10, fontWeight: FontWeight.w900, letterSpacing: 1.2)),
      SizedBox(height: 10),
      Text('From market signals to informed decisions.', style: TextStyle(color: Colors.white, fontSize: 23, fontWeight: FontWeight.w800, height: 1.2)),
      SizedBox(height: 10),
      Text('A structured workspace for market monitoring, options research and portfolio review.', style: TextStyle(color: Color(0xFFB6C2D2), fontSize: 13, height: 1.5)),
      SizedBox(height: 22),
      _AirJourneyStep(number: '01', title: 'Request access', detail: 'Register this device with your international mobile number.'),
      SizedBox(height: 16),
      _AirJourneyStep(number: '02', title: 'AIR reviews your request', detail: 'Access remains pending until an AIR administrator approves it.'),
      SizedBox(height: 16),
      _AirJourneyStep(number: '03', title: 'Explore your workspace', detail: 'Your dashboard opens after approval. Strategy features depend on your assigned subscription.'),
      SizedBox(height: 20),
      Divider(color: Color(0xFF344258)),
      SizedBox(height: 12),
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(Icons.shield_outlined, color: Color(0xFFE5B85C), size: 18),
        SizedBox(width: 9),
        Expanded(child: Text('Access is approval-based. A mobile number identifies your request; phone ownership verification is not yet provided by this flow. Do not use it for payments or broker authorization until verification is added.', style: TextStyle(color: Color(0xFF9EADBF), fontSize: 11, height: 1.45))),
      ]),
      SizedBox(height: 10),
      Text('Market research is informational and does not guarantee investment outcomes.', style: TextStyle(color: Color(0xFF7E8CA0), fontSize: 10, height: 1.4)),
    ]),
  );
}

class _AirJourneyStep extends StatelessWidget {
  const _AirJourneyStep({required this.number, required this.title, required this.detail});
  final String number;
  final String title;
  final String detail;
  @override
  Widget build(BuildContext context) => Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
    Container(width: 34, height: 34, alignment: Alignment.center, decoration: BoxDecoration(color: const Color(0xFFE5B85C).withValues(alpha: .13), borderRadius: BorderRadius.circular(11)), child: Text(number, style: const TextStyle(color: Color(0xFFE5B85C), fontWeight: FontWeight.w900, fontSize: 11))),
    const SizedBox(width: 12),
    Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(title, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 13)),
      const SizedBox(height: 4),
      Text(detail, style: const TextStyle(color: Color(0xFF9EADBF), fontSize: 11, height: 1.4)),
    ])),
  ]);
}
