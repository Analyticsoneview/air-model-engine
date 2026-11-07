import 'dart:async';
import 'package:flutter/material.dart';
import '../services/air_api_client.dart';

class ModelEngineScreen extends StatefulWidget {
  const ModelEngineScreen({super.key});
  @override
  State<ModelEngineScreen> createState() => _ModelEngineScreenState();
}

class _ModelEngineScreenState extends State<ModelEngineScreen> {
  final AirApiClient _api = AirApiClient();
  static const _sections = ['P&L CALENDAR', 'OPEN', 'NEW', 'HOLD', 'REENTRY', 'SURVIVOR', 'WAIT', 'SLHIT', 'TARGETS', 'EXPIRED', 'EXPIRYSCAN', 'PHYSICAL SETTLEMENT', 'COMBINED', 'EXPIRY78', 'RECOVERED', 'RECOVERY'];
  static const _strategyTabs = ['EXPIRY78', 'RECOVERED', 'RECOVERY'];

  String _strategyKey(String section) => section == 'RECOVERED' ? 'ORIGINAL366' : section;
  Map<String, dynamic> _groups = {};
  Map<String, dynamic> _strategies = {};
  Map<String, dynamic> _counts = {};
  Map<String, dynamic> _summary = {};
  Map<String, dynamic> _breakdowns = {};
  List<Map<String, dynamic>> _expiryRows = [];
  List<Map<String, dynamic>> _settlementRows = [];
  Map<String, dynamic> _settlementSummary = {};
  String? _settlementNote;
  List<Map<String, dynamic>> _expiryAlerts = [];
  String? _expiryNote;
  int _selected = 0;
  bool _authenticated = false, _loading = false;
  Timer? _autoRefreshTimer;
  String? _error, _updatedAt;
  String _strategyStatus = 'OPEN';
  String _dataStatus = 'SIGN IN TO LOAD YOUR MODEL ENGINE LEDGER';
  Map<String, dynamic> _marketDataSource = {};
  Map<String, dynamic> _pnlCalendar = {};
  DateTime _calendarMonth = DateTime(DateTime.now().year, DateTime.now().month);
  bool _calendarLoading = false;

  @override
  void initState() {
    super.initState();
    _authenticated = _api.isAuthenticated;
    if (_authenticated) {
      _refresh();
      _autoRefreshTimer = Timer.periodic(const Duration(minutes: 5), (_) {
        if (mounted && !_loading) _refresh();
      });
    }
  }

  @override
  void dispose() { _autoRefreshTimer?.cancel(); _api.dispose(); super.dispose(); }

  Future<void> _refresh() async {
    if (!_api.isAuthenticated) return;
    setState(() { _loading = true; _error = null; });
    try {
      final result = await _api.modelEngineMaster();
      Map<String, dynamic>? expiryResult;
      Map<String, dynamic>? settlementResult;
      Map<String, dynamic>? pnlResult;
      try { expiryResult = await _api.expiryScan(); }
      catch (e) { _expiryNote = 'EXPIRYSCAN unavailable: $e'; }
      try { settlementResult = await _api.physicalSettlement(); }
      catch (e) { _settlementNote = 'Physical settlement review unavailable: $e'; }
      try { pnlResult = await _api.modelEnginePnlCalendar(year: _calendarMonth.year, month: _calendarMonth.month); }
      catch (e) { _error = 'P&L calendar unavailable: $e'; }
      if (!mounted) return;
      setState(() {
        if (pnlResult != null) _pnlCalendar = pnlResult;
        _groups = result['groups'] as Map<String, dynamic>? ?? {};
        _strategies = result['strategies'] as Map<String, dynamic>? ?? {};
        if (expiryResult != null) {
          _expiryRows = [
            ...(expiryResult['rows'] as List<dynamic>? ?? const []),
            ...(expiryResult['expired_rows'] as List<dynamic>? ?? const []),
          ].whereType<Map<String, dynamic>>().toList();
          _expiryAlerts = (expiryResult['close_alerts'] as List<dynamic>? ?? const [])
              .whereType<Map<String, dynamic>>().toList();
          _expiryNote = expiryResult['note']?.toString();
        }
        if (settlementResult != null) {
          _settlementRows = (settlementResult['rows'] as List<dynamic>? ?? const [])
              .whereType<Map<String, dynamic>>().toList();
          _settlementSummary = settlementResult['summary'] as Map<String, dynamic>? ?? {};
          _settlementNote = settlementResult['note']?.toString();
        }
        _counts = result['counts'] as Map<String, dynamic>? ?? {};
        _summary = result['summary'] as Map<String, dynamic>? ?? {};
        _breakdowns = result['breakdowns'] as Map<String, dynamic>? ?? {};
        _updatedAt = result['updated_at']?.toString();
        _dataStatus = result['data_status']?.toString() ?? 'UNKNOWN';
        _marketDataSource = result['market_data_source'] as Map<String, dynamic>? ?? {};
      });
    } catch (e) { if (mounted) setState(() => _error = e.toString()); }
    finally { if (mounted) setState(() => _loading = false); }
  }

  String _v(Map<String, dynamic> row, String key) => row[key] == null ? '—' : row[key].toString();

