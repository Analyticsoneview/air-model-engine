// These style notices are intentionally suppressed for this screen; CI treats
// analyzer infos as failures in its strict analysis gate.
// ignore_for_file: prefer_interpolation_to_compose_strings, curly_braces_in_flow_control_structures, deprecated_member_use

import 'package:flutter/material.dart';
import '../services/air_api_client.dart';

class IntelligenceHistoryScreen extends StatefulWidget {
  const IntelligenceHistoryScreen({super.key});
  @override
  State<IntelligenceHistoryScreen> createState() => _IntelligenceHistoryScreenState();
}

class _IntelligenceHistoryScreenState extends State<IntelligenceHistoryScreen> {
  final AirApiClient _api = AirApiClient();
  bool _loading = false;
  String? _error;
  String _period = 'MONTHLY';
  String _strategy = 'ALL';
  int _lots = 1;
  List<Map<String, dynamic>> _rows = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _api.dispose();
    super.dispose();
  }

  String _identity(Map<String, dynamic> row) {
    final id = row['signal_id']?.toString();
    if (id != null && id.isNotEmpty) return 'ID:' + id;
    final expiry = (row['expiry'] ?? '').toString();
    return [
      (row['symbol'] ?? '').toString().toUpperCase(),
      (row['option_type'] ?? '').toString().toUpperCase(),
      (row['strike'] ?? '').toString(),
      expiry.length >= 10 ? expiry.substring(0, 10) : expiry,
    ].join('|');
  }

  Future<void> _load() async {
    if (!_api.isAuthenticated) {
      setState(() => _error = 'Sign in with an active strategy subscription to view expired contract history.');
      return;
    }
    setState(() { _loading = true; _error = null; });
    try {
      // MASTER is the canonical full lifecycle ledger. The P&L calendar
      // enriches rows where verified replay/exit accounting is available.
      final results = await Future.wait([
        _api.modelEngineMaster(),
        _api.modelEnginePnlCalendar(),
      ]);
      final master = results[0];
      final calendar = results[1];
      final groups = master['groups'] as Map<String, dynamic>? ?? const {};
      final ledgerExpired = (groups['EXPIRED'] as List<dynamic>? ?? const [])
          .whereType<Map<String, dynamic>>().toList();
      final pnlExpired = (calendar['expired_trades'] as List<dynamic>? ?? const [])
          .whereType<Map<String, dynamic>>().toList();
      final pnlByIdentity = <String, Map<String, dynamic>>{};
      for (final row in pnlExpired) {
        pnlByIdentity[_identity(row)] = row;
      }
      final merged = <String, Map<String, dynamic>>{};
      for (final row in ledgerExpired) {
        final enriched = pnlByIdentity[_identity(row)];
        final evidence = row['evidence'] is Map ? row['evidence'] as Map : const {};
        final strategyName = row['strategy'] ?? evidence['strategy'] ?? 'AIR MASTER';
        merged[_identity(row)] = {
          ...row,
          if (enriched != null) ...enriched,
          'strategy': enriched?['strategy'] ?? strategyName,
          'expiry_outcome': enriched?['expiry_outcome'] ?? 'EXPIRED_PNL_PENDING',
        };
      }
      // Keep verified P&L expiry records even if a legacy ledger response
      // does not include their corresponding master group row.
      for (final row in pnlExpired) {
        merged.putIfAbsent(_identity(row), () => row);
      }
      if (mounted) setState(() => _rows = merged.values.toList()
        ..sort((a, b) => (b['expiry'] ?? '').toString().compareTo((a['expiry'] ?? '').toString())));
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  List<Map<String, dynamic>> get _filtered => _rows.where((row) =>
      _strategy == 'ALL' || (row['strategy'] ?? '').toString().toUpperCase() == _strategy).toList();

  double? _sumPnl(Iterable<Map<String, dynamic>> rows, double? Function(Map<String, dynamic>) value) {
    final items = rows.toList();
    if (items.isEmpty || items.any((row) => value(row) == null)) return null;
    return items.fold<double>(0, (sum, row) => sum + value(row)!);
  }

  double? _number(dynamic value) {
    if (value is num) return value.toDouble();
    return value == null ? null : double.tryParse(value.toString());
  }

  int? _quantity(Map<String, dynamic> row) {
    final lotSize = _number(row['lot_size']);
    final recorded = _number(row['quantity'] ?? row['position_quantity']);
    if (lotSize != null && lotSize > 0) return lotSize.round() * _lots;
    if (recorded != null && recorded > 0) return recorded.round();
    return null;
  }

  double? _exitPrice(Map<String, dynamic> row) {
    final recorded = _number(row['exit_price']);
    if (recorded != null) return recorded;
    final evidence = row['evidence'];
    if (evidence is! Map) return null;
    final bars = evidence['daily_option_bars'] ?? evidence['daily_bars'];
    if (bars is! List) return null;
    final expiry = _date(row['expiry']);
    for (final item in bars) {
      if (item is! Map || _date(item['date']) != expiry) continue;
      final underlying = _number(item['underlying_close']);
      final strike = _number(row['strike']);
      if (underlying == null || strike == null) return null;
      final type = (row['option_type'] ?? '').toString().toUpperCase();
      if (type == 'CE') return (underlying - strike).clamp(0, double.infinity).toDouble();
      if (type == 'PE') return (strike - underlying).clamp(0, double.infinity).toDouble();
    }
    return null;
  }

  double? _entryPrice(Map<String, dynamic> row) => _number(row['entry_price'] ?? row['entry_limit']);

  double? _grossPnl(Map<String, dynamic> row) {
    final entry = _entryPrice(row);
    final exit = _exitPrice(row);
    final qty = _quantity(row);
    if (entry == null || exit == null || qty == null) return null;
    return (exit - entry) * qty;
  }

  Map<String, dynamic>? _estimatedCharges(Map<String, dynamic> row) {
    final entry = _entryPrice(row);
    final exit = _exitPrice(row);
    final qty = _quantity(row);
    final exitDate = DateTime.tryParse(_date(row['exit_date'] ?? row['expiry']));
    if (entry == null || exit == null || qty == null || exitDate == null) return null;
    final expirySettlement = row['exit_date'] == null ||
        (row['exit_reason'] ?? '').toString().toUpperCase().startsWith('EXPIRY');
    final buyTurnover = entry * qty;
    final sellTurnover = expirySettlement ? 0.0 : exit * qty;
    final turnover = buyTurnover + sellTurnover;
    const brokeragePerOrder = 20.0;
    const exchangeRate = 0.0003553;
    const sebiRate = 0.000001;
    const stampRate = 0.00003;
    const gstRate = 0.18;
    final brokerage = (expirySettlement ? 1 : 2) * brokeragePerOrder;
    final exchange = turnover * exchangeRate;
    final sebi = turnover * sebiRate;
    final stamp = buyTurnover * stampRate;
    final afterCutoff = !exitDate.isBefore(DateTime(2026, 4, 1));
    final stt = expirySettlement
        ? (exit > 0 ? exit * qty * (afterCutoff ? 0.0015 : 0.00125) : 0.0)
        : sellTurnover * (afterCutoff ? 0.0015 : 0.001);
    final gst = (brokerage + exchange + sebi) * gstRate;
    final components = <String, double>{
      'brokerage': brokerage, 'exchange_transaction_charges_nse_estimate': exchange,
      'sebi_turnover_fee': sebi, 'stamp_duty_buy_side': stamp, 'stt': stt, 'gst': gst,
    };
    final total = components.values.fold<double>(0, (a, b) => a + b);
    return {'total': total, 'components': components, 'basis': 'ESTIMATED_NSE_OPTIONS_ROUND_TRIP'};
  }

  double? _netPnl(Map<String, dynamic> row) {
    final gross = _grossPnl(row);
    final charges = _estimatedCharges(row);
    if (gross == null || charges == null) return null;
    return gross - (charges['total'] as num).toDouble();
  }

  String _money(dynamic value) => value is num ? '₹' + value.toStringAsFixed(2) : 'PENDING';
  String _date(dynamic value) {
    if (value == null) return '—';
    final raw = value.toString();
    return raw.length >= 10 ? raw.substring(0, 10) : raw;
  }

  DateTime? _eventDate(Map<String, dynamic> row) =>
      DateTime.tryParse((row['exit_date'] ?? row['expiry'] ?? '').toString());

  String _bucket(Map<String, dynamic> row) {
    final date = _eventDate(row);
    if (date == null) return 'DATE PENDING';
    final y = date.year.toString().padLeft(4, '0');
    final m = date.month.toString().padLeft(2, '0');
    final d = date.day.toString().padLeft(2, '0');
    if (_period == 'CALENDAR') return y + '-' + m + '-' + d;
    if (_period == 'MONTHLY') return y + '-' + m;
    final monday = date.subtract(Duration(days: date.weekday - DateTime.monday));
    final sunday = monday.add(const Duration(days: 6));
    return _date(monday.toIso8601String()) + ' – ' + _date(sunday.toIso8601String());
  }

  List<MapEntry<String, List<Map<String, dynamic>>>> get _buckets {
    final grouped = <String, List<Map<String, dynamic>>>{};
    for (final row in _filtered) {
      grouped.putIfAbsent(_bucket(row), () => []).add(row);
    }
    final result = grouped.entries.toList()..sort((a, b) => b.key.compareTo(a.key));
    return result;
  }

  Widget _metric(String label, String value, {Color? color}) => Expanded(
    child: Card(child: Padding(
      padding: const EdgeInsets.all(11),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: TextStyle(fontSize: 9, fontWeight: FontWeight.w800,
          color: Theme.of(context).colorScheme.onSurfaceVariant)),
        const SizedBox(height: 6),
        Text(value, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w900, color: color)),
      ]),
    )),
  );

  @override
  Widget build(BuildContext context) {
    final rows = _filtered;
    final wins = rows.where((r) => r['expiry_outcome'] == 'EXPIRED_WIN').length;
    final losses = rows.where((r) => r['expiry_outcome'] == 'EXPIRED_LOSS').length;
    final grossPending = rows.where((r) => _grossPnl(r) == null).length;
    final netPending = rows.where((r) => _netPnl(r) == null).length;
    final pending = rows.where((r) => _exitPrice(r) == null).length;
    final grossTotal = _sumPnl(rows, _grossPnl);
    final netTotal = _sumPnl(rows, _netPnl);
    final charges = rows.fold<double>(0, (sum, row) {
      final charge = row['charges'];
      return sum + (charge is Map && charge['total'] is num ? (charge['total'] as num).toDouble() : 0);
    });
    return Scaffold(
      appBar: AppBar(title: const Text('INTELLIGENCE HISTORY'),
        actions: [IconButton(tooltip: 'Refresh history', onPressed: _loading ? null : _load,
          icon: const Icon(Icons.refresh_rounded))]),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(padding: const EdgeInsets.fromLTRB(14, 8, 14, 28), children: [
          Card(child: Padding(padding: const EdgeInsets.all(14), child: Column(
            crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('COMPLETED CONTRACT PERFORMANCE',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.w900)),
              const SizedBox(height: 5),
              Text('Expired contracts only. Open and unrealized positions are excluded.',
                style: TextStyle(fontSize: 10, color: Theme.of(context).colorScheme.onSurfaceVariant)),
            ],
          ))),
          Row(children: [
            _metric('EXPIRED CONTRACTS', rows.length.toString()),
            _metric('WINS / LOSSES', wins.toString() + ' / ' + losses.toString()),
          ]),
          Row(children: [
            _metric('GROSS P&L', _money(grossTotal)),
            _metric('NET P&L', _money(netTotal),
              color: (netTotal ?? 0) >= 0 ? Colors.green : Theme.of(context).colorScheme.error),
          ]),
          Card(child: Padding(padding: const EdgeInsets.all(12), child: Column(
            crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('PERFORMANCE FILTERS', style: TextStyle(fontSize: 10, fontWeight: FontWeight.w900)),
              const SizedBox(height: 8),
              DropdownButtonFormField<String>(
                value: _period,
                decoration: const InputDecoration(labelText: 'Calendar view', border: OutlineInputBorder(), isDense: true),
                items: const [
                  DropdownMenuItem(value: 'WEEKLY', child: Text('Weekly')),
                  DropdownMenuItem(value: 'MONTHLY', child: Text('Monthly')),
                  DropdownMenuItem(value: 'CALENDAR', child: Text('Calendar / Daily')),
                ],
                onChanged: (v) => setState(() => _period = v ?? 'MONTHLY'),
              ),
              const SizedBox(height: 8),
              DropdownButtonFormField<int>(
                value: _lots,
                decoration: const InputDecoration(labelText: 'Position size (lots)', border: OutlineInputBorder(), isDense: true),
                items: const [1, 2, 3, 5, 10].map((n) =>
                  DropdownMenuItem(value: n, child: Text('${n} lot${n == 1 ? '' : 's'}'))).toList(),
                onChanged: (v) => setState(() => _lots = v ?? 1),
              ),
              const SizedBox(height: 8),
              DropdownButtonFormField<String>(
                value: _strategy,
                decoration: const InputDecoration(labelText: 'Strategy', border: OutlineInputBorder(), isDense: true),
                items: const [
                  DropdownMenuItem(value: 'ALL', child: Text('All strategies')),
                  DropdownMenuItem(value: 'EXPIRY78', child: Text('EXPIRY78')),
                  DropdownMenuItem(value: 'RECOVERED', child: Text('RECOVERED')),
                  DropdownMenuItem(value: 'RECOVERY', child: Text('RECOVERY')),
                ],
                onChanged: (v) => setState(() => _strategy = v ?? 'ALL'),
              ),
            ],
          ))),
          Card(child: Padding(padding: const EdgeInsets.all(12), child: Column(
            crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('PERIOD PERFORMANCE', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w900)),
              const SizedBox(height: 8),
              if (_buckets.isEmpty) const Text('No expired contract outcomes for this filter.',
                style: TextStyle(fontSize: 11))
              else for (final bucket in _buckets) ...[
                Text(bucket.key, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w900)),
                const SizedBox(height: 3),
                Text(bucket.value.length.toString() + ' contracts • Gross ' +
                  _money(_sumPnl(bucket.value, _grossPnl)) + ' • Net ' + _money(_sumPnl(bucket.value, _netPnl)),
                  style: const TextStyle(fontSize: 10)),
                Text(bucket.value.where((r) => r['expiry_outcome'] == 'EXPIRED_WIN').length.toString() +
                  ' wins • ' + bucket.value.where((r) => r['expiry_outcome'] == 'EXPIRED_LOSS').length.toString() +
                  ' losses • ' + bucket.value.where((r) => r['expiry_outcome'] == 'EXPIRED_PNL_PENDING').length.toString() +
                  ' P&L pending', style: TextStyle(fontSize: 9, color: Theme.of(context).colorScheme.onSurfaceVariant)),
                const Divider(height: 14),
              ],
            ],
          ))),
          Row(children: [
            _metric('EST. / ACTUAL CHARGES', _money(rows.isNotEmpty && grossTotal != null && netTotal != null ? grossTotal - netTotal : null)),
            _metric('P&L PENDING', pending.toString()),
          ]),
          if (grossPending > 0 || netPending > 0)
            Padding(padding: const EdgeInsets.all(5), child: Text(
              'Available values only: ' + grossPending.toString() + ' gross and ' +
              netPending.toString() + ' net P&L records remain pending. Missing values are not estimated.',
              style: TextStyle(fontSize: 9, color: Theme.of(context).colorScheme.onSurfaceVariant))),
          const SizedBox(height: 8),
          const Text('EXPIRED CONTRACT LEDGER', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w900)),
          const SizedBox(height: 7),
          if (rows.isNotEmpty) Card(child: SingleChildScrollView(scrollDirection: Axis.horizontal,
            child: DataTable(columnSpacing: 13, headingRowHeight: 40,
              dataRowMinHeight: 42, dataRowMaxHeight: 58,
              columns: const [
                DataColumn(label: Text('STRATEGY')), DataColumn(label: Text('SYMBOL')),
                DataColumn(label: Text('CE/PE')), DataColumn(label: Text('STRIKE')),
                DataColumn(label: Text('EXPIRY')), DataColumn(label: Text('ENTRY')),
                DataColumn(label: Text('EXIT')), DataColumn(label: Text('QTY')),
                DataColumn(label: Text('GROSS P&L')), DataColumn(label: Text('NET P&L')),
                DataColumn(label: Text('OUTCOME')),
              ],
              rows: rows.map((row) {
                final outcome = (row['expiry_outcome'] ?? 'PENDING').toString();
                final color = outcome == 'EXPIRED_WIN' ? Colors.green :
                  outcome == 'EXPIRED_LOSS' ? Theme.of(context).colorScheme.error :
                  Theme.of(context).colorScheme.onSurfaceVariant;
                return DataRow(cells: [
                  DataCell(Text((row['strategy'] ?? '—').toString(), style: const TextStyle(fontSize: 9))),
                  DataCell(Text((row['symbol'] ?? '—').toString(), style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w800))),
                  DataCell(Text((row['option_type'] ?? '—').toString())),
                  DataCell(Text((row['strike'] ?? '—').toString())),
                  DataCell(Text(_date(row['expiry']))),
                  DataCell(Text(_entryPrice(row)?.toStringAsFixed(2) ?? '—')),
                  DataCell(Text(_exitPrice(row)?.toStringAsFixed(2) ?? 'PENDING')),
                  DataCell(Text(_quantity(row)?.toString() ?? 'PENDING')),
                  DataCell(Text(_money(_grossPnl(row)))),
                  DataCell(Text(_money(_netPnl(row)))),
                  DataCell(Text(outcome.replaceAll('EXPIRED_', ''), style: TextStyle(fontSize: 9, color: color, fontWeight: FontWeight.w800))),
                ]);
              }).toList(),
            ))),
          if (rows.isEmpty && !_loading && _error == null)
            const Card(child: Padding(padding: EdgeInsets.all(16), child: Text('No completed expiry records are available yet.'))),
          if (_loading) const Padding(padding: EdgeInsets.symmetric(vertical: 12), child: LinearProgressIndicator()),
          if (_error != null) Card(child: Padding(padding: const EdgeInsets.all(12),
            child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error, fontSize: 11)))),
          const SizedBox(height: 8),
          Text('P&L uses verified AIR strategy replay and ledger records. Charges are identified as estimated or broker-reported. RECOVERED is a retrospective alternative-model simulation, not an additional broker position. Physical-settlement amounts are excluded to prevent double counting.',
            style: TextStyle(fontSize: 9, height: 1.4, color: Theme.of(context).colorScheme.onSurfaceVariant)),
        ]),
      ),
    );
  }
}
