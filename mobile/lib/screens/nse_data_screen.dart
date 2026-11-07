import 'dart:async';

import 'package:flutter/material.dart';

import '../services/air_api_client.dart';

class NseDataScreen extends StatefulWidget {
  const NseDataScreen({super.key});

  @override
  State<NseDataScreen> createState() => _NseDataScreenState();
}

class _NseDataScreenState extends State<NseDataScreen> {
  final AirApiClient _api = AirApiClient();
  final TextEditingController _search = TextEditingController();
  Timer? _poller;
  Map<String, dynamic> _status = {};
  List<Map<String, dynamic>> _rows = [];
  String _market = 'CM';
  String _instrumentFilter = '';
  bool _loading = false;
  bool _statusLoading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
    _poller = Timer.periodic(const Duration(seconds: 15), (_) => _refreshStatus());
  }

  @override
  void dispose() {
    _poller?.cancel();
    _search.dispose();
    _api.dispose();
    super.dispose();
  }

  int _recordsFor(String market) {
    final markets = _status['markets'] as Map<String, dynamic>? ?? const {};
    final row = markets[market] as Map<String, dynamic>? ?? const {};
    return (row['records'] as num?)?.toInt() ?? 0;
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final status = await _api.nseDataStatus();
      final data = await _api.nseDataRows(
        market: _market,
        symbol: _search.text,
        instrumentType: _instrumentFilter.isEmpty ? null : _instrumentFilter,
        limit: 150,
      );
      if (!mounted) return;
      setState(() {
        _status = status;
        _rows = (data['rows'] as List<dynamic>? ?? const [])
            .whereType<Map<String, dynamic>>().toList();
      });
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _refreshStatus() async {
    if (_statusLoading) return;
    _statusLoading = true;
    try {
      final status = await _api.nseDataStatus();
      if (!mounted) return;
      final oldCount = _recordsFor(_market);
      final oldBootstrap = _status['bootstrap'] as Map<String, dynamic>? ?? const {};
      final newBootstrap = status['bootstrap'] as Map<String, dynamic>? ?? const {};
      final oldRunStamp = oldBootstrap['updated_at']?.toString();
      final newRunStamp = newBootstrap['updated_at']?.toString();
      setState(() => _status = status);
      // Reload the visible rows whenever a reconciliation/download batch changes,
      // even when the total row count happens to remain unchanged.
      if (_recordsFor(_market) != oldCount || oldRunStamp != newRunStamp) {
        await _loadRows();
      }
    } catch (_) {
      // Keep the last known status visible during temporary network interruptions.
    } finally {
      _statusLoading = false;
    }
  }

  Future<void> _loadRows() async {
    try {
      final data = await _api.nseDataRows(
        market: _market,
        symbol: _search.text,
        instrumentType: _instrumentFilter.isEmpty ? null : _instrumentFilter,
        limit: 150,
      );
      if (mounted) {
        setState(() => _rows = (data['rows'] as List<dynamic>? ?? const [])
            .whereType<Map<String, dynamic>>().toList());
      }
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    }
  }

  Future<void> _requestBootstrap() async {
    try {
      final result = await _api.triggerNseBootstrap();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(result['message']?.toString() ?? 'NSE bootstrap requested')),
      );
      await _refreshStatus();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Bootstrap request failed: $error')),
        );
      }
    }
  }

  String _number(dynamic value, {int decimals = 2}) {
    if (value == null) return '—';
    final number = (value as num).toDouble();
    if (number.abs() >= 10000000) return '${(number / 10000000).toStringAsFixed(2)} Cr';
    if (number.abs() >= 100000) return '${(number / 100000).toStringAsFixed(2)} L';
    if (number.abs() >= 1000 && decimals == 0) return number.toStringAsFixed(0);
    return number.toStringAsFixed(decimals).replaceFirst(RegExp(r"\.?0+$"), "");
  }

  String _date(dynamic value) {
    if (value == null) return '';
    final text = value.toString();
    return text.length >= 10 ? text.substring(0, 10) : text;
  }

  List<Map<String, dynamic>> _upcomingHolidays() {
    final calendar = _status['trading_calendar'] as Map<String, dynamic>? ?? const {};
    final segments = calendar['segments'] as Map<String, dynamic>? ?? const {};
    final cm = segments['CM'] as List<dynamic>? ?? const [];
    final today = DateTime.now();
    final rows = cm.whereType<Map<String, dynamic>>().where((item) {
      final parsed = DateTime.tryParse(item['date']?.toString() ?? '');
      return parsed != null && !parsed.isBefore(DateTime(today.year, today.month, today.day));
    }).toList();
    rows.sort((a, b) => (a['date'] ?? '').toString().compareTo((b['date'] ?? '').toString()));
    return rows.take(5).toList();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final bootstrap = _status['bootstrap'] as Map<String, dynamic>? ?? const {};
    final bootstrapState = bootstrap['status']?.toString() ?? 'NOT_STARTED';
    final ready = bootstrapState == 'READY';
    final progress = ((bootstrap['progress_pct'] as num?)?.toDouble() ?? 0) / 100;
    final cmRecords = _recordsFor('CM');
    final foRecords = _recordsFor('FO');
    final marketStats = (_status['markets'] as Map<String, dynamic>? ?? const {})[_market]
        as Map<String, dynamic>? ?? const {};

    return Scaffold(
      appBar: AppBar(
        title: const Text('NSE HISTORICAL DATA'),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            onPressed: _loading ? null : _load,
            icon: const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(14, 8, 14, 24),
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(15),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(children: [
                      Icon(Icons.cloud_download_outlined, color: cs.primary),
                      const SizedBox(width: 8),
                      const Expanded(child: Text('INITIAL DATA BOOTSTRAP',
                          style: TextStyle(fontSize: 11, fontWeight: FontWeight.w900, letterSpacing: .7))),
                      Text(ready ? 'READY' : bootstrapState,
                          style: TextStyle(fontSize: 9, fontWeight: FontWeight.w900,
                              color: ready ? Colors.green : cs.primary)),
                    ]),
                    const SizedBox(height: 9),
                    Text(
                      bootstrap['note']?.toString() ??
                          'The AIR server downloads three calendar months of NSE CM and F&O closing bhavcopy archives on first deployment.',
                      style: TextStyle(fontSize: 11, height: 1.4, color: cs.onSurfaceVariant),
                    ),
                    if (bootstrapState == 'RUNNING') ...[
                      const SizedBox(height: 10),
                      LinearProgressIndicator(value: progress > 0 ? progress : null),
                      const SizedBox(height: 5),
                      Text('${(progress * 100).toStringAsFixed(1)}% · ${bootstrap['completed_files'] ?? 0} / ${(bootstrap['weekdays_to_check'] as num? ?? 0).toInt() * 2} files',
                          style: TextStyle(fontSize: 9, color: cs.onSurfaceVariant)),
                    ],
                    const SizedBox(height: 10),
                    Wrap(spacing: 8, runSpacing: 6, children: [
                      _CoverageChip(label: 'CM', value: '${_number(cmRecords, decimals: 0)} rows', color: cs.primary),
                      _CoverageChip(label: 'FO', value: '${_number(foRecords, decimals: 0)} rows', color: cs.tertiary),
                      _CoverageChip(label: 'PAIRED SESSIONS', value: '${bootstrap['paired_sessions'] ?? 0}', color: cs.secondary),
                      if ((bootstrap['partial_sessions_found'] as num? ?? 0) > 0)
                        _CoverageChip(label: 'PARTIAL FOUND', value: '${bootstrap['partial_sessions_found']}', color: cs.error),
                      if ((bootstrap['repaired_sessions'] as num? ?? 0) > 0)
                        _CoverageChip(label: 'AUTO-REPAIRED', value: '${bootstrap['repaired_sessions']}', color: Colors.green),
                    ]),
                    if (bootstrap['strategy_run'] is Map) ...[
                      const SizedBox(height: 7),
                      Builder(builder: (context) {
                        final run = bootstrap['strategy_run'] as Map<String, dynamic>;
                        final results = run['results'] as List<dynamic>? ?? const [];
                        final replayed = results.fold<int>(0, (sum, item) {
                          final row = item as Map<String, dynamic>;
                          return sum + ((row['EXPIRY78'] as Map?)?['contracts_replayed'] as num? ?? 0).toInt()
                              + ((row['RECOVERED'] as Map?)?['contracts_replayed'] as num? ?? 0).toInt();
                        });
                        return Text(
                          'Post-market strategy replay: ${run['status'] ?? 'UNKNOWN'} • ${run['customers'] ?? 0} customers • $replayed contracts replayed',
                          style: TextStyle(fontSize: 9, fontWeight: FontWeight.w800,
                            color: run['status'] == 'COMPLETED' ? Colors.green : cs.error),
                        );
                      }),
                    ],
                    if (_status['expired_fo_cleanup'] is Map) ...[
                      const SizedBox(height: 7),
                      Builder(builder: (context) {
                        final cleanup = _status['expired_fo_cleanup'] as Map<String, dynamic>;
                        final snapshot = cleanup['strategy_snapshot'] as Map<String, dynamic>? ?? const {};
                        return Text(
                          'FO expiry cleanup: ${cleanup['status'] ?? 'UNKNOWN'} • ${cleanup['removed_records'] ?? 0} rows / ${cleanup['removed_contract_keys'] ?? 0} contracts removed • ${snapshot['daily_bars_attached'] ?? 0} daily bars saved to ${snapshot['strategy_rows_updated'] ?? 0} strategy records',
                          style: TextStyle(fontSize: 9, color: cs.onSurfaceVariant),
                        );
                      }),
                    ],
                    if ((bootstrap['integrity_mismatches'] as List<dynamic>? ?? const []).isNotEmpty) ...[
                      const SizedBox(height: 8),
                      ...((bootstrap['integrity_mismatches'] as List<dynamic>).take(3)).map((item) {
                        final session = item as Map<String, dynamic>;
                        final marketChecks = session['markets'] as List<dynamic>? ?? const [];
                        final details = marketChecks.whereType<Map<String, dynamic>>()
                            .map((check) => '${check['market']}: NSE ${check['nse_source_records'] ?? '—'} / DB ${check['app_db_records'] ?? 0}')
                            .join('   ·   ');
                        return Padding(
                          padding: const EdgeInsets.only(top: 3),
                          child: Text('${session['date']}: $details',
                              style: TextStyle(fontSize: 9, color: cs.error)),
                        );
                      }),
                    ],
                  ],
                ),
              ),
            ),
            if (_upcomingHolidays().isNotEmpty) ...[
              const SizedBox(height: 10),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(13),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(children: [
                        Icon(Icons.event_available_rounded, color: cs.primary, size: 18),
                        const SizedBox(width: 7),
                        const Expanded(child: Text('NSE TRADING CALENDAR · CM',
                            style: TextStyle(fontSize: 10, fontWeight: FontWeight.w900, letterSpacing: .5))),
                        Text('OFFICIAL', style: TextStyle(fontSize: 8, color: cs.onSurfaceVariant)),
                      ]),
                      const SizedBox(height: 7),
                      ..._upcomingHolidays().map((holiday) => Padding(
                        padding: const EdgeInsets.symmetric(vertical: 3),
                        child: Row(children: [
                          SizedBox(width: 82, child: Text(holiday['date']?.toString() ?? '',
                              style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w800))),
                          Expanded(child: Text(holiday['description']?.toString() ?? 'Trading holiday',
                              style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant))),
                        ]),
                      )),
                      Text('Calendar refreshes with the nightly NSE data cycle. Special sessions follow separate NSE circulars.',
                          style: TextStyle(fontSize: 9, color: cs.onSurfaceVariant)),
                    ],
                  ),
                ),
              ),
            ],
            const SizedBox(height: 12),
            Row(children: [
              Expanded(child: _MarketChoice(
                title: 'CASH MARKET',
                subtitle: 'Equity OHLC · Volume',
                selected: _market == 'CM',
                onTap: () {
                  setState(() { _market = 'CM'; _instrumentFilter = ''; });
                  _load();
                },
              )),
              const SizedBox(width: 9),
              Expanded(child: _MarketChoice(
                title: 'F&O MARKET',
                subtitle: 'Futures · Options · OI',
                selected: _market == 'FO',
                onTap: () {
                  setState(() { _market = 'FO'; _instrumentFilter = ''; });
                  _load();
                },
              )),
            ]),
            const SizedBox(height: 10),
            TextField(
              controller: _search,
              textCapitalization: TextCapitalization.characters,
              decoration: InputDecoration(
                hintText: _market == 'CM' ? 'Search equity symbol' : 'Search stock or index (e.g. NIFTY)',
                prefixIcon: const Icon(Icons.search_rounded),
                suffixIcon: IconButton(
                  tooltip: 'Clear search',
                  onPressed: () { _search.clear(); _loadRows(); },
                  icon: const Icon(Icons.close_rounded),
                ),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(13)),
                isDense: true,
              ),
              onSubmitted: (_) => _loadRows(),
            ),
            if (_market == 'FO') ...[
              const SizedBox(height: 8),
              Wrap(spacing: 7, children: [
                _FilterChip(label: 'ALL', selected: _instrumentFilter.isEmpty,
                    onTap: () { setState(() => _instrumentFilter = ''); _loadRows(); }),
                _FilterChip(label: 'OPTIONS', selected: _instrumentFilter == 'OPT',
                    onTap: () { setState(() => _instrumentFilter = 'OPT'); _loadRows(); }),
                _FilterChip(label: 'FUTURES', selected: _instrumentFilter == 'FUT',
                    onTap: () { setState(() => _instrumentFilter = 'FUT'); _loadRows(); }),
              ]),
            ],
            const SizedBox(height: 12),
            Row(children: [
              Expanded(child: Text(
                '${_market == 'CM' ? 'CASH EQUITIES' : 'F&O CONTRACTS'} · ${marketStats['sessions'] ?? 0} sessions',
                style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w900, letterSpacing: .5),
              )),
              Text('${_rows.length} shown', style: TextStyle(fontSize: 9, color: cs.onSurfaceVariant)),
            ]),
            const SizedBox(height: 7),
            if (_loading) const LinearProgressIndicator(minHeight: 2),
            if (_error != null)
              Padding(padding: const EdgeInsets.all(12),
                child: Text(_error!, style: TextStyle(color: cs.error, fontSize: 11))),
            if (_rows.isEmpty && !_loading)
              Card(child: Padding(
                padding: const EdgeInsets.all(22),
                child: Column(children: [
                  Icon(Icons.storage_outlined, size: 32, color: cs.onSurfaceVariant),
                  const SizedBox(height: 8),
                  const Text('No rows available yet', style: TextStyle(fontWeight: FontWeight.w800)),
                  const SizedBox(height: 5),
                  Text('The server bootstrap may still be running, or the selected symbol has no matching EOD records.',
                      textAlign: TextAlign.center,
                      style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
                ]),
              )),
            ..._rows.map((row) => _BhavcopyRowCard(
              row: row,
              market: _market,
              date: _date,
              number: _number,
            )),
            const SizedBox(height: 12),
            Text(
              'Source: NSE official UDiFF bhavcopy archives. These are end-of-day records, not intraday candles, historical bid/ask quotes or complete intraday option-chain snapshots.',
              style: TextStyle(fontSize: 9, color: cs.onSurfaceVariant, height: 1.4),
            ),
          ],
        ),
      ),
    );
  }
}