  String _tabCount(String section) {
    if (section == 'P&L CALENDAR') return '₹';
    if (_strategyTabs.contains(section)) {
      final data = _strategies[_strategyKey(section)];
      if (data is! Map) return '0';
      if (section == 'RECOVERED') {
        final counts = data['counts'];
        return counts is Map ? (counts['RECOVERED'] ?? 0).toString() : '0';
      }
      return (data['count'] ?? 0).toString();
    }
    if (section == 'EXPIRYSCAN') return _expiryRows.length.toString();
    if (section == 'PHYSICAL SETTLEMENT') return _settlementRows.length.toString();
    return (_counts[section] ?? 0).toString();
  }
  Widget _settlementMetric(String label, dynamic value) => Container(
    padding: const EdgeInsets.all(9),
    decoration: BoxDecoration(
      border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
      borderRadius: BorderRadius.circular(8),
    ),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(label, style: const TextStyle(fontSize: 8, fontWeight: FontWeight.w800)),
      const SizedBox(height: 3),
      Text(value == null ? '—' : (value is num && label.contains('FUNDS') ? '₹${value.toStringAsFixed(2)}' : value.toString()),
        style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w900)),
    ]),
  );

  Widget _cell(String value) => Padding(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 9),
    child: Text(value, style: const TextStyle(fontSize: 10)),
  );

  List<DataColumn> get _columns => [
    DataColumn(label: Text('MODEL SIGNAL DATE')),
    DataColumn(label: Text('ENTRY DATE')),
    DataColumn(label: Text('CLASSIFICATION')),
    DataColumn(label: Text('INSTRUMENT')),
    DataColumn(label: Text('SYMBOL')),
    DataColumn(label: Text('SECTOR')),
    DataColumn(label: Text('CE/PE')),
    DataColumn(label: Text('STRIKE')),
    DataColumn(label: Text('EXPIRY')),
    DataColumn(label: Text('ENTRY PRICE')),
    DataColumn(label: Text('LATEST PRICE')),
    DataColumn(label: Text('QUANTITY / LOTS')),
    DataColumn(label: Text('STOP LOSS')),
    DataColumn(label: Text('TARGETS')),
    DataColumn(label: Text('CURRENT P&L')),
    DataColumn(label: Text('DAYS TO EXPIRY')),
    DataColumn(label: Text('STATUS')),
    if (_sections[_selected] == 'EXPIRY78') const DataColumn(label: Text('DELIVERY ALERT • ENTRY / LIVE')),
    if (_sections[_selected] == 'EXPIRY78') const DataColumn(label: Text('PHYSICAL SETTLEMENT FORECAST')),
    const DataColumn(label: Text('LATEST EVIDENCE')),
  ];

  bool _isSurvivor(Map<String, dynamic> r) =>
      r['survivor_eligible'] == true;

  String _classificationLabel(Map<String, dynamic> r) {
    switch ((r['classification'] ?? '').toString().toUpperCase()) {
      case 'NEW': return '🆕 NEW';
      case 'HOLD': return '📌 HOLD';
      case 'RE-ENTRY': return '🔁 RE-ENTRY';
      case 'SL': return 'SL HIT';
      case 'SLHIT': return 'SL HIT';
      case 'TARGETS': return '45% TARGET HIT';
      case 'EXPIRED': return 'EXPIRED';
      case 'OPEN': return '📌 OPEN';
      case 'RECOVERED_WATCH':
        final outcome = (r['recovered_outcome'] ?? '').toString().toUpperCase();
        if (outcome == 'TARGET_FIRST') return '👀 RECOVERED • TARGET HIT';
        if (outcome == 'STOP_FIRST') return '👀 RECOVERED • SL HIT';
        if (outcome == 'EXPIRY_SETTLEMENT') return '👀 RECOVERED • EXPIRY';
        return '👀 RECOVERED WATCH';
      default: return _v(r, 'classification');
    }
  }

  String _quantityLots(Map<String, dynamic> r) {
    final quantity = r['quantity'];
    final lotSize = r['lot_size'];
    if (quantity == null) return '—';
    if (lotSize is num && lotSize > 0 && quantity is num) {
      final lots = quantity / lotSize;
      return '$quantity qty / ${lots.toStringAsFixed(lots % 1 == 0 ? 0 : 2)} lots';
    }
    return '$quantity qty';
  }

  String _stopDisplay(Map<String, dynamic> r) {
    final stop = _v(r, 'stop_loss');
    final trailing = r['trailing_stop'];
    final history = r['trail_history'];
    if (trailing != null || (history is List && history.isNotEmpty)) {
      if (history is List && history.isNotEmpty && history.last is Map) {
        final last = history.last as Map;
        final milestone = last['milestone_gain_pct'];
        final locked = last['locked_gain_pct'];
        final steps = history.length;
        return '$stop • 🔒 +${milestone ?? '—'}% HIT • LOCK +${locked ?? '—'}% • $steps STEP(S)';
      }
      return '$stop • 🔒 TRAILED';
    }
    return stop;
  }

  String _targets(Map<String, dynamic> r) {
    final values = [r['target_1'], r['target_2'], r['target_3']]
        .where((value) => value != null).map((value) => value.toString()).toList();
    return values.isEmpty ? '—' : values.join(' / ');
  }

  String _pnlDisplay(Map<String, dynamic> r) {
    final points = r['pnl_points'];
    final pct = r['pnl_pct'];
    final rupees = r['pnl_rupees'];
    final parts = <String>[];
    if (points != null) parts.add('$points pts');
    if (pct != null) parts.add('$pct%');
    if (rupees != null) parts.add('₹$rupees');
    return parts.isEmpty ? '—' : parts.join(' • ');
  }

  String _evidenceDisplay(Map<String, dynamic> r) {
    final evidence = r['evidence'];
    if (evidence is! Map) return '—';
    final underlying = evidence['underlying_confirmation'] ??
        evidence['latest_underlying_confirmation'] ?? evidence['underlying'];
    final option = evidence['option_confirmation'] ??
        evidence['latest_option_confirmation'] ?? evidence['option'];
    final parts = <String>[];
    if (underlying != null) parts.add('Underlying: $underlying');
    if (option != null) parts.add('Option: $option');
    if (evidence['source'] != null) parts.add('Source: ${evidence['source']}');
    if (r['cohort_id'] != null) parts.add('Cohort: ${r['cohort_id']}');
    if (evidence['source_bhavcopy'] != null) parts.add('Bhavcopy: ${evidence['source_bhavcopy']}');
    if (evidence['daily_rows'] != null) parts.add('Daily rows: ${evidence['daily_rows']}');
    if (evidence['expiry_status_reason'] != null) parts.add(evidence['expiry_status_reason'].toString());
    if (evidence['observed_at'] != null) parts.add('Observed: ${evidence['observed_at']}');
    return parts.isEmpty ? '—' : parts.join(' | ');
  }

  String _physicalForecastDisplay(Map<String, dynamic> r) {
    final forecast = r['physical_settlement_forecast'];
    if (forecast is! Map) return 'UNKNOWN • forecast unavailable';
    final risk = forecast['physical_settlement_risk']?.toString() ?? 'UNKNOWN';
    final itm = forecast['forecast_itm']?.toString() ?? 'UNKNOWN';
    final probability = forecast['itm_probability_pct'];
    final price = forecast['forecast_stock_price'];
    final direction = forecast['delivery_direction_if_itm']?.toString() ?? '—';
    final status = forecast['forecast_status']?.toString() ?? '';
    final parts = <String>[risk, 'ITM: $itm'];
    if (probability != null) parts.add('P(ITM): $probability%');
    if (price != null) parts.add('Expiry est: ₹$price');
    parts.add(direction);
    if (status == 'INSUFFICIENT_UNDERLYING_OHLCV') parts.add('Underlying OHLCV missing');
    return parts.join(' • ');
  }

  String _physicalDeliveryAlertDisplay(Map<String, dynamic> r) {
    final setup = r['physical_delivery_at_setup'];
    final entry = r['physical_delivery_at_entry'];
    final current = r['physical_delivery_current'];
    if (current is! Map) return '⚪ DATA REQUIRED';
    final icon = current['icon']?.toString() ?? '⚪';
    final status = current['status']?.toString() ?? 'UNKNOWN';
    final setupStatus = setup is Map ? (setup['status']?.toString() ?? 'UNKNOWN') : 'UNKNOWN';
    final entryStatus = entry is Map ? (entry['status']?.toString() ?? 'UNKNOWN') : 'UNKNOWN';
    final distance = current['distance_to_strike_pct'];
    final dte = current['days_to_expiry'];
    final qualified = current['qualified'] == true;
    final parts = <String>[
      '$icon $status',
      if (qualified) '🟢 PHYSICAL SETTLEMENT QUALIFIED',
      'Setup: $setupStatus',
      'Entry: $entryStatus',
    ];
    if (distance != null) parts.add('Strike gap: $distance%');
    if (dte != null) parts.add('DTE: $dte');
    return parts.join(' • ');
  }

  DataRow _row(Map<String, dynamic> r) {
    final survivor = _isSurvivor(r);
    final dte = r['days_to_expiry'];
    final status = _v(r, 'position_status');
    final instrument = (r['instrument_type'] ?? '—').toString().toUpperCase();
    final cells = [
      _cell(_v(r, 'signal_date')),
      _cell(_v(r, 'entry_date')),
      _cell(_classificationLabel(r)),
      _cell(instrument),
      _cell('${r['physical_delivery_icon'] ?? ''} ${_v(r, 'symbol')}'),
      _cell(_v(r, 'sector')),
      _cell(_v(r, 'option_type')),
      _cell(_v(r, 'strike')),
      _cell(_v(r, 'expiry')),
      _cell(_v(r, 'entry_price') == '—' ? (r['entry_limit']?.toString() ?? '—') : _v(r, 'entry_price')),
      _cell(_v(r, 'latest_price')),
      _cell(_quantityLots(r)),
      _cell(_stopDisplay(r)),
      _cell(_targets(r)),
      _cell(_pnlDisplay(r)),
      _cell(dte == null ? '—' : '$dte calendar days'),
      _cell(status),
      if (_sections[_selected] == 'EXPIRY78') _cell(_physicalDeliveryAlertDisplay(r)),
      if (_sections[_selected] == 'EXPIRY78') _cell(_physicalForecastDisplay(r)),
      _cell(_evidenceDisplay(r)),
    ];
    final deliveryCurrent = r['physical_delivery_current'];
    final deliveryCritical = deliveryCurrent is Map && deliveryCurrent['status'] == 'CRITICAL';
    final deliveryQualified = r['physical_delivery_qualified'] == true;
    return DataRow(
      color: WidgetStateProperty.resolveWith<Color?>((states) {
        if (deliveryCritical) return Theme.of(context).colorScheme.errorContainer.withValues(alpha: 0.48);
        if (deliveryQualified) return Theme.of(context).colorScheme.tertiaryContainer.withValues(alpha: 0.45);
        if (survivor) return Theme.of(context).colorScheme.tertiary.withValues(alpha: 0.18);
        return null;
      }),
      cells: cells.map((cell) => DataCell(cell)).toList(),
    );
  }


  String _money(dynamic value) => value is num
      ? '₹${value.toStringAsFixed(2)}' : '—';

  Future<void> _changeCalendarMonth(int delta) async {
    final next = DateTime(_calendarMonth.year, _calendarMonth.month + delta);
    setState(() { _calendarMonth = next; _calendarLoading = true; });
    try {
      final result = await _api.modelEnginePnlCalendar(year: next.year, month: next.month);
      if (mounted) setState(() => _pnlCalendar = result);
    } catch (e) {
      if (mounted) setState(() => _error = 'P&L calendar: $e');
    } finally {
      if (mounted) setState(() => _calendarLoading = false);
    }
  }

  void _showPnlDate(DateTime date) {
    final key = '${date.year.toString().padLeft(4, '0')}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';
    final all = (_pnlCalendar['trades'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .where((trade) => trade['entry_date'] == key || trade['exit_date'] == key)
        .toList();
    all.addAll(((_pnlCalendar['physical_settlement'] as Map?)?['rows'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>().where((trade) => trade['exit_date'] == key));
    final dayRows = (_pnlCalendar['days'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>().where((row) => row['date'] == key).toList();
    final day = dayRows.isEmpty ? <String, dynamic>{} : dayRows.first;
    showDialog<void>(context: context, builder: (context) => AlertDialog(
      title: Text('TRADE HISTORY • $key'),
      content: SizedBox(width: 620, child: SingleChildScrollView(child: Column(
        crossAxisAlignment: CrossAxisAlignment.start, children: [
          Wrap(spacing: 8, runSpacing: 8, children: [
            _settlementMetric('GROSS P&L • EXIT DATE', _money(day['gross_pnl'])),
            _settlementMetric('CHARGES', _money(day['estimated_or_actual_charges'])),
            _settlementMetric('NET P&L', _money(day['net_pnl'])),
            _settlementMetric('CAPITAL DEPLOYED • ENTRY DATE', _money(day['capital_deployed'])),
          ]),
          const SizedBox(height: 10),
          Text('Trades entered or exited on this date: ${all.length}', style: const TextStyle(fontWeight: FontWeight.w800)),
          const SizedBox(height: 8),
          ...all.map((trade) {
            final charge = trade['charges'] is Map ? trade['charges'] as Map : const {};
            final components = charge['components'] is Map ? charge['components'] as Map : const {};
            return Card(child: Padding(padding: const EdgeInsets.all(10), child: Column(
              crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${trade['strategy'] ?? '—'} • ${trade['symbol'] ?? '—'} ${trade['option_type'] ?? ''} ${trade['strike'] ?? ''}',
                  style: const TextStyle(fontWeight: FontWeight.w900)),
                Text('Entry ${trade['entry_date'] ?? '—'} @ ₹${trade['entry_price'] ?? '—'} • Qty ${trade['quantity'] ?? '—'} • Capital ${_money(trade['capital_deployed'])}',
                  style: const TextStyle(fontSize: 11)),
                Text('Exit ${trade['exit_date'] ?? 'OPEN'} @ ₹${trade['exit_price'] ?? '—'} • ${trade['classification'] ?? '—'}',
                  style: const TextStyle(fontSize: 11)),
                if (trade['expiry_outcome'] != null)
                  Text('EXPIRY RESULT • ${trade['expiry_outcome']}',
                    style: TextStyle(fontSize: 10, fontWeight: FontWeight.w900,
                      color: trade['expiry_outcome'] == 'EXPIRED_WIN' ? Colors.green :
                        trade['expiry_outcome'] == 'EXPIRED_LOSS' ? Colors.red :
                        Theme.of(context).colorScheme.onSurfaceVariant)),
                const Divider(),
                Text('Gross ${_money(trade['gross_pnl'])}  |  Charges ${_money(charge['total'])}  |  Net ${_money(trade['net_pnl'])}',
                  style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 12)),
                if (components.isNotEmpty) ...[
                  const SizedBox(height: 5),
                  const Text('CHARGES BREAKUP', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 10)),
                  ...components.entries.map((entry) => Padding(
                    padding: const EdgeInsets.symmetric(vertical: 1),
                    child: Row(children: [
                      Expanded(child: Text(entry.key.toString().replaceAll('_', ' ').toUpperCase(), style: const TextStyle(fontSize: 10))),
                      Text(_money(entry.value), style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700)),
                    ]),
                  )),
                  Text('Basis: ${charge['basis'] ?? '—'}', style: const TextStyle(fontSize: 9, fontStyle: FontStyle.italic)),
                ] else
                  const Text('Charges / quantity / exit valuation not available; net P&L remains unverified.',
                    style: TextStyle(fontSize: 10)),
              ],
            )));
          }),
          if (all.isEmpty) const Text('No trade entries or exits recorded for this date.'),
        ],
      ))),
      actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('CLOSE'))],
    ));
  }

  Widget _pnlCalendarView() {
    final summary = _pnlCalendar['summary'] is Map
        ? _pnlCalendar['summary'] as Map : const {};
    final overall = summary['overall'] is Map ? summary['overall'] as Map : const {};
    final expiry = summary['EXPIRY78'] is Map ? summary['EXPIRY78'] as Map : const {};
    final recovered = summary['RECOVERED'] is Map ? summary['RECOVERED'] as Map : const {};
    final recovery = summary['RECOVERY'] is Map ? summary['RECOVERY'] as Map : const {};
    final physical = summary['PHYSICAL_SETTLEMENT'] is Map ? summary['PHYSICAL_SETTLEMENT'] as Map : const {};
    final monthRows = (_pnlCalendar['months'] as List<dynamic>? ?? const []).whereType<Map<String, dynamic>>();
    final monthKey = '${_calendarMonth.year.toString().padLeft(4, '0')}-${_calendarMonth.month.toString().padLeft(2, '0')}';
    final month = monthRows.firstWhere((r) => r['month'] == monthKey, orElse: () => <String, dynamic>{});
    final days = (_pnlCalendar['days'] as List<dynamic>? ?? const []).whereType<Map<String, dynamic>>();
    final dayMap = {for (final row in days) row['date'].toString(): row};
    final firstWeekday = DateTime(_calendarMonth.year, _calendarMonth.month, 1).weekday % 7;
    final count = DateTime(_calendarMonth.year, _calendarMonth.month + 1, 0).day;
    final cells = <Widget>[];
    for (var i = 0; i < firstWeekday; i++) { cells.add(const SizedBox(height: 86)); }
    for (var d = 1; d <= count; d++) {
      final date = DateTime(_calendarMonth.year, _calendarMonth.month, d);
      final key = '${date.year.toString().padLeft(4, '0')}-${date.month.toString().padLeft(2, '0')}-${d.toString().padLeft(2, '0')}';
      final row = dayMap[key] ?? const {};
      final gross = row['gross_pnl'];
      final net = row['net_pnl'];
      final cap = row['capital_deployed'];
      cells.add(InkWell(onTap: () => _showPnlDate(date), child: Container(
        height: 86, padding: const EdgeInsets.all(5),
        decoration: BoxDecoration(border: Border.all(color: Theme.of(context).colorScheme.outlineVariant), borderRadius: BorderRadius.circular(7)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('$d', style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 11)),
          if (gross != null && gross != 0) Text('G ${_money(gross)}', maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 8)),
          if (net != null && net != 0) Text('N ${_money(net)}', maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 8, fontWeight: FontWeight.w800, color: (net as num) >= 0 ? Colors.green : Colors.red)),
          if (cap != null && cap != 0) Text('C ${_money(cap)}', maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 8)),
          if ((row['physical_settlement_contracts'] ?? 0) != 0) Text('PS G ${_money(row['physical_settlement_gross_pnl'])}', maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 8)),
          if ((row['expired_contract_count'] ?? 0) != 0)
            Text('EXP ${row['expired_wins'] ?? 0}W/${row['expired_losses'] ?? 0}L',
              maxLines: 1, overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 7, fontWeight: FontWeight.w800)),
          if ((row['trade_count'] ?? 0) != 0 || (row['entries_count'] ?? 0) != 0)
            Text('Trades ${row['trade_count'] ?? 0} • Entry ${row['entries_count'] ?? 0}', maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 7)),
        ]),
      )));
    }
    while (cells.length % 7 != 0) { cells.add(const SizedBox(height: 86)); }
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Card(child: Padding(padding: const EdgeInsets.all(12), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('AIR • P&L CALENDAR', style: TextStyle(fontWeight: FontWeight.w900, fontSize: 14)),
        const SizedBox(height: 5),
        const Text('Realized P&L is assigned to exit date. Capital deployed is assigned to entry date. Expired contracts remain in strategy trade history with win/loss/breakeven outcomes after their market-data rows are cleaned. Tap any date for trade history and charge details.', style: TextStyle(fontSize: 10)),
        const SizedBox(height: 10),
        Wrap(spacing: 8, runSpacing: 8, children: [
          _settlementMetric('CUMULATIVE CAPITAL DEPLOYED', _money(overall['capital_deployed'])),
          _settlementMetric('PEAK CONCURRENT CAPITAL', _money(overall['peak_concurrent_capital'])),
          _settlementMetric('GROSS REALIZED', _money(overall['gross_pnl'])),
          _settlementMetric('CHARGES', _money(overall['estimated_or_actual_charges'])),
          _settlementMetric('NET REALIZED', _money(overall['net_pnl'])),
          _settlementMetric('EXPIRED CONTRACTS', overall['expired_contract_count'] ?? 0),
          _settlementMetric('EXPIRY WINS / LOSSES',
            '${overall['expired_wins'] ?? 0} / ${overall['expired_losses'] ?? 0}'),
        ]),
        Text('Expiry breakeven: ${overall['expired_breakeven'] ?? 0} • Expiry P&L pending: ${overall['expired_pnl_pending'] ?? 0} • Missing net values: ${overall['net_pending_count'] ?? 0} trades • Estimated charges: ${overall['charges_estimated_count'] ?? 0} • Actual charge records: ${overall['charges_actual_count'] ?? 0}',
          style: const TextStyle(fontSize: 9)),
      ]))),
      Card(child: Padding(padding: const EdgeInsets.all(10), child: Column(children: [
        Row(children: [
          IconButton(onPressed: _calendarLoading ? null : () => _changeCalendarMonth(-1), icon: const Icon(Icons.chevron_left)),
          Expanded(child: Text(monthKey, textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 15))),
          IconButton(onPressed: _calendarLoading ? null : () => _changeCalendarMonth(1), icon: const Icon(Icons.chevron_right)),
        ]),
        if (_calendarLoading) const LinearProgressIndicator(),
        Row(children: ['SUN','MON','TUE','WED','THU','FRI','SAT'].map((d) =>
          Expanded(child: Center(child: Text(d, style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w800))))).toList()),
        const SizedBox(height: 5),
        GridView.count(crossAxisCount: 7, shrinkWrap: true, physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: 3, crossAxisSpacing: 3, childAspectRatio: 0.82, children: cells),
      ]))),
      Card(child: Padding(padding: const EdgeInsets.all(10), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('MONTH SUMMARY • $monthKey', style: const TextStyle(fontWeight: FontWeight.w900)),
        const SizedBox(height: 6),
        Wrap(spacing: 8, runSpacing: 8, children: [
          _settlementMetric('CAPITAL DEPLOYED', _money(month['capital_deployed'])),
          _settlementMetric('GROSS', _money(month['gross_pnl'])),
          _settlementMetric('CHARGES', _money(month['estimated_or_actual_charges'])),
          _settlementMetric('NET', _money(month['net_pnl'])),
          _settlementMetric('EXPIRED W / L',
            '${month['expired_wins'] ?? 0} / ${month['expired_losses'] ?? 0}'),
        ]),
      ]))),
      Card(child: Padding(padding: const EdgeInsets.all(10), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('STRATEGY-WISE', style: TextStyle(fontWeight: FontWeight.w900)),
        Text('EXPIRY78 • Capital ${_money(expiry['capital_deployed'])} • Gross ${_money(expiry['gross_pnl'])} • Charges ${_money(expiry['estimated_or_actual_charges'])} • Net ${_money(expiry['net_pnl'])} • Expiry W/L ${expiry['expired_wins'] ?? 0}/${expiry['expired_losses'] ?? 0}', style: const TextStyle(fontSize: 10)),
        Text('RECOVERED • Capital ${_money(recovered['capital_deployed'])} • Gross ${_money(recovered['gross_pnl'])} • Charges ${_money(recovered['estimated_or_actual_charges'])} • Net ${_money(recovered['net_pnl'])} • Expiry W/L ${recovered['expired_wins'] ?? 0}/${recovered['expired_losses'] ?? 0}', style: const TextStyle(fontSize: 10)),
        Text('RECOVERY • Capital ${_money(recovery['capital_deployed'])} • Gross ${_money(recovery['gross_pnl'])} • Charges ${_money(recovery['estimated_or_actual_charges'])} • Net ${_money(recovery['net_pnl'])} • Expiry W/L ${recovery['expired_wins'] ?? 0}/${recovery['expired_losses'] ?? 0}', style: const TextStyle(fontSize: 10)),
        const Divider(),
        Text('PHYSICAL SETTLEMENT • ${physical['contract_count'] ?? 0} contracts • Capital ${_money(physical['capital_deployed'])} • Source gross ${_money(physical['gross_pnl'])} • Charges PENDING • Net PENDING',
          style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w800)),
      ]))),
      Card(child: Padding(padding: const EdgeInsets.all(10), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('ESTIMATED CHARGES MODEL', style: TextStyle(fontWeight: FontWeight.w900)),
        ...((_pnlCalendar['charge_model'] as Map?)?['notes'] as List<dynamic>? ?? const [])
            .map((note) => Padding(padding: const EdgeInsets.symmetric(vertical: 2), child: Text('• $note', style: const TextStyle(fontSize: 9)))),
        const Text('Broker contract-note charges override estimates. Physical settlement charges are separately reviewed and excluded from these strategy totals.', style: TextStyle(fontSize: 9, fontWeight: FontWeight.w700)),
      ]))),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final selectedSection = _sections[_selected];
    final pnlSelected = selectedSection == 'P&L CALENDAR';
    final expirySelected = selectedSection == 'EXPIRYSCAN';
    final settlementSelected = selectedSection == 'PHYSICAL SETTLEMENT';
    final strategySelected = _strategyTabs.contains(selectedSection);
    final strategyData = _strategies[_strategyKey(selectedSection)] as Map<String, dynamic>?;
    final strategyGroups = strategyData?['groups'] as Map<String, dynamic>?;
    final strategyRows = strategyGroups == null ? null : strategyGroups[_strategyStatus];
    final selectedRows = strategySelected ? strategyRows : _groups[selectedSection];
    final rows = (selectedRows as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>().toList();
    return Scaffold(
      appBar: AppBar(title: const Text('AIR MODEL ENGINE'),
        actions: [IconButton(tooltip: 'Refresh ledger',
          onPressed: !_authenticated || _loading ? null : _refresh,
          icon: const Icon(Icons.refresh_rounded))]),
      body: ListView(padding: const EdgeInsets.all(14), children: [
        if (!_authenticated) Card(child: Padding(
          padding: const EdgeInsets.all(16), child: Column(children: [
            const Icon(Icons.lock_outline_rounded, size: 28),
            const SizedBox(height: 8),
            const Text('AIR MOBILE APPROVAL REQUIRED', style: TextStyle(fontWeight: FontWeight.w900)),
            const SizedBox(height: 6),
            const Text('Sign in once through the main AIR mobile approval screen. Model Engine uses that shared session and does not request a second login.', textAlign: TextAlign.center, style: TextStyle(fontSize: 11)),
          ]),
        )) else ...[
          Card(child: Padding(padding: const EdgeInsets.all(12), child: Column(
            crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                const Expanded(child: Text('AIR MASTER • SIGNAL & POSITION LIFECYCLE', style: TextStyle(fontWeight: FontWeight.w900, fontSize: 12))),
                Text(_dataStatus, style: TextStyle(fontSize: 9, color: cs.primary, fontWeight: FontWeight.w800)),
              ]),
              const SizedBox(height: 5),
              Text('Updated: ${_updatedAt ?? 'No verified records yet'} • shared AIR session • auto-refresh 5 min',
                style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
              const SizedBox(height: 4),
              Text(
                'HISTORY: ${(_marketDataSource['historical_source'] as Map?)?['provider'] ?? 'NSE EOD'}'
                '  •  LIVE: ${(_marketDataSource['live_source'] as Map?)?['provider'] ?? 'NOT CONNECTED'}',
                style: TextStyle(fontSize: 9, color: cs.onSurfaceVariant, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 8),
              Text('OPEN ${_summary['open'] ?? 0}  •  NEW ${_summary['new'] ?? 0}  •  HOLD ${_summary['hold'] ?? 0}  •  REENTRY ${_summary['reentry'] ?? 0}  •  SURVIVOR ${_summary['survivor_watch'] ?? 0}  •  SLHIT ${_summary['slhit'] ?? 0}',
                style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
              const SizedBox(height: 4),
              Text('INDEX ${(_breakdowns['instrument_type'] as Map<String, dynamic>?)?['INDEX'] ?? 0}  •  STOCK ${(_breakdowns['instrument_type'] as Map<String, dynamic>?)?['STOCK'] ?? 0}  •  SECTORS ${(_breakdowns['sector'] as Map<String, dynamic>?)?.length ?? 0}',
                style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
              const SizedBox(height: 10),
              Wrap(spacing: 7, runSpacing: 7, children: _sections.map((s) => ChoiceChip(
                label: Text('$s  ${_tabCount(s)}', style: const TextStyle(fontSize: 10)),
                selected: _sections[_selected] == s,
                onSelected: (_) => setState(() {
                  _selected = _sections.indexOf(s);
                  _strategyStatus = s == 'RECOVERED' ? 'OPEN' : 'OPEN';
                }),
              )).toList()),
            ],
          ))),
          const SizedBox(height: 10),
          if (pnlSelected) _pnlCalendarView(),
          if (strategySelected) ...[
            if (strategyData?['rules'] is Map) Card(child: Padding(
              padding: const EdgeInsets.all(12), child: Text(
                (strategyData!['rules'] as Map)['qualification']?.toString() ?? '',
                style: TextStyle(fontSize: 10, height: 1.35, color: cs.onSurfaceVariant),
              ),
            )),
            if (selectedSection == 'RECOVERED' && strategyData?['baseline'] is Map) Card(child: Padding(
              padding: const EdgeInsets.all(12), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('RECOVERED • ORIGINAL366 COHORT FILTER', style: TextStyle(fontWeight: FontWeight.w900, fontSize: 11)),
                const SizedBox(height: 6),
                Text('534 original entries → 366 full-expiry-coverage records', style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
                Text('83 partial-coverage excluded • 85 no post-entry data excluded', style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
                Text('366 original 5% SL hits: 274 same-day • 69 later-session • 23 gap/open', style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
                Text('RECOVERED trigger: post-SL daily CLOSE above original entry. Alternative replay uses that SAME entry: 10% SL / 45% target; same-candle conflict = SL first.', style: TextStyle(fontSize: 10, color: cs.primary)),
                Text('OPEN / TARGETS / SLHIT / EXPIRED are alternative-model outcomes. Original 5% SL history remains separately preserved.', style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
              ]),
            )),
            Wrap(spacing: 7, runSpacing: 7, children: (selectedSection == 'RECOVERED'
              ? ['OPEN', 'TARGETS', 'SLHIT', 'EXPIRED', 'WAIT']
              : ['OPEN', 'NEW', 'HOLD', 'WAIT', 'SLHIT', 'REENTRY']).map((status) => ChoiceChip(
              label: Text('$status  ${((strategyData?['counts'] as Map?)?[status] ?? 0)}', style: const TextStyle(fontSize: 10)),
              selected: _strategyStatus == status,
              onSelected: (_) => setState(() => _strategyStatus = status),
            )).toList()),
          ],
          if (_sections[_selected] == 'WAIT' && !strategySelected) Padding(padding: const EdgeInsets.all(8), child: Text('WAIT is reserved for candidates explicitly marked pending by a verified workflow. Missing data is never treated as WAIT.', style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant))),
          if (settlementSelected) ...[
            Card(child: Padding(padding: const EdgeInsets.all(12), child: Column(
              crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('EXPIRY78 • PHYSICAL DELIVERY REVIEW', style: TextStyle(fontWeight: FontWeight.w900, fontSize: 12)),
                const SizedBox(height: 6),
                Text('27-Oct-2026 expiry • 13 stock-option expiry outcomes from the 45-contract backtest',
                  style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
                const SizedBox(height: 8),
                Wrap(spacing: 8, runSpacing: 8, children: [
                  _settlementMetric('TAKE SHARES IF CALLS ITM', _settlementSummary['take_delivery_share_quantity_if_all_calls_itm']),
                  _settlementMetric('GIVE SHARES IF PUTS ITM', _settlementSummary['give_delivery_share_quantity_if_all_puts_itm']),
                  _settlementMetric('CALL FUNDS PAYABLE', _settlementSummary['provisional_call_funds_payable_if_itm']),
                  _settlementMetric('PUT FUNDS RECEIVABLE', _settlementSummary['provisional_put_funds_receivable_if_itm']),
                ]),
                const SizedBox(height: 8),
                Text('PROVISIONAL • Underlying expiry closes are not attached. No contract is marked verified ITM. Strike-value amounts are conditional estimates, not confirmed pay-in/pay-out.',
                  style: TextStyle(fontSize: 10, color: cs.error, fontWeight: FontWeight.w700)),
                if (_settlementNote != null) Text(_settlementNote!, style: TextStyle(fontSize: 9, color: cs.onSurfaceVariant)),
              ],
            ))),
            if (_settlementRows.isNotEmpty) Card(child: SingleChildScrollView(scrollDirection: Axis.horizontal,
              child: DataTable(columns: const [
                DataColumn(label: Text('SYMBOL')), DataColumn(label: Text('CE/PE')),
                DataColumn(label: Text('STRIKE')), DataColumn(label: Text('QTY SHARES')),
                DataColumn(label: Text('ENTRY PREMIUM')), DataColumn(label: Text('SOURCE EXIT VALUE')),
                DataColumn(label: Text('DELIVERY IF ITM')), DataColumn(label: Text('STRIKE NOTIONAL')),
                DataColumn(label: Text('ITM CHECK')), DataColumn(label: Text('STATUS')),
              ], rows: _settlementRows.map((r) => DataRow(cells: [
                DataCell(_cell(_v(r, 'symbol'))),
                DataCell(_cell(_v(r, 'option_type'))),
                DataCell(_cell(_v(r, 'strike'))),
                DataCell(_cell(_v(r, 'quantity_shares'))),
                DataCell(_cell(_v(r, 'entry_premium'))),
                DataCell(_cell(_v(r, 'source_recorded_expiry_value'))),
                DataCell(_cell(_v(r, 'delivery_direction_if_itm'))),
                DataCell(_cell(_v(r, 'funds_obligation_at_strike_if_itm'))),
                DataCell(_cell(_v(r, 'itm_status'))),
                DataCell(_cell(_v(r, 'settlement_status'))),
              ])).toList()))),
          ],
          if (expirySelected && _expiryNote != null) Padding(padding: const EdgeInsets.all(8), child: Text(_expiryNote!, style: const TextStyle(fontSize: 11))),
          if (_expiryAlerts.isNotEmpty) Card(child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('EXPIRYSCAN • CLOSE-BEFORE-EXPIRY REMINDERS', style: TextStyle(fontWeight: FontWeight.w900, fontSize: 11)),
              const SizedBox(height: 6),
              ..._expiryAlerts.map((r) => Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Text(
                  '${r['symbol']} ${r['option_type']} ${r['strike']} • Expiry ${r['expiry']} • Review/close before expiry',
                  style: TextStyle(fontSize: 10, color: cs.error, fontWeight: FontWeight.w700),
                ),
              )),
              const Text('Reminder is shown on the prior weekday when the app refreshes. Exchange holidays are not yet calendar-adjusted. No order is placed.', style: TextStyle(fontSize: 9)),
            ]),
          )),
          if (expirySelected && _expiryRows.isNotEmpty) Card(child: SingleChildScrollView(scrollDirection: Axis.horizontal,
            child: DataTable(columns: const [
              DataColumn(label: Text('CLASSIFICATION')), DataColumn(label: Text('PRIORITY')), DataColumn(label: Text('UNDERLYING ID')),
              DataColumn(label: Text('CE/PE')), DataColumn(label: Text('EXPIRY')),
              DataColumn(label: Text('STRIKE')), DataColumn(label: Text('DTE')),
              DataColumn(label: Text('PREMIUM')), DataColumn(label: Text('VOLUME')),
              DataColumn(label: Text('OI')), DataColumn(label: Text('OI CHANGE')),
              DataColumn(label: Text('BID')), DataColumn(label: Text('ASK')),
              DataColumn(label: Text('SPREAD %')), DataColumn(label: Text('SCAN STATUS')),
              DataColumn(label: Text('OBSERVED AT')),
            ], rows: _expiryRows.map((r) => DataRow(
              color: r['survivor'] == true ? WidgetStateProperty.all(cs.tertiary.withValues(alpha: 0.18)) : null,
              cells: [
                DataCell(_cell(_v(r, 'classification'))),
                _v(r, 'survivor') == 'true' ? DataCell(_cell('★ SURVIVOR')) : DataCell(_cell('STANDARD')),
                for (final key in ['underlying_scrip','option_type','expiry','strike','days_to_expiry',
                  'last_price','volume','open_interest','oi_change','bid_price','ask_price','spread_pct',
                  'scan_status','observed_at']) DataCell(_cell(_v(r, key))),
              ],
            )).toList()))),
          if (!pnlSelected && !settlementSelected && ((!expirySelected && rows.isEmpty) || (expirySelected && _expiryRows.isEmpty))) Card(child: Padding(padding: const EdgeInsets.all(18),
            child: Column(children: [
              Icon(Icons.hourglass_empty_rounded, size: 28, color: cs.onSurfaceVariant),
              const SizedBox(height: 8),
              Text('No verified ${strategySelected ? '$selectedSection / $_strategyStatus' : selectedSection} records', style: const TextStyle(fontWeight: FontWeight.w800)),
              const SizedBox(height: 5),
              Text('This section populates only from persisted verified records. No invented sample trades are displayed.',
                textAlign: TextAlign.center, style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
            ]),
          )) else if (!pnlSelected && !expirySelected && !settlementSelected) Card(child: SingleChildScrollView(scrollDirection: Axis.horizontal,
            child: DataTable(columnSpacing: 14, headingRowHeight: 38,
              dataRowMinHeight: 38, dataRowMaxHeight: 52,
              columns: _columns, rows: rows.map(_row).toList()))),
        ],
        if (_loading) const Padding(padding: EdgeInsets.symmetric(vertical: 10), child: LinearProgressIndicator()),
        if (_error != null) Padding(padding: const EdgeInsets.only(top: 10),
          child: Text(_error!, style: TextStyle(color: cs.error, fontSize: 11))),
        const SizedBox(height: 12),
        Text('AIR MASTER keeps strategy membership isolated. EXPIRY78 applies its seven-rule expiry-survivor lifecycle; RECOVERED is the ORIGINAL366 reference cohort (366 of 534) and adds a watch-only row after a post-SL daily option close above original entry premium; RECOVERY remains a separate re-entry strategy. OPEN = NEW + HOLD. No automatic order placement.',
          style: TextStyle(fontSize: 10, height: 1.4, color: cs.onSurfaceVariant)),
      ]),
    );
  }
}
