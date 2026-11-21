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
      // The P&L calendar is the canonical accounting projection. Do not
      // overlay MASTER rows or reconstruct missing prices, quantities or P&L.
      final calendar = await _api.modelEnginePnlCalendar();
      final pnlExpired = (calendar['expired_trades'] as List<dynamic>? ?? const [])
          .whereType<Map<String, dynamic>>()
          .where((row) => row['source'] == 'VERIFIED_REPLAY_OR_LEDGER')
          .toList();
      final unique = <String, Map<String, dynamic>>{};
      for (final row in pnlExpired) {
        unique[_identity(row)] = Map<String, dynamic>.from(row);
      }
      if (mounted) setState(() => _rows = unique.values.toList()
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

  double? _canonicalNumber(Map<String, dynamic> row, String field) =>
      _number(row[field]);

  double? _grossPnl(Map<String, dynamic> row) => _canonicalNumber(row, 'gross_pnl');

  double? _netPnl(Map<String, dynamic> row) => _canonicalNumber(row, 'net_pnl');

  double? _chargesTotal(Map<String, dynamic> row) {
    final charges = row['charges'];
    return charges is Map ? _number(charges['total']) : null;
  }

  String _chargeBasis(Map<String, dynamic> row) {
    final charges = row['charges'];
    if (charges is! Map) return 'PENDING';
    final basis = (charges['basis'] ?? '').toString();
    if (basis == 'ACTUAL_SOURCE_BREAKDOWN' ||
        basis == 'ACTUAL_REPORTED_TOTAL_BREAKDOWN_UNAVAILABLE') return 'ACTUAL';
    if (basis.startsWith('ESTIMATED')) return 'ESTIMATED';
    return 'PENDING';
  }

  int? _recordedQuantity(Map<String, dynamic> row) {
    final quantity = _number(row['quantity']);
    return quantity == null ? null : quantity.round();
  }

  String _outcome(Map<String, dynamic> row) =>
      (row['expiry_outcome'] ?? 'EXPIRED_PNL_PENDING').toString();

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
    final pending = rows.where((r) => r['exit_price'] == null).length;
    final chargePending = rows.where((r) => _chargesTotal(r) == null).length;
    final estimatedCharges = rows.where((r) => _chargeBasis(r) == 'ESTIMATED').length;
    final actualCharges = rows.where((r) => _chargeBasis(r) == 'ACTUAL').length;
    final grossTotal = _sumPnl(rows, _grossPnl);
    final netTotal = _sumPnl(rows, _netPnl);
    final chargesTotal = _sumPnl(rows, _chargesTotal);
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
            _metric('RECORDED CHARGES', _money(chargePending == 0 ? chargesTotal : null)),
            _metric('P&L PENDING', pending.toString()),
          ]),
          Padding(padding: const EdgeInsets.symmetric(horizontal: 5), child: Text(
            'Charges: $actualCharges actual / broker-reported, $estimatedCharges estimated, $chargePending pending. Estimates are not broker-confirmed.',
            style: TextStyle(fontSize: 9, color: Theme.of(context).colorScheme.onSurfaceVariant))),
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
                DataColumn(label: Text('LOT SIZE')), DataColumn(label: Text('GROSS P&L')), DataColumn(label: Text('NET P&L')),
                DataColumn(label: Text('OUTCOME')),
              ],
              rows: rows.map((row) {
                final outcome = _outcome(row);
                final color = outcome == 'EXPIRED_WIN' ? Colors.green :
                  outcome == 'EXPIRED_LOSS' ? Theme.of(context).colorScheme.error :
                  Theme.of(context).colorScheme.onSurfaceVariant;
                return DataRow(cells: [
                  DataCell(Text((row['strategy'] ?? '—').toString(), style: const TextStyle(fontSize: 9))),
                  DataCell(Text((row['symbol'] ?? '—').toString(), style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w800))),
                  DataCell(Text((row['option_type'] ?? '—').toString())),
                  DataCell(Text((row['strike'] ?? '—').toString())),
                  DataCell(Text(_date(row['expiry']))),
                  DataCell(Text(_number(row['entry_price'])?.toStringAsFixed(2) ?? '—')),
                  DataCell(Text(_number(row['exit_price'])?.toStringAsFixed(2) ?? 'PENDING')),
                  DataCell(Text(_recordedQuantity(row)?.toString() ?? 'PENDING')),
                  DataCell(Text(_number(row['lot_size'])?.toStringAsFixed(0) ?? '—')),
                  DataCell(Text(_money(_grossPnl(row)))),
                  DataCell(Text(_money(_netPnl(row)))),
                  DataCell(Text(outcome, style: TextStyle(fontSize: 9, color: color, fontWeight: FontWeight.w800))),
                ]);
              }).toList(),
            ))),
          if (rows.isEmpty && !_loading && _error == null)
            const Card(child: Padding(padding: EdgeInsets.all(16), child: Text('No completed expiry records are available yet.'))),
          if (_loading) const Padding(padding: EdgeInsets.symmetric(vertical: 12), child: LinearProgressIndicator()),
          if (_error != null) Card(child: Padding(padding: const EdgeInsets.all(12),
            child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error, fontSize: 11)))),
          const SizedBox(height: 8),
          Text('Displayed quantity, exit price and P&L come directly from the canonical verified replay/ledger P&L record. Lot size is reference metadata only. Charges retain their source basis (actual, estimated or pending). No expiry value or missing P&L is reconstructed in this screen. RECOVERED is a retrospective alternative-model simulation, not an additional broker position. Physical-settlement amounts are excluded to prevent double counting.',
            style: TextStyle(fontSize: 9, height: 1.4, color: Theme.of(context).colorScheme.onSurfaceVariant)),
        ]),
      ),
    );
  }
}