class _MarketChoice extends StatelessWidget {
  const _MarketChoice({required this.title, required this.subtitle, required this.selected, required this.onTap});
  final String title, subtitle;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Material(
      color: selected ? cs.primaryContainer : Theme.of(context).cardColor,
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(14),
        child: Padding(
          padding: const EdgeInsets.all(13),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: TextStyle(fontSize: 10, fontWeight: FontWeight.w900,
                color: selected ? cs.onPrimaryContainer : cs.onSurface)),
            const SizedBox(height: 3),
            Text(subtitle, style: TextStyle(fontSize: 9,
                color: selected ? cs.onPrimaryContainer : cs.onSurfaceVariant)),
          ]),
        ),
      ),
    );
  }
}

class _CoverageChip extends StatelessWidget {
  const _CoverageChip({required this.label, required this.value, required this.color});
  final String label, value;
  final Color color;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
    decoration: BoxDecoration(
      color: color.withValues(alpha: .1),
      borderRadius: BorderRadius.circular(20),
      border: Border.all(color: color.withValues(alpha: .25)),
    ),
    child: Text('$label · $value',
        style: TextStyle(fontSize: 9, color: color, fontWeight: FontWeight.w800)),
  );
}

class _FilterChip extends StatelessWidget {
  const _FilterChip({required this.label, required this.selected, required this.onTap});
  final String label;
  final bool selected;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => ChoiceChip(
    label: Text(label, style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w800)),
    selected: selected,
    onSelected: (_) => onTap(),
    visualDensity: VisualDensity.compact,
  );
}

class _BhavcopyRowCard extends StatelessWidget {
  const _BhavcopyRowCard({
    required this.row, required this.market,
    required this.date, required this.number,
  });
  final Map<String, dynamic> row;
  final String market;
  final String Function(dynamic) date;
  final String Function(dynamic, {int decimals}) number;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final symbol = row['symbol']?.toString() ?? '—';
    final type = row['instrument_type']?.toString() ?? '';
    final expiry = date(row['expiry']);
    final optionType = row['option_type']?.toString() ?? '';
    final strike = row['strike'];
    final title = market == 'CM' ? symbol : '$symbol  ·  $type';
    final details = market == 'CM'
        ? 'O ${number(row['open'])}   H ${number(row['high'])}   L ${number(row['low'])}   C ${number(row['close'])}'
        : '${expiry.isEmpty ? type : expiry}  ·  ${strike == null ? '' : number(strike)} $optionType  ·  Close ${number(row['close'])}';
    return Card(
      margin: const EdgeInsets.only(bottom: 7),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(title, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w900))),
            Text(date(row['trade_date']), style: TextStyle(fontSize: 9, color: cs.onSurfaceVariant)),
          ]),
          const SizedBox(height: 5),
          Text(details, style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
          const SizedBox(height: 7),
          Wrap(spacing: 12, runSpacing: 4, children: [
            _Metric(label: 'VOLUME', value: number(row['volume'], decimals: 0)),
            if (market == 'FO') _Metric(label: 'OI', value: number(row['open_interest'], decimals: 0)),
            if (market == 'FO') _Metric(label: 'OI CHG', value: number(row['oi_change'], decimals: 0)),
            if (market == 'CM') _Metric(label: 'VALUE', value: number(row['turnover'], decimals: 0)),
          ]),
        ]),
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value});
  final String label, value;
  @override
  Widget build(BuildContext context) => Row(mainAxisSize: MainAxisSize.min, children: [
    Text('$label ', style: TextStyle(fontSize: 8, color: Theme.of(context).colorScheme.onSurfaceVariant)),
    Text(value, style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w800)),
  ]);
}
), '');
  }

  String _date(dynamic value) {
    if (value == null) return '';
    final text = value.toString();
    return text.length >= 10 ? text.substring(0, 10) : text;
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final bootstrap = _status['bootstrap'] as Map<String, dynamic>? ?? const {};
    final bootstrapState = bootstrap['status']?.toString() ?? 'NOT_STARTED';
    final ready = bootstrapState == 'READY';
    final progress = ((bootstrap['progress_pct'] as num?)?.toDouble() ?? 0) / 100;
    final cmRecords = _recordsFor('CM');
    final foRecords = _recordsFor('FO');
    final marketStats = (_status['markets'] as Map<String, dynamic>? ?? const {})[_market]
        as Map<String, dynamic>? ?? const {};

    return Scaffold(
      appBar: AppBar(
        title: const Text('NSE HISTORICAL DATA'),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            onPressed: _loading ? null : _load,
            icon: const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(14, 8, 14, 24),
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(15),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(children: [
                      Icon(Icons.cloud_download_outlined, color: cs.primary),
                      const SizedBox(width: 8),
                      const Expanded(child: Text('INITIAL DATA BOOTSTRAP',
                          style: TextStyle(fontSize: 11, fontWeight: FontWeight.w900, letterSpacing: .7))),
                      Text(ready ? 'READY' : bootstrapState,
                          style: TextStyle(fontSize: 9, fontWeight: FontWeight.w900,
                              color: ready ? Colors.green : cs.primary)),
                    ]),
                    const SizedBox(height: 9),
                    Text(
                      bootstrap['note']?.toString() ??
                          'The AIR server downloads three calendar months of NSE CM and F&O closing bhavcopy archives on first deployment.',
                      style: TextStyle(fontSize: 11, height: 1.4, color: cs.onSurfaceVariant),
                    ),
                    if (bootstrapState == 'RUNNING') ...[
                      const SizedBox(height: 10),
                      LinearProgressIndicator(value: progress > 0 ? progress : null),
                      const SizedBox(height: 5),
                      Text('${(progress * 100).toStringAsFixed(1)}% · ${bootstrap['completed_files'] ?? 0} / ${(bootstrap['weekdays_to_check'] as num? ?? 0).toInt() * 2} files',
                          style: TextStyle(fontSize: 9, color: cs.onSurfaceVariant)),
                    ],
                    const SizedBox(height: 10),
                    Wrap(spacing: 8, runSpacing: 6, children: [
                      _CoverageChip(label: 'CM', value: '${_number(cmRecords, decimals: 0)} rows', color: cs.primary),
                      _CoverageChip(label: 'FO', value: '${_number(foRecords, decimals: 0)} rows', color: cs.tertiary),
                      _CoverageChip(label: 'PAIRED SESSIONS', value: '${bootstrap['paired_sessions'] ?? 0}', color: cs.secondary),
                    ]),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 12),
            Row(children: [
              Expanded(child: _MarketChoice(
                title: 'CASH MARKET',
                subtitle: 'Equity OHLC · Volume',
                selected: _market == 'CM',
                onTap: () {
                  setState(() { _market = 'CM'; _instrumentFilter = ''; });
                  _load();
                },
              )),
              const SizedBox(width: 9),
              Expanded(child: _MarketChoice(
                title: 'F&O MARKET',
                subtitle: 'Futures · Options · OI',
                selected: _market == 'FO',
                onTap: () {
                  setState(() { _market = 'FO'; _instrumentFilter = ''; });
                  _load();
                },
              )),
            ]),
            const SizedBox(height: 10),
            TextField(
              controller: _search,
              textCapitalization: TextCapitalization.characters,
              decoration: InputDecoration(
                hintText: _market == 'CM' ? 'Search equity symbol' : 'Search stock or index (e.g. NIFTY)',
                prefixIcon: const Icon(Icons.search_rounded),
                suffixIcon: IconButton(
                  tooltip: 'Clear search',
                  onPressed: () { _search.clear(); _loadRows(); },
                  icon: const Icon(Icons.close_rounded),
                ),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(13)),
                isDense: true,
              ),
              onSubmitted: (_) => _loadRows(),
            ),
            if (_market == 'FO') ...[
              const SizedBox(height: 8),
              Wrap(spacing: 7, children: [
                _FilterChip(label: 'ALL', selected: _instrumentFilter.isEmpty,
                    onTap: () { setState(() => _instrumentFilter = ''); _loadRows(); }),
                _FilterChip(label: 'OPTIONS', selected: _instrumentFilter == 'OPT',
                    onTap: () { setState(() => _instrumentFilter = 'OPT'); _loadRows(); }),
                _FilterChip(label: 'FUTURES', selected: _instrumentFilter == 'FUT',
                    onTap: () { setState(() => _instrumentFilter = 'FUT'); _loadRows(); }),
              ]),
            ],
            const SizedBox(height: 12),
            Row(children: [
              Expanded(child: Text(
                '${_market == 'CM' ? 'CASH EQUITIES' : 'F&O CONTRACTS'} · ${marketStats['sessions'] ?? 0} sessions',
                style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w900, letterSpacing: .5),
              )),
              Text('${_rows.length} shown', style: TextStyle(fontSize: 9, color: cs.onSurfaceVariant)),
            ]),
            const SizedBox(height: 7),
            if (_loading) const LinearProgressIndicator(minHeight: 2),
            if (_error != null)
              Padding(padding: const EdgeInsets.all(12),
                child: Text(_error!, style: TextStyle(color: cs.error, fontSize: 11))),
            if (_rows.isEmpty && !_loading)
              Card(child: Padding(
                padding: const EdgeInsets.all(22),
                child: Column(children: [
                  Icon(Icons.storage_outlined, size: 32, color: cs.onSurfaceVariant),
                  const SizedBox(height: 8),
                  const Text('No rows available yet', style: TextStyle(fontWeight: FontWeight.w800)),
                  const SizedBox(height: 5),
                  Text('The server bootstrap may still be running, or the selected symbol has no matching EOD records.',
                      textAlign: TextAlign.center,
                      style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
                ]),
              )),
            ..._rows.map((row) => _BhavcopyRowCard(
              row: row,
              market: _market,
              date: _date,
              number: _number,
            )),
            const SizedBox(height: 12),
            Text(
              'Source: NSE official UDiFF bhavcopy archives. These are end-of-day records, not intraday candles, historical bid/ask quotes or complete intraday option-chain snapshots.',
              style: TextStyle(fontSize: 9, color: cs.onSurfaceVariant, height: 1.4),
            ),
          ],
        ),
      ),
    );
  }
}

