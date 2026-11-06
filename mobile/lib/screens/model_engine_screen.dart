import 'package:flutter/material.dart';
import '../services/air_api_client.dart';

class ModelEngineScreen extends StatefulWidget {
  const ModelEngineScreen({super.key});
  @override
  State<ModelEngineScreen> createState() => _ModelEngineScreenState();
}

class _ModelEngineScreenState extends State<ModelEngineScreen> {
  final AirApiClient _api = AirApiClient();
  final _email = TextEditingController();
  final _password = TextEditingController();
  static const _sections = ['NEW', 'HOLD', 'RE-ENTRY', 'SL', 'TARGETS', 'EXPIRED', 'EXPIRYSCAN'];
  Map<String, dynamic> _groups = {};
  Map<String, dynamic> _counts = {};
  int _selected = 0;
  bool _authenticated = false, _loading = false;
  String? _error, _updatedAt;
  String _dataStatus = 'SIGN IN TO LOAD YOUR MODEL ENGINE LEDGER';

  @override
  void dispose() { _email.dispose(); _password.dispose(); _api.dispose(); super.dispose(); }

  Future<void> _login() async {
    setState(() { _loading = true; _error = null; });
    try {
      await _api.login(_email.text, _password.text);
      _authenticated = true;
      await _refresh();
    } catch (e) { if (mounted) setState(() => _error = e.toString()); }
    finally { if (mounted) setState(() => _loading = false); }
  }

