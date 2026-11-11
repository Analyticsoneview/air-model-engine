import 'package:flutter/material.dart';

import '../services/air_api_client.dart';

class AirSubscriptionScreen extends StatefulWidget {
  const AirSubscriptionScreen({super.key});
  @override
  State<AirSubscriptionScreen> createState() => _AirSubscriptionScreenState();
}

class _AirSubscriptionScreenState extends State<AirSubscriptionScreen> {
  final AirApiClient _api = AirApiClient();
  List<Map<String, dynamic>> _plans = [];
  Map<String, dynamic>? _subscription;
  bool _loading = true;
  String? _error;

  @override
  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      final values = await Future.wait([_api.subscriptionPlans(), _api.mySubscription()]);
      if (!mounted) return;
      final status = values[1] as Map<String, dynamic>;
      setState(() {
        _plans = values[0] as List<Map<String, dynamic>>;
        _subscription = status['subscription'] as Map<String, dynamic>?;
      });
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally { if (mounted) setState(() => _loading = false); }
  }

  @override
  void dispose() { _api.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final active = _subscription?['status'] == 'ACTIVE';
    return Scaffold(
      appBar: AppBar(title: const Text('AIR SUBSCRIPTION'), actions: [
        IconButton(onPressed: _loading ? null : _load, icon: const Icon(Icons.refresh_rounded)),
      ]),
      body: _loading ? const Center(child: CircularProgressIndicator()) : ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(
            crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(active ? 'ACTIVE PLAN' : 'DASHBOARD ACCESS ACTIVE',
                style: TextStyle(fontSize: 11, fontWeight: FontWeight.w900, color: theme.colorScheme.primary)),
              const SizedBox(height: 8),
              Text(active ? (_subscription?['plan_code']?.toString() ?? 'AIR PLAN') : 'No active strategy subscription',
                style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
              const SizedBox(height: 6),
              Text(active
                ? 'Valid until ${_subscription?['expires_at'] ?? '—'}'
                : 'Your AIR dashboard remains available. Activate a plan to unlock strategy workspaces.',
                style: TextStyle(fontSize: 12, color: theme.colorScheme.onSurfaceVariant)),
            ],
          ))),
          const SizedBox(height: 18),
          const Text('CHOOSE YOUR PLAN', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w900, letterSpacing: .8)),
          const SizedBox(height: 8),
          ..._plans.map((plan) => Card(
            child: ListTile(
              leading: Icon(Icons.workspace_premium_outlined, color: theme.colorScheme.primary),
              title: Text(plan['name']?.toString() ?? 'AIR Plan', style: const TextStyle(fontWeight: FontWeight.w800)),
              subtitle: Text('${plan['validity_days']} days · Strategy access during active validity'),
              trailing: const Icon(Icons.lock_clock_outlined),
            ),
          )),
          const SizedBox(height: 12),
          Card(color: theme.colorScheme.surfaceContainerHighest, child: const Padding(
            padding: EdgeInsets.all(14),
            child: Text('Initial rollout: plan activation is handled by AIR administration. Online payments and automatic renewals are not enabled yet. Published pricing will be added before customer payments go live.',
              style: TextStyle(fontSize: 12, height: 1.45)),
          )),
          if (_error != null) Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Text(_error!, style: TextStyle(color: theme.colorScheme.error)),
          ),
        ],
      ),
    );
  }
}