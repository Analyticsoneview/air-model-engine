import 'package:flutter/material.dart';

import '../services/air_api_client.dart';
import 'nse_data_screen.dart';
import 'air_markets_screen.dart';

class AdminNseDataCenterScreen extends StatefulWidget {
  const AdminNseDataCenterScreen({
    super.key,
    required this.apiBase,
    required this.accessTokenProvider,
    required this.ensureAdminSession,
  });

  final String apiBase;
  final String? Function() accessTokenProvider;
  final Future<void> Function() ensureAdminSession;

  @override
  State<AdminNseDataCenterScreen> createState() => _AdminNseDataCenterScreenState();
}

class _AdminNseDataCenterScreenState extends State<AdminNseDataCenterScreen> {
  late final AirApiClient _api;
  Map<String, dynamic> _status = {};
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _api = AirApiClient(
      baseUrl: widget.apiBase,
      accessTokenProvider: widget.accessTokenProvider,
    );
    _load();
  }

  @override
  void dispose() {
    _api.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    if (mounted) setState(() { _loading = true; _error = null; });
    try {
      await widget.ensureAdminSession();
      final status = await _api.nseDataStatus();
      if (mounted) setState(() => _status = status);
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Widget _metric(String label, dynamic value) => SizedBox(
    width: 145,
    child: Card(child: Padding(
      padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w800)),
        const SizedBox(height: 6),
        Text('${value ?? '—'}', style: const TextStyle(fontSize: 21, fontWeight: FontWeight.w900)),
      ]),
    )),
  );

  @override
  Widget build(BuildContext context) {
    final bootstrap = _status['bootstrap'] as Map<String, dynamic>? ?? const {};
    final markets = _status['markets'] as Map<String, dynamic>? ?? const {};
    final cm = markets['CM'] as Map<String, dynamic>? ?? const {};
    final fo = markets['FO'] as Map<String, dynamic>? ?? const {};
    final cs = Theme.of(context).colorScheme;
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(padding: const EdgeInsets.all(16), children: [
        Row(children: [
          const Expanded(child: Text('NSE DATA CENTER', style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: .7))),
          IconButton(onPressed: _loading ? null : _load, icon: const Icon(Icons.refresh)),
        ]),
        const Text('Administrator workspace for official NSE archive health, historical coverage and market-data operations.'),
        const SizedBox(height: 12),
        if (_loading) const LinearProgressIndicator(),
        if (_error != null) Card(color: cs.errorContainer, child: Padding(
          padding: const EdgeInsets.all(12), child: Text(_error!))),
        Card(child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('ARCHIVE BOOTSTRAP · ${bootstrap['status'] ?? 'UNKNOWN'}',
              style: const TextStyle(fontWeight: FontWeight.w900)),
            const SizedBox(height: 6),
            Text(bootstrap['note']?.toString() ?? 'No bootstrap status has been reported.'),
            const SizedBox(height: 8),
            Text('Progress: ${bootstrap['progress_pct'] ?? 0}% · Paired sessions: ${bootstrap['paired_sessions'] ?? 0}'),
            if (bootstrap['updated_at'] != null)
              Text('Last updated: ${bootstrap['updated_at']}'),
          ]),
        )),
        const SizedBox(height: 8),
        Wrap(spacing: 8, runSpacing: 8, children: [
          _metric('CASH MARKET ROWS', cm['records']),
          _metric('F&O MARKET ROWS', fo['records']),
          _metric('CM SESSIONS', cm['sessions']),
          _metric('FO SESSIONS', fo['sessions']),
        ]),
        const SizedBox(height: 12),
        Card(child: ListTile(
          leading: const Icon(Icons.history),
          title: const Text('NSE HISTORICAL DATA'),
          subtitle: const Text('Explore CM and FO EOD rows, symbol filters, archive coverage and integrity results.'),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => NseDataScreen(
              apiBase: widget.apiBase,
              accessTokenProvider: widget.accessTokenProvider,
              ensureAdminSession: widget.ensureAdminSession,
            ),
          )),
        )),
        Card(child: ListTile(
          leading: const Icon(Icons.candlestick_chart),
          title: const Text('MARKETS & OPTIONS'),
          subtitle: const Text('Review market-data source status and browse persisted NSE cash and F&O records.'),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => AirMarketsScreen(
              apiBase: widget.apiBase,
              accessTokenProvider: widget.accessTokenProvider,
              ensureAdminSession: widget.ensureAdminSession,
              adminMode: true,
            ),
          )),
        )),
        const SizedBox(height: 8),
        const Text('NSE UDiFF bhavcopy is end-of-day archive data. It is not a live tick feed or an intraday option-chain snapshot.',
          style: TextStyle(fontSize: 11)),
      ]),
    );
  }
}