  Future<void> _refresh() async {
    if (!_api.isAuthenticated) return;
    setState(() { _loading = true; _error = null; });
    try {
      final result = await _api.modelEngineLedger();
      if (!mounted) return;
      setState(() {
        _groups = result['groups'] as Map<String, dynamic>? ?? {};
        _counts = result['counts'] as Map<String, dynamic>? ?? {};
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
    DataColumn(label: Text('SIGNAL DATE')), DataColumn(label: Text('ENTRY DATE')),
    DataColumn(label: Text('CLASS')), DataColumn(label: Text('SYMBOL')),
    DataColumn(label: Text('TYPE')), DataColumn(label: Text('EXPIRY')),
    DataColumn(label: Text('STRIKE')), DataColumn(label: Text('ENTRY')),
    DataColumn(label: Text('LATEST')), DataColumn(label: Text('SL')),
    DataColumn(label: Text('T1')), DataColumn(label: Text('T2')),
    DataColumn(label: Text('T3')), DataColumn(label: Text('LOT')),
    DataColumn(label: Text('QTY')), DataColumn(label: Text('P&L')),
    DataColumn(label: Text('SCORE')), DataColumn(label: Text('AGE')),
    DataColumn(label: Text('DTE')), DataColumn(label: Text('SHELF LEFT')),
    DataColumn(label: Text('SHELF STATUS')), DataColumn(label: Text('REASON')),
  ];

  DataRow _row(Map<String, dynamic> r) => DataRow(cells: [
    DataCell(_cell(_v(r, 'signal_date'))), DataCell(_cell(_v(r, 'entry_date'))),
    DataCell(_cell(_v(r, 'classification'))), DataCell(_cell(_v(r, 'symbol'))),
    DataCell(_cell('${_v(r, 'instrument_type')} ${_v(r, 'option_type')}')),
    DataCell(_cell(_v(r, 'expiry'))), DataCell(_cell(_v(r, 'strike'))),
    DataCell(_cell(_v(r, 'entry_price'))), DataCell(_cell(_v(r, 'latest_price'))),
    DataCell(_cell(_v(r, 'stop_loss'))), DataCell(_cell(_v(r, 'target_1'))),
    DataCell(_cell(_v(r, 'target_2'))), DataCell(_cell(_v(r, 'target_3'))),
    DataCell(_cell(_v(r, 'lot_size'))), DataCell(_cell(_v(r, 'quantity'))),
    DataCell(_cell('${_v(r, 'pnl')} (${_v(r, 'pnl_pct')}%)')),
    DataCell(_cell(_v(r, 'score'))), DataCell(_cell(_v(r, 'signal_age_days'))),
    DataCell(_cell(_v(r, 'days_to_expiry'))), DataCell(_cell(_v(r, 'shelf_life_remaining_days'))),
    DataCell(_cell(_v(r, 'shelf_life_status'))), DataCell(_cell(_v(r, 'reason'))),
  ]);

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final rows = (_groups[_sections[_selected]] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>().toList();
    return Scaffold(
      appBar: AppBar(title: const Text('AIR MODEL ENGINE'),
        actions: [IconButton(tooltip: 'Refresh ledger',
          onPressed: !_authenticated || _loading ? null : _refresh,
          icon: const Icon(Icons.refresh_rounded))]),
      body: ListView(padding: const EdgeInsets.all(14), children: [
        if (!_authenticated) Card(child: Padding(
          padding: const EdgeInsets.all(14), child: Column(children: [
            const Text('SIGN IN TO AIR', style: TextStyle(fontWeight: FontWeight.w900)),
            const SizedBox(height: 10),
            TextField(controller: _email, keyboardType: TextInputType.emailAddress,
              decoration: const InputDecoration(labelText: 'AIR email', border: OutlineInputBorder())),
            const SizedBox(height: 8),
            TextField(controller: _password, obscureText: true,
              decoration: const InputDecoration(labelText: 'AIR password', border: OutlineInputBorder())),
            const SizedBox(height: 10),
            FilledButton(onPressed: _loading ? null : _login, child: const Text('SIGN IN & LOAD LEDGER')),
          ]),
        )) else ...[
          Card(child: Padding(padding: const EdgeInsets.all(12), child: Column(
            crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                const Expanded(child: Text('SIGNAL & POSITION LIFECYCLE', style: TextStyle(fontWeight: FontWeight.w900, fontSize: 12))),
                Text(_dataStatus, style: TextStyle(fontSize: 9, color: cs.primary, fontWeight: FontWeight.w800)),
              ]),
              const SizedBox(height: 5),
              Text('Updated: ${_updatedAt ?? 'No verified records yet'}',
                style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
              const SizedBox(height: 10),
              Wrap(spacing: 7, runSpacing: 7, children: _sections.map((s) => ChoiceChip(
                label: Text('$s  ${_counts[s] ?? 0}', style: const TextStyle(fontSize: 10)),
                selected: _sections[_selected] == s,
                onSelected: (_) => setState(() => _selected = _sections.indexOf(s)),
              )).toList()),
            ],
          ))),
          const SizedBox(height: 10),
          if (rows.isEmpty) Card(child: Padding(padding: const EdgeInsets.all(18),
            child: Column(children: [
              Icon(Icons.hourglass_empty_rounded, size: 28, color: cs.onSurfaceVariant),
              const SizedBox(height: 8),
              Text('No verified ${_sections[_selected]} records', style: const TextStyle(fontWeight: FontWeight.w800)),
              const SizedBox(height: 5),
              Text('This section populates when the validated signal engine writes records. No invented sample trades are displayed.',
                textAlign: TextAlign.center, style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
            ]),
          )) else Card(child: SingleChildScrollView(scrollDirection: Axis.horizontal,
            child: DataTable(columnSpacing: 14, headingRowHeight: 38,
              dataRowMinHeight: 38, dataRowMaxHeight: 52,
              columns: _columns, rows: rows.map(_row).toList()))),
        ],
        if (_loading) const Padding(padding: EdgeInsets.symmetric(vertical: 10), child: LinearProgressIndicator()),
        if (_error != null) Padding(padding: const EdgeInsets.only(top: 10),
          child: Text(_error!, style: TextStyle(color: cs.error, fontSize: 11))),
        const SizedBox(height: 12),
        Text('Shelf life is separate from contract DTE. SURVIVOR marks contracts with 0–7 days to expiry; it is a watch classification, not an automatic trade signal. Order placement is not part of this ledger.',
          style: TextStyle(fontSize: 10, height: 1.4, color: cs.onSurfaceVariant)),
      ]),
    );
  }
}
