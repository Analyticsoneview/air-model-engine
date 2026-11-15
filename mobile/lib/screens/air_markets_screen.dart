import 'package:flutter/material.dart';

import '../services/air_api_client.dart';

class AirMarketsScreen extends StatefulWidget {
  const AirMarketsScreen({super.key});

  @override
  State<AirMarketsScreen> createState() => _AirMarketsScreenState();
}

class _AirMarketsScreenState extends State<AirMarketsScreen> {
  final AirApiClient _api = AirApiClient();
  final TextEditingController _search = TextEditingController();
  String _market = 'CM';
  bool _loading = true;
  String? _error;
  Map<String, dynamic> _status = {};
  Map<String, dynamic> _access = {};
  List<Map<String, dynamic>> _rows = [];
  DateTime? _lastLoaded;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _search.dispose();
    _api.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    if (mounted) setState(() { _loading = true; _error = null; });
    try {
      final results = await Future.wait([
        _api.nseDataStatus(),
        _api.customerMarketDataAccess(),
        _api.nseDataRows(market: _market, symbol: _search.text, limit: 150),
      ]);
      if (!mounted) return;
      final rows = (results[2]['rows'] as List<dynamic>? ?? const [])
          .whereType<Map<String, dynamic>>()
          .toList(growable: false);
      setState(() {
        _status = results[0];
        _access = results[1];
        _rows = rows;
        _lastLoaded = DateTime.now();
      });
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  String _number(dynamic value) {
    if (value == null) return '—';
    final number = value is num ? value : num.tryParse(value.toString());
    if (number == null) return value.toString();
    return number.toStringAsFixed(2);
  }

  String _date(dynamic value) {
    if (value == null) return '—';
    final raw = value.toString();
    return raw.length >= 10 ? raw.substring(0, 10) : raw;
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final bootstrap = _status['bootstrap'] as Map<String, dynamic>? ?? const {};
    final markets = _status['markets'] as Map<String, dynamic>? ?? const {};
    final source = _access['market_data_source'] as Map<String, dynamic>? ?? const {};
    final sourceLabel = _access['effective_source']?.toString() ?? 'NSE';
    final connection = _access['connection_status']?.toString() ?? 'unknown';
    final latestDate = _rows.isNotEmpty ? _date(_rows.first['trade_date']) : 'No imported session';

    return Scaffold(
      appBar: AppBar(
        title: const Text('MARKETS & OPTIONS'),
        actions: [
          IconButton(
            tooltip: 'Refresh market data',
            onPressed: _loading ? null : _load,
            icon: const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 28),
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    const Expanded(child: Text('DATA SOURCE & FRESHNESS', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w900, letterSpacing: .8))),
                    _StatusPill(label: sourceLabel, color: sourceLabel == 'BROKER' ? Colors.green : cs.primary),
                  ]),
                  const SizedBox(height: 10),
                  Text(source['connection_message']?.toString() ?? _access['note']?.toString() ?? 'Market-data source status is not available.',
                      style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant)),
                  const SizedBox(height: 8),
                  Wrap(spacing: 8, runSpacing: 6, children: [
                    _MetaPill(label: 'Connection: $connection'),
                    _MetaPill(label: 'NSE: ${bootstrap['status'] ?? 'UNKNOWN'}'),
                    _MetaPill(label: 'Session: $latestDate'),
                  ]),
                  if (_lastLoaded != null) ...[
                    const SizedBox(height: 8),
                    Text('Checked ${TimeOfDay.fromDateTime(_lastLoaded!).format(context)} · Official NSE bhavcopy is end-of-day data, not a live tick feed.',
                      style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
                  ],
                ]),
              ),
            ),
            const SizedBox(height: 12),
            Row(children: [
              Expanded(child: _MarketStatusCard(label: 'CASH MARKET', data: markets['CM'] as Map<String, dynamic>? ?? const {})),
              const SizedBox(width: 10),
              Expanded(child: _MarketStatusCard(label: 'F&O MARKET', data: markets['FO'] as Map<String, dynamic>? ?? const {})),
            ]),
            const SizedBox(height: 18),
            Row(children: [
              const Expanded(child: Text('NSE BHAVCOPY EXPLORER', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w900, letterSpacing: .7))),
              Text('${_rows.length} ROWS', style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
            ]),
            const SizedBox(height: 9),
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'CM', label: Text('Cash (CM)')),
                ButtonSegment(value: 'FO', label: Text('F&O (FO)')),
              ],
              selected: {_market},
              onSelectionChanged: (values) {
                setState(() => _market = values.first);
                _load();
              },
            ),
            const SizedBox(height: 9),
            TextField(
              controller: _search,
              textCapitalization: TextCapitalization.characters,
              decoration: InputDecoration(
                hintText: 'Search symbol (e.g. RELIANCE)',
                prefixIcon: const Icon(Icons.search_rounded),
                suffixIcon: IconButton(
                  tooltip: 'Clear search',
                  onPressed: () { _search.clear(); _load(); },
                  icon: const Icon(Icons.close_rounded),
                ),
                border: const OutlineInputBorder(),
              ),
              onSubmitted: (_) => _load(),
            ),
            const SizedBox(height: 10),
            if (_error != null)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Text('Market data could not be loaded: $_error', style: TextStyle(color: cs.error, fontSize: 12)),
                ),
              ),
            if (_loading && _rows.isEmpty)
              const Padding(padding: EdgeInsets.all(28), child: Center(child: CircularProgressIndicator())),
            if (!_loading && _rows.isEmpty && _error == null)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(18),
                  child: Column(children: [
                    const Icon(Icons.query_stats_rounded, size: 30),
                    const SizedBox(height: 8),
                    const Text('No imported rows for this filter', style: TextStyle(fontWeight: FontWeight.w800)),
                    const SizedBox(height: 5),
                    Text('The AIR server will show records after the NSE archive import completes. No prices are estimated or substituted.',
                      textAlign: TextAlign.center, style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant)),
                  ]),
                ),
              ),
            for (final row in _rows) _BhavcopyRow(row: row, market: _market, number: _number, date: _date),
            if (_rows.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text('Source: ${_market == 'CM' ? 'NSE official cash-market' : 'NSE official derivatives'} UDiFF bhavcopy · EOD records only.',
                  style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
              ),
          ],
        ),
      ),
    );
  }
}