class _MarketChoice extends StatelessWidget {
  const _MarketChoice({required this.title, required this.subtitle, required this.selected, required this.onTap});
  final String title, subtitle;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Material(
      color: selected ? cs.primaryContainer : Theme.of(context).cardColor,
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(14),
        child: Padding(
          padding: const EdgeInsets.all(13),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: TextStyle(fontSize: 10, fontWeight: FontWeight.w900,
                color: selected ? cs.onPrimaryContainer : cs.onSurface)),
            const SizedBox(height: 3),
            Text(subtitle, style: TextStyle(fontSize: 9,
                color: selected ? cs.onPrimaryContainer : cs.onSurfaceVariant)),
          ]),
        ),
      ),
    );
  }
}

class _CoverageChip extends StatelessWidget {
  const _CoverageChip({required this.label, required this.value, required this.color});
  final String label, value;
  final Color color;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
    decoration: BoxDecoration(
      color: color.withValues(alpha: .1),
      borderRadius: BorderRadius.circular(20),
      border: Border.all(color: color.withValues(alpha: .25)),
    ),
    child: Text('$label · $value',
        style: TextStyle(fontSize: 9, color: color, fontWeight: FontWeight.w800)),
  );
}

class _FilterChip extends StatelessWidget {
  const _FilterChip({required this.label, required this.selected, required this.onTap});
  final String label;
  final bool selected;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => ChoiceChip(
    label: Text(label, style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w800)),
    selected: selected,
    onSelected: (_) => onTap(),
    visualDensity: VisualDensity.compact,
  );
}

