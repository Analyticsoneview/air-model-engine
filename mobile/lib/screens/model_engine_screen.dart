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
  static const _sections = ['OPEN', 'NEW', 'HOLD', 'REENTRY', 'SURVIVOR', 'WAIT', 'SLHIT', 'TARGETS', 'EXPIRED', 'EXPIRYSCAN', 'COMBINED'];
  Map<String, dynamic> _groups = {};
  Map<String, dynamic> _counts = {};
  Map<String, dynamic> _summary = {};
  Map<String, dynamic> _breakdowns = {};
  List<Map<String, dynamic>> _expiryRows = [];
  String? _expiryNote;
  int _selected = 0;
  bool _authenticated = false, _loading = false;
  Timer? _autoRefreshTimer;
  String? _error, _updatedAt;
  String _dataStatus = 'SIGN IN TO LOAD YOUR MODEL ENGINE LEDGER';

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
      try { expiryResult = await _api.expiryScan(); }
      catch (e) { _expiryNote = 'EXPIRYSCAN unavailable: $e'; }
      if (!mounted) return;
      setState(() {
        _groups = result['groups'] as Map<String, dynamic>? ?? {};
        if (expiryResult != null) {
          _expiryRows = (expiryResult['rows'] as List<dynamic>? ?? const [])
              .whereType<Map<String, dynamic>>().toList();
          _expiryNote = expiryResult['note']?.toString();
        }
        _counts = result['counts'] as Map<String, dynamic>? ?? {};
        _summary = result['summary'] as Map<String, dynamic>? ?? {};
        _breakdowns = result['breakdowns'] as Map<String, dynamic>? ?? {};
        _updatedAt = result['updated_at']?.toString();
        _dataStatus = result['data_status']?.toString() ?? 'UNKNOWN';
      });
    } catch (e) { if (mounted) setState(() => _error = e.toString()); }
    finally { if (mounted) setState(() => _loading = false); }
  }

  String _v(Map<String, dynamic> row, String key) => row[key] == null ? '—' : row[key].toString();
  Widget _cell(String value) => Padding(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 9),
    child: Text(value, style: const TextStyle(fontSize: 10)),
  );

  List<DataColumn> get _columns => const [
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
    DataColumn(label: Text('LATEST EVIDENCE')),
  ];

  bool _isSurvivor(Map<String, dynamic> r) =>
      r['survivor_eligible'] == true;

  String _classificationLabel(Map<String, dynamic> r) {
    switch ((r['classification'] ?? '').toString().toUpperCase()) {
      case 'NEW': return '🆕 NEW';
      case 'HOLD': return '📌 HOLD';
      case 'RE-ENTRY': return '🔁 RE-ENTRY';
      case 'SL': return 'SL HIT';
      case 'TARGETS': return 'TARGET HIT';
      case 'EXPIRED': return 'EXPIRED';
      default: return _v(r, 'classification');
    }
  }

  String _quantityLots(Map<String, dynamic> r) {
    final quantity = r['quantity'];
    final lotSize = r['lot_size'];
    if (quantity == null) return '—';
    if (lotSize is num && lotSize > 0 && quantity is num) {
      final lots = quantity / lotSize;
      return '${quantity} qty / ${lots.toStringAsFixed(lots % 1 == 0 ? 0 : 2)} lots';
    }
    return '${quantity} qty';
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
    if (points != null) parts.add('${points} pts');
    if (pct != null) parts.add('${pct}%');
    if (rupees != null) parts.add('₹${rupees}');
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
    return parts.isEmpty ? '—' : parts.join(' | ');
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
      _cell(_v(r, 'symbol')),
      _cell(_v(r, 'sector')),
      _cell(_v(r, 'option_type')),
      _cell(_v(r, 'strike')),
      _cell(_v(r, 'expiry')),
      _cell(_v(r, 'entry_price')),
      _cell(_v(r, 'latest_price')),
      _cell(_quantityLots(r)),
      _cell(_v(r, 'stop_loss')),
      _cell(_targets(r)),
      _cell(_pnlDisplay(r)),
      _cell(dte == null ? '—' : '${dte} calendar days'),
      _cell(status),
      _cell(_evidenceDisplay(r)),
    ];
    return DataRow(
      color: survivor
          ? WidgetStateProperty.resolveWith<Color?>((states) =>
              Theme.of(context).colorScheme.tertiary.withValues(alpha: 0.18))
          : null,
      cells: cells.map((cell) => DataCell(cell)).toList(),
    );
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final expirySelected = _sections[_selected] == 'EXPIRYSCAN';
    final rows = (_groups[_sections[_selected]] as List<dynamic>? ?? const [])
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
              const SizedBox(height: 8),
              Text('OPEN ${_summary['open'] ?? 0}  •  NEW ${_summary['new'] ?? 0}  •  HOLD ${_summary['hold'] ?? 0}  •  REENTRY ${_summary['reentry'] ?? 0}  •  SURVIVOR ${_summary['survivor_watch'] ?? 0}  •  SLHIT ${_summary['slhit'] ?? 0}',
                style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
              const SizedBox(height: 4),
              Text('INDEX ${(_breakdowns['instrument_type'] as Map<String, dynamic>?)?['INDEX'] ?? 0}  •  STOCK ${(_breakdowns['instrument_type'] as Map<String, dynamic>?)?['STOCK'] ?? 0}  •  SECTORS ${(_breakdowns['sector'] as Map<String, dynamic>?)?.length ?? 0}',
                style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
              const SizedBox(height: 10),
              Wrap(spacing: 7, runSpacing: 7, children: _sections.map((s) => ChoiceChip(
                label: Text('$s  ${s == 'EXPIRYSCAN' ? _expiryRows.length : (_counts[s] ?? 0)}', style: const TextStyle(fontSize: 10)),
                selected: _sections[_selected] == s,
                onSelected: (_) => setState(() => _selected = _sections.indexOf(s)),
              )).toList()),
            ],
          ))),
          const SizedBox(height: 10),
          if (_sections[_selected] == 'WAIT') Padding(padding: const EdgeInsets.all(8), child: Text('WAIT is reserved for candidates explicitly marked pending by a verified workflow. Missing data is never treated as WAIT.', style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant))),
          if (expirySelected && _expiryNote != null) Padding(padding: const EdgeInsets.all(8), child: Text(_expiryNote!, style: const TextStyle(fontSize: 11))),
          if (expirySelected && _expiryRows.isNotEmpty) Card(child: SingleChildScrollView(scrollDirection: Axis.horizontal,
            child: DataTable(columns: const [
              DataColumn(label: Text('PRIORITY')), DataColumn(label: Text('UNDERLYING ID')),
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
                _v(r, 'survivor') == 'true' ? DataCell(_cell('★ SURVIVOR')) : DataCell(_cell('STANDARD')),
                for (final key in ['underlying_scrip','option_type','expiry','strike','days_to_expiry',
                  'last_price','volume','open_interest','oi_change','bid_price','ask_price','spread_pct',
                  'scan_status','observed_at']) DataCell(_cell(_v(r, key))),
              ],
            )).toList()))),
          if (!expirySelected && rows.isEmpty || expirySelected && _expiryRows.isEmpty) Card(child: Padding(padding: const EdgeInsets.all(18),
            child: Column(children: [
              Icon(Icons.hourglass_empty_rounded, size: 28, color: cs.onSurfaceVariant),
              const SizedBox(height: 8),
              Text('No verified ${_sections[_selected]} records', style: const TextStyle(fontWeight: FontWeight.w800)),
              const SizedBox(height: 5),
              Text('This section populates only from persisted verified records. No invented sample trades are displayed.',
                textAlign: TextAlign.center, style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
            ]),
          )) else if (!expirySelected) Card(child: SingleChildScrollView(scrollDirection: Axis.horizontal,
            child: DataTable(columnSpacing: 14, headingRowHeight: 38,
              dataRowMinHeight: 38, dataRowMaxHeight: 52,
              columns: _columns, rows: rows.map(_row).toList()))),
        ],
        if (_loading) const Padding(padding: EdgeInsets.symmetric(vertical: 10), child: LinearProgressIndicator()),
        if (_error != null) Padding(padding: const EdgeInsets.only(top: 10),
          child: Text(_error!, style: TextStyle(color: cs.error, fontSize: 11))),
        const SizedBox(height: 12),
        Text('AIR MASTER uses one canonical contract ledger. OPEN = NEW + HOLD. REENTRY, SLHIT, TARGETS and EXPIRED remain separate lifecycle outcomes. SURVIVOR is a cross-cutting watch flag for 0–7 calendar DTE; original classification is retained. WAIT is populated only by an explicit pending-state source. EXPIRYSCAN is evidence-only, not a qualified signal. No automatic order placement.',
          style: TextStyle(fontSize: 10, height: 1.4, color: cs.onSurfaceVariant)),
      ]),
    );
  }
}
