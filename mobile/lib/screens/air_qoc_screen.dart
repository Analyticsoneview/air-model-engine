import 'package:flutter/material.dart';

import '../services/air_api_client.dart';

class AirQocScreen extends StatefulWidget {
  const AirQocScreen({super.key});

  @override
  State<AirQocScreen> createState() => _AirQocScreenState();
}

class _AirQocScreenState extends State<AirQocScreen> {
  final AirApiClient _api = AirApiClient();
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _scrip = TextEditingController(text: '13');
  final _segment = TextEditingController(text: 'IDX_I');
  List<Map<String, dynamic>> _accounts = [];
  List<Map<String, dynamic>> _universe = [];
  Map<String, dynamic>? _selectedUnderlying;
  List<String> _expiries = [];
  List<Map<String, dynamic>> _rows = [];
  List<Map<String, dynamic>> _signals = [];
  String _qocMode = 'LIVE';
  String _qocScope = 'ALL';
  bool _showRejected = false;
  Map<String, dynamic>? _qocSummary;
  String? _accountId;
  String? _expiry;
  String? _error;
  String? _status;
  bool _authenticated = false;
  bool _loading = false;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _scrip.dispose();
    _segment.dispose();
    _api.dispose();
    super.dispose();
  }

  Future<void> _run(Future<void> Function() action) async {
    setState(() { _loading = true; _error = null; });
    try {
      await action();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _login() => _run(() async {
    await _api.login(_email.text, _password.text);
    final accounts = await _api.accounts();
    final dhan = accounts.where((a) => a['broker'] == 'dhan').toList();
    if (!mounted) return;
    setState(() {
      _accounts = dhan;
      _authenticated = true;
      _accountId = dhan.isNotEmpty ? dhan.first['account_id'] as String : null;
      _status = dhan.isEmpty
          ? 'No Dhan account registered. Add one under AIR Connections.'
          : 'Signed in. Discovering the complete F&O universe…';
    });
    if (dhan.isNotEmpty) await _loadUniverse();
  });

  int? get _underlyingScrip =>
      int.tryParse((_selectedUnderlying?['security_id'] ?? _scrip.text).toString());

  String get _underlyingSegment =>
      (_selectedUnderlying?['exchange_segment'] ?? _segment.text).toString();

  Future<void> _loadUniverse() => _run(() async {
    final result = await _api.dhanFnoUniverse();
    final values = (result['underlyings'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .where((item) => item['validated'] == true)
        .toList(growable: false);
    if (!mounted) return;
    setState(() {
      _universe = values;
      _selectedUnderlying = values.isNotEmpty ? values.first : null;
      _status = 'Discovered ${result['total_underlying_count'] ?? values.length} NSE F&O underlyings · '
          '${result['stock_underlying_count'] ?? 0} stocks · '
          '${result['index_underlying_count'] ?? 0} indices. '
          'Validated mappings: ${result['validated_underlying_count'] ?? values.length}.';
    });
  });

  Future<void> _checkStatus() => _run(() async {
    final id = _accountId;
    if (id == null) throw const AirApiException('Select a Dhan account first.');
    final result = await _api.dhanDataStatus(id);
    if (!mounted) return;
    setState(() => _status =
        'Authenticated · Data plan: ${result['data_plan'] ?? 'not reported'} · '
        'Validity: ${result['data_validity'] ?? 'not reported'}');
  });

  Future<void> _loadExpiries() => _run(() async {
    final id = _accountId;
    final scrip = _underlyingScrip;
    if (id == null || scrip == null || scrip <= 0) {
      throw const AirApiException('Enter a valid underlying security ID and select an account.');
    }
    final values = await _api.dhanExpiryList(id, scrip, _underlyingSegment);
    if (!mounted) return;
    setState(() {
      _expiries = values;
      _expiry = values.isNotEmpty ? values.first : null;
      _rows = [];
      if (values.isEmpty) _status = 'No active option expiries returned for this underlying.';
    });
  });

  Future<void> _loadChain() => _run(() async {
    final id = _accountId;
    final scrip = _underlyingScrip;
    final expiry = _expiry;
    if (id == null || scrip == null || expiry == null) {
      throw const AirApiException('Select an account, valid security ID and expiry.');
    }
    final result = await _api.dhanOptionChain(
        id, scrip, _underlyingSegment, expiry);
    final data = result['data'] as Map<String, dynamic>? ?? {};
    final oc = data['oc'] as Map<String, dynamic>? ?? {};
    final rows = <Map<String, dynamic>>[];
    for (final entry in oc.entries) {
      final sides = entry.value as Map<String, dynamic>? ?? {};
      rows.add({
        'strike': entry.key,
        'ce': sides['ce'] as Map<String, dynamic>? ?? {},
        'pe': sides['pe'] as Map<String, dynamic>? ?? {},
      });
    }
    rows.sort((a, b) =>
        (double.tryParse(a['strike'] as String) ?? 0)
            .compareTo(double.tryParse(b['strike'] as String) ?? 0));
    if (!mounted) return;
    setState(() {
      _rows = rows;
      _status = '${result['saved_contract_observations'] ?? rows.length} '
          'CE/PE contract observations saved to the private AIR research store. '
          'Underlying LTP: ${data['last_price'] ?? '—'}';
    });
  });

  Future<void> _runQualification() => _run(() async {
    final id = _accountId;
    if (id == null) throw const AirApiException('Select a Dhan account first.');
    final result = await _api.dhanQocQualification(
      id,
      mode: _qocMode,
      underlyingScrip: _qocScope == 'SELECTED'
          ? _selectedUnderlying?['security_id']?.toString() : null,
      expiry: _qocScope == 'SELECTED' ? _expiry : null,
    );
    if (!mounted) return;
    final values = (result['signals'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>().toList(growable: false);
    setState(() {
      _signals = values;
      _qocSummary = result;
      _status = 'AIR QOC ${result['mode']} · Evaluated ${result['contracts_evaluated'] ?? 0} contracts · '
          'High conviction ${(result['counts'] as Map?)?['HIGH_CONVICTION'] ?? 0} · '
          'Qualified ${(result['counts'] as Map?)?['QUALIFIED'] ?? 0} · '
          'Watch ${(result['counts'] as Map?)?['WATCH'] ?? 0} · '
          'Rejected ${(result['counts'] as Map?)?['REJECT'] ?? 0}';
    });
  });

  Future<void> _runEodCapture() => _run(() async {
    final result = await _api.runQocEodCapture();
    if (!mounted) return;
    setState(() => _status =
        'EOD capture: ${result['status'] ?? 'unknown'} · '
        'Underlying count: ${result['underlyings'] ?? 0} · '
        'Expiry chains: ${result['expiry_chains'] ?? 0} · '
        'Saved contract observations: ${result['contract_observations'] ?? 0}. '
        'This is data capture only, not a QOC signal.');
  });

  Future<void> _loadSaved() => _run(() async {
    final id = _accountId;
    if (id == null) throw const AirApiException('Select a Dhan account first.');
    final values = await _api.dhanObservations(id);
    if (!mounted) return;
    final grouped = <String, Map<String, dynamic>>{};
    for (final observation in values) {
      final key = '${observation['expiry']}|${observation['strike']}|${observation['observed_at']}';
      final row = grouped.putIfAbsent(key, () => {
        'strike': observation['strike']?.toString() ?? '—',
        'ce': <String, dynamic>{},
        'pe': <String, dynamic>{},
      });
      if (observation['option_type'] == 'CE') {
        row['ce'] = observation;
      } else if (observation['option_type'] == 'PE') {
        row['pe'] = observation;
      }
    }
    setState(() {
      _rows = grouped.values.toList();
      _status = 'Loaded ${values.length} stored CE/PE observations. '
          'Rows are grouped by expiry, strike and observation time; they are snapshots, not live quotes.';
    });
  });

  String _value(Map<String, dynamic> row, String key) =>
      row[key]?.toString() ?? '—';

  Widget _metricCell(String value) => Padding(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
    child: Text(value, style: const TextStyle(fontSize: 10)),
  );

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final visibleSignals = _showRejected
        ? _signals
        : _signals.where((item) => item['classification'] != 'REJECT').toList();
    return Scaffold(
      appBar: AppBar(title: const Text('AIR QOC · OPTIONS DATA')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('READ-ONLY DATA CONNECTION',
                    style: TextStyle(fontWeight: FontWeight.w900, fontSize: 12)),
                const SizedBox(height: 5),
                Text('Connect to AIR, choose a Dhan account, then retrieve an expiry and option chain. This screen does not place orders.',
                    style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant)),
                if (!_authenticated) ...[
                  const SizedBox(height: 12),
                  TextField(controller: _email, keyboardType: TextInputType.emailAddress,
                      decoration: const InputDecoration(labelText: 'AIR email', border: OutlineInputBorder())),
                  const SizedBox(height: 9),
                  TextField(controller: _password, obscureText: true,
                      decoration: const InputDecoration(labelText: 'AIR password', border: OutlineInputBorder())),
                  const SizedBox(height: 10),
                  FilledButton(onPressed: _loading ? null : _login,
                      child: const Text('SIGN IN TO AIR')),
                ] else ...[
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    initialValue: _accountId,
                    decoration: const InputDecoration(labelText: 'Dhan account', border: OutlineInputBorder()),
                    items: _accounts.map((a) => DropdownMenuItem<String>(
                      value: a['account_id'] as String,
                      child: Text(a['account_id'] as String),
                    )).toList(),
                    onChanged: _loading ? null : (v) => setState(() => _accountId = v),
                  ),
                  const SizedBox(height: 9),
                  OutlinedButton.icon(onPressed: _loading ? null : _checkStatus,
                      icon: const Icon(Icons.verified_user_outlined),
                      label: const Text('CHECK DATA API ACCESS')),
                  const SizedBox(height: 8),
                  FilledButton.tonalIcon(
                    onPressed: _loading ? null : _runEodCapture,
                    icon: const Icon(Icons.schedule_send_rounded),
                    label: const Text('RUN EOD SNAPSHOT CAPTURE'),
                  ),
                ],
              ]),
            ),
          ),
          const SizedBox(height: 12),
          Card(child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('UNDERLYING & EXPIRY', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w900)),
              const SizedBox(height: 10),
              if (_universe.isEmpty)
                FilledButton.tonalIcon(
                  onPressed: _loading || !_authenticated ? null : _loadUniverse,
                  icon: const Icon(Icons.sync),
                  label: const Text('DISCOVER F&O UNIVERSE'),
                )
              else ...[
                Text('Automatic universe · ${_universe.length} validated underlyings',
                    style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant)),
                const SizedBox(height: 8),
                DropdownButtonFormField<Map<String, dynamic>>(
                  initialValue: _selectedUnderlying,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'NSE F&O underlying', border: OutlineInputBorder()),
                  items: _universe.map((item) => DropdownMenuItem<Map<String, dynamic>>(
                    value: item,
                    child: Text('${item['symbol']} · ${item['instrument']} · ${item['security_id']}'),
                  )).toList(),
                  onChanged: _loading ? null : (value) => setState(() {
                    _selectedUnderlying = value;
                    _expiries = [];
                    _expiry = null;
                    _rows = [];
                  }),
                ),
                const SizedBox(height: 8),
                FilledButton.tonal(onPressed: _loading || !_authenticated ? null : _loadExpiries,
                    child: const Text('GET ACTIVE EXPIRIES')),
              ],
              if (_expiries.isNotEmpty) ...[
                const SizedBox(height: 8),
                DropdownButtonFormField<String>(
                  initialValue: _expiry,
                  decoration: const InputDecoration(labelText: 'Expiry date', border: OutlineInputBorder()),
                  items: _expiries.map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(),
                  onChanged: (v) => setState(() => _expiry = v),
                ),
                const SizedBox(height: 8),
                FilledButton(onPressed: _loading ? null : _loadChain,
                    child: const Text('FETCH OPTION CHAIN & SAVE SNAPSHOT')),
              ],
            ]),
          )),
          if (_status != null) ...[
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: cs.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(12)),
              child: Text(_status!, style: const TextStyle(fontSize: 11)),
            ),
          ],
          if (_error != null) ...[
            const SizedBox(height: 10),
            Text(_error!, style: TextStyle(color: cs.error, fontSize: 11)),
          ],
          if (_authenticated) ...[
            const SizedBox(height: 12),
            Card(child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('AIR QOC · QUALIFIED RESEARCH',
                    style: TextStyle(fontSize: 12, fontWeight: FontWeight.w900)),
                const SizedBox(height: 5),
                Text('Scores are calculated from two distinct same-session snapshots. Missing or stale evidence is rejected; one snapshot never creates a signal.',
                    style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
                const SizedBox(height: 10),
                DropdownButtonFormField<String>(
                  initialValue: _qocScope,
                  decoration: const InputDecoration(labelText: 'Universe scope', border: OutlineInputBorder()),
                  items: const [
                    DropdownMenuItem(value: 'ALL', child: Text('All stored NSE F&O underlyings')),
                    DropdownMenuItem(value: 'SELECTED', child: Text('Selected underlying / expiry')),
                  ],
                  onChanged: _loading ? null : (value) => setState(() {
                    _qocScope = value ?? 'ALL';
                    _signals = [];
                    _qocSummary = null;
                  }),
                ),
                const SizedBox(height: 8),
                DropdownButtonFormField<String>(
                  initialValue: _qocMode,
                  decoration: const InputDecoration(labelText: 'Research workflow', border: OutlineInputBorder()),
                  items: const [
                    DropdownMenuItem(value: 'LIVE', child: Text('AIR QOC LIVE · 5-minute freshness')),
                    DropdownMenuItem(value: 'POSITIONAL', child: Text('AIR QOC POSITIONAL · 30-minute freshness')),
                    DropdownMenuItem(value: 'POST_MARKET', child: Text('AIR QOC POST-MARKET · same-session data')),
                  ],
                  onChanged: _loading ? null : (value) => setState(() {
                    _qocMode = value ?? 'LIVE';
                    _signals = [];
                    _qocSummary = null;
                  }),
                ),
                const SizedBox(height: 9),
                SizedBox(width: double.infinity, child: FilledButton.icon(
                  onPressed: _loading ? null : _runQualification,
                  icon: const Icon(Icons.fact_check_outlined),
                  label: const Text('RUN AIR QOC QUALIFICATION'),
                )),
                if (_qocSummary != null) ...[
                  const SizedBox(height: 8),
                  Text('${_qocSummary!['disclosure'] ?? ''}',
                      style: TextStyle(fontSize: 9, height: 1.35, color: cs.onSurfaceVariant)),
                ],
              ]),
            )),
            if (_signals.isNotEmpty) ...[
              const SizedBox(height: 8),
              Row(children: [
                const Expanded(child: Text('RANKED QOC RESULTS',
                    style: TextStyle(fontSize: 11, fontWeight: FontWeight.w900))),
                TextButton(
                  onPressed: () => setState(() => _showRejected = !_showRejected),
                  child: Text(_showRejected ? 'HIDE REJECTS' : 'SHOW REJECTS'),
                ),
              ]),
              if (visibleSignals.isEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  child: Text('No contracts passed the current qualification gates. Rejected contracts: ${(_qocSummary?['counts'] as Map?)?['REJECT'] ?? 0}.',
                      style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
                )
              else
              ...visibleSignals.map((signal) {
                final classification = signal['classification']?.toString() ?? 'REJECT';
                final accepted = classification == 'HIGH_CONVICTION' || classification == 'QUALIFIED';
                final color = classification == 'HIGH_CONVICTION'
                    ? const Color(0xFF168A61)
                    : classification == 'QUALIFIED' ? const Color(0xFF3985C6)
                    : classification == 'WATCH' ? const Color(0xFFB88728) : cs.error;
                final failures = (signal['gate_failures'] as List<dynamic>? ?? const []).join(' · ');
                final breakdown = (signal['score_breakdown'] as Map?)?.entries
                    .map((entry) => '${entry.key}: ${entry.value}').join(' · ') ?? 'No score evidence';
                final targets = signal['targets_reference'] as Map<String, dynamic>? ?? const {};
                return Card(child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Row(children: [
                      Expanded(child: Text('${signal['underlying']} ${signal['option_type']} ${signal['strike']}',
                          style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w900))),
                      Text('${signal['score']}/100', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w900, color: color)),
                    ]),
                    const SizedBox(height: 3),
                    Text('$classification · Expiry ${signal['expiry']} · DTE ${signal['dte'] ?? '—'}',
                        style: TextStyle(fontSize: 9, fontWeight: FontWeight.w800, color: color)),
                    const SizedBox(height: 7),
                    Wrap(spacing: 12, runSpacing: 5, children: [
                      Text('Premium ₹${signal['entry_premium'] ?? '—'}', style: const TextStyle(fontSize: 10)),
                      Text('OTM ${signal['otm_pct'] ?? '—'}%', style: const TextStyle(fontSize: 10)),
                      Text('Underlying ${signal['underlying_change_pct'] ?? '—'}%', style: const TextStyle(fontSize: 10)),
                      Text('Premium move ${signal['premium_change_pct'] ?? '—'}%', style: const TextStyle(fontSize: 10)),
                      Text('Option vol Δ ${signal['volume_delta'] ?? '—'}', style: const TextStyle(fontSize: 10)),
                      Text('OI Δ ${signal['oi_delta'] ?? '—'}', style: const TextStyle(fontSize: 10)),
                      Text('Spread ${signal['spread_pct'] ?? '—'}%', style: const TextStyle(fontSize: 10)),
                    ]),
                    const SizedBox(height: 5),
                    Text('Score evidence: $breakdown', style: TextStyle(fontSize: 9, color: cs.onSurfaceVariant)),
                    if (!accepted && failures.isNotEmpty)
                      Text('Failed gates: $failures', style: TextStyle(fontSize: 9, color: cs.error)),
                    if (accepted)
                      Text('Illustrative only · SL ₹${signal['stop_loss_reference'] ?? '—'} · +50% ₹${targets['plus_50_percent'] ?? '—'} · +100% ₹${targets['plus_100_percent'] ?? '—'} · +200% ₹${targets['plus_200_percent'] ?? '—'} · +300% ₹${targets['plus_300_percent'] ?? '—'}',
                          style: TextStyle(fontSize: 9, color: cs.onSurfaceVariant)),
                  ]),
                ));
              }),
            ],
          ],
          if (_loading) const Padding(
            padding: EdgeInsets.symmetric(vertical: 12),
            child: LinearProgressIndicator(),
          ),
          if (_rows.isNotEmpty) ...[
            const SizedBox(height: 14),
            Row(children: [
              const Expanded(child: Text('OPTION CHAIN SNAPSHOT',
                  style: TextStyle(fontSize: 12, fontWeight: FontWeight.w900))),
              TextButton(onPressed: _loading ? null : _loadSaved,
                  child: const Text('SAVED DATA')),
            ]),
            Card(child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: DataTable(
                columnSpacing: 16,
                columns: const [
                  DataColumn(label: Text('STRIKE')),
                  DataColumn(label: Text('CE LTP')),
                  DataColumn(label: Text('CE VOL')),
                  DataColumn(label: Text('CE OI')),
                  DataColumn(label: Text('PE LTP')),
                  DataColumn(label: Text('PE VOL')),
                  DataColumn(label: Text('PE OI')),
                ],
                rows: _rows.map((row) {
                  final ce = row['ce'] as Map<String, dynamic>? ?? {};
                  final pe = row['pe'] as Map<String, dynamic>? ?? {};
                  return DataRow(cells: [
                    DataCell(Text(_value(row, 'strike'))),
                    DataCell(_metricCell(_value(ce, 'last_price'))),
                    DataCell(_metricCell(_value(ce, 'volume'))),
                    DataCell(_metricCell(_value(ce, 'oi'))),
                    DataCell(_metricCell(_value(pe, 'last_price'))),
                    DataCell(_metricCell(_value(pe, 'volume'))),
                    DataCell(_metricCell(_value(pe, 'oi'))),
                  ]);
                }).toList(),
              ),
            )),
          ],
          const SizedBox(height: 14),
          Text('Important: one option-chain snapshot is not an AIR QOC signal. Qualification requires session-to-session underlying behaviour, volume, premium change, OI change, expiry and liquidity checks.',
              style: TextStyle(fontSize: 10, height: 1.4, color: cs.onSurfaceVariant)),
        ],
      ),
    );
  }
}