class _BhavcopyRowCard extends StatelessWidget {
  const _BhavcopyRowCard({
    required this.row, required this.market,
    required this.date, required this.number,
  });
  final Map<String, dynamic> row;
  final String market;
  final String Function(dynamic) date;
  final String Function(dynamic, {int decimals}) number;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final symbol = row['symbol']?.toString() ?? '—';
    final type = row['instrument_type']?.toString() ?? '';
    final expiry = date(row['expiry']);
    final optionType = row['option_type']?.toString() ?? '';
    final strike = row['strike'];
    final title = market == 'CM' ? symbol : '$symbol  ·  $type';
    final details = market == 'CM'
        ? 'O ${number(row['open'])}   H ${number(row['high'])}   L ${number(row['low'])}   C ${number(row['close'])}'
        : '${expiry.isEmpty ? type : expiry}  ·  ${strike == null ? '' : number(strike)} $optionType  ·  Close ${number(row['close'])}';
    return Card(
      margin: const EdgeInsets.only(bottom: 7),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(title, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w900))),
            Text(date(row['trade_date']), style: TextStyle(fontSize: 9, color: cs.onSurfaceVariant)),
          ]),
          const SizedBox(height: 5),
          Text(details, style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
          const SizedBox(height: 7),
          Wrap(spacing: 12, runSpacing: 4, children: [
            _Metric(label: 'VOLUME', value: number(row['volume'], decimals: 0)),
            if (market == 'FO') _Metric(label: 'OI', value: number(row['open_interest'], decimals: 0)),
            if (market == 'FO') _Metric(label: 'OI CHG', value: number(row['oi_change'], decimals: 0)),
            if (market == 'CM') _Metric(label: 'VALUE', value: number(row['turnover'], decimals: 0)),
          ]),
        ]),
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value});
  final String label, value;
  @override
  Widget build(BuildContext context) => Row(mainAxisSize: MainAxisSize.min, children: [
    Text('$label ', style: TextStyle(fontSize: 8, color: Theme.of(context).colorScheme.onSurfaceVariant)),
    Text(value, style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w800)),
  ]);
}