class _MarketStatusCard extends StatelessWidget {
  const _MarketStatusCard({required this.label, required this.data});
  final String label;
  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Card(child: Padding(
      padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: TextStyle(fontSize: 9, fontWeight: FontWeight.w800, color: cs.onSurfaceVariant)),
        const SizedBox(height: 7),
        Text(data['status']?.toString() ?? 'UNKNOWN', style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w900)),
        const SizedBox(height: 3),
        Text('${data['sessions'] ?? 0} sessions · ${data['records'] ?? 0} records',
          style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
      ]),
    ));
  }
}

class _BhavcopyRow extends StatelessWidget {
  const _BhavcopyRow({required this.row, required this.market, required this.number, required this.date});
  final Map<String, dynamic> row;
  final String market;
  final String Function(dynamic) number;
  final String Function(dynamic) date;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final change = row['close'] is num && row['previous_close'] is num
        ? (row['close'] as num) - (row['previous_close'] as num)
        : null;
    final positive = change != null && change >= 0;
    return Card(
      margin: const EdgeInsets.only(bottom: 7),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 11),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(row['symbol']?.toString() ?? 'Unknown', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w900))),
            Text(number(row['close']), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w900)),
            if (change != null) ...[
              const SizedBox(width: 8),
              Text('${positive ? '+' : ''}${number(change)}',
                style: TextStyle(fontSize: 10, fontWeight: FontWeight.w800, color: positive ? Colors.green : cs.error)),
            ],
          ]),
          const SizedBox(height: 5),
          Wrap(spacing: 12, runSpacing: 4, children: [
            Text(date(row['trade_date']), style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
            if (market == 'FO') Text('${row['expiry'] ?? '—'} · ${row['strike'] ?? '—'} ${row['option_type'] ?? ''}',
              style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
            Text('Vol ${number(row['volume'])}', style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
            if (row['open_interest'] != null) Text('OI ${number(row['open_interest'])}', style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
          ]),
        ]),
      ),
    );
  }
}

class _StatusPill extends StatelessWidget {
  const _StatusPill({required this.label, required this.color});
  final String label;
  final Color color;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
    decoration: BoxDecoration(color: color.withValues(alpha: .13), borderRadius: BorderRadius.circular(20)),
    child: Text(label, style: TextStyle(fontSize: 9, fontWeight: FontWeight.w900, color: color)),
  );
}

class _MetaPill extends StatelessWidget {
  const _MetaPill({required this.label});
  final String label;
  @override
  Widget build(BuildContext context) => Chip(label: Text(label, style: const TextStyle(fontSize: 9)), visualDensity: VisualDensity.compact, padding: EdgeInsets.zero);
}
