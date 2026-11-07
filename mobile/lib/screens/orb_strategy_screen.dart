import 'dart:async';
import 'package:flutter/material.dart';
import '../services/air_api_client.dart';

class OrbStrategyScreen extends StatefulWidget {
  const OrbStrategyScreen({super.key});
  @override
  State<OrbStrategyScreen> createState() => _OrbStrategyScreenState();
}

class _OrbStrategyScreenState extends State<OrbStrategyScreen> {
  final AirApiClient _api = AirApiClient();
  final TextEditingController _symbols = TextEditingController(text: 'NIFTY, BANKNIFTY');
  Timer? _timer;
  Map<String, dynamic> _status = {};
  bool _busy = false;
  String? _message;

  @override
  void initState() {
    super.initState();
    _refresh();
    _timer = Timer.periodic(const Duration(seconds: 5), (_) => _refresh());
  }

  @override
  void dispose() {
    _timer?.cancel();
    _symbols.dispose();
    _api.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    if (_busy) return;
    try {
      final result = await _api.orbStatus();
      if (mounted) setState(() => _status = result);
    } catch (e) {
      if (mounted) setState(() => _message = e.toString());
    }
  }

  Future<void> _subscribe() async {
    final values = _symbols.text.split(',').map((x) => x.trim().toUpperCase())
        .where((x) => x.isNotEmpty).toSet().toList();
    if (values.isEmpty) return;
    setState(() { _busy = true; _message = null; });
    try {
      final result = await _api.orbSubscribe(values);
      setState(() => _message =
          'Subscribed: ${(result['symbols'] as List? ?? const []).join(', ')}'
          '${(result['not_found'] as List? ?? const []).isEmpty ? '' : ' • Not found: ${(result['not_found'] as List).join(', ')}'}');
      await _refresh();
    } catch (e) {
      setState(() => _message = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _ruleCard(String title, String range, List<String> rules) => Card(
    child: Padding(
      padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 12)),
        const SizedBox(height: 4),
        Text(range, style: TextStyle(color: Theme.of(context).colorScheme.primary,
            fontWeight: FontWeight.w900, fontSize: 15)),
        const SizedBox(height: 7),
        ...rules.map((rule) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 2),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('•  '), Expanded(child: Text(rule, style: const TextStyle(fontSize: 10))),
          ]),
        )),
      ]),
    ),
  );

  Widget _metric(String label, dynamic value) => Expanded(child: Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(label, style: const TextStyle(fontSize: 8, fontWeight: FontWeight.w800)),
      const SizedBox(height: 3),
      Text(value?.toString() ?? '—',
          style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w900)),
    ],
  ));

  Widget _signalCard(Map<String, dynamic> signal) {
    final isOpen = signal['status'] == 'OPEN';
    return Card(child: Padding(
      padding: const EdgeInsets.all(11),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('${signal['strategy']} • ${signal['symbol']}',
              style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 11))),
          Text(signal['status']?.toString() ?? '—',
              style: TextStyle(fontWeight: FontWeight.w900, fontSize: 9,
                  color: isOpen ? Colors.green : Theme.of(context).colorScheme.error)),
        ]),
        const SizedBox(height: 7),
        Row(children: [
          _metric('ENTRY', signal['entry_price']),
          _metric('STOP LOSS', signal['stop_loss']),
          _metric('RANGE HIGH', signal['range_high']),
        ]),
        const SizedBox(height: 5),
        Text('Entry: ${signal['entry_at'] ?? '—'}'
          '${signal['exit_price'] == null ? '' : ' • Exit: ${signal['exit_price']}'}',
          style: const TextStyle(fontSize: 9)),
        if (signal['exit_reason'] != null)
          Text(signal['exit_reason'].toString(), style: const TextStyle(fontSize: 9)),
      ]),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final symbols = (_status['symbols'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>().toList();
    final signals = (_status['signals'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>().toList().reversed.toList();
    final source = _status['market_data_source'] as Map<String, dynamic>? ?? {};
    return Scaffold(
      appBar: AppBar(title: const Text('AIR ORB STRATEGIES'),
        actions: [IconButton(onPressed: _refresh, icon: const Icon(Icons.refresh))]),
      body: ListView(padding: const EdgeInsets.all(14), children: [
        Card(child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('LIVE INSTRUMENT SUBSCRIPTION',
                style: TextStyle(fontWeight: FontWeight.w900, fontSize: 11)),
            const SizedBox(height: 5),
            const Text('Enter comma-separated NSE symbols. Default watchlist: NIFTY, BANKNIFTY.',
                style: TextStyle(fontSize: 10)),
            const SizedBox(height: 8),
            TextField(controller: _symbols,
              decoration: const InputDecoration(labelText: 'Symbols',
                  hintText: 'NIFTY, BANKNIFTY, RELIANCE', border: OutlineInputBorder(),
                  isDense: true)),
            const SizedBox(height: 8),
            SizedBox(width: double.infinity, child: ElevatedButton.icon(
              onPressed: _busy ? null : _subscribe,
              icon: const Icon(Icons.radar_rounded),
              label: Text(_busy ? 'SUBSCRIBING…' : 'SUBSCRIBE TO LIVE FEED'))),
            if (_message != null) Text(_message!, style: const TextStyle(fontSize: 10)),
            const SizedBox(height: 5),
            Text('SOURCE: ${source['effective_source'] ?? '—'} • STATUS: ${source['connection_status'] ?? '—'}',
                style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w800)),
            Text('Last tick: ${_status['last_tick_at'] ?? 'Awaiting live data'} • Ticks: ${_status['tick_count'] ?? 0}',
                style: const TextStyle(fontSize: 9)),
          ]),
        )),
        _ruleCard('MORNING ORB • BREAKOUT / RETEST / CONFIRMATION',
          '09:18–09:23 IST', const [
            'Build range high and low from live ticks during the five-minute window.',
            'Wait for a completed 3-minute candle to close above range high.',
            'Wait for a retest of range high, then another completed 3-minute close above it.',
            'BUY at confirmation candle close. Initial SL = confirmation candle low.',
            'Trail only from completed 3-minute candle lows; never loosen the stop.',
            'Exit when a completed candle closes below the previous candle open; use the next executable tick.',
          ]),
        _ruleCard('AFTERNOON ORB • IMMEDIATE UPSIDE BREAKOUT',
          '12:57–13:00 IST', const [
            'Capture the range high and low from the 12:57–13:00 candle.',
            'BUY immediately on the first live tick above range high. No close confirmation or retest.',
            'Initial SL = 12:57–13:00 candle low.',
          ]),
        Card(child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('RANGE STATUS BY SYMBOL',
                style: TextStyle(fontWeight: FontWeight.w900, fontSize: 11)),
            const SizedBox(height: 7),
            if (symbols.isEmpty) const Text('Subscribe to instruments to start collecting live ranges.',
                style: TextStyle(fontSize: 10)),
            ...symbols.map((row) {
              final morning = row['morning'] as Map<String, dynamic>? ?? {};
              final afternoon = row['afternoon'] as Map<String, dynamic>? ?? {};
              return Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(row['symbol']?.toString() ?? '—',
                      style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 11)),
                  Text('MORNING H/L: ${morning['range_high'] ?? '—'} / ${morning['range_low'] ?? '—'}'
                      ' • Breakout: ${morning['breakout'] == true ? 'YES' : 'NO'}'
                      ' • Retest: ${morning['retested'] == true ? 'YES' : 'NO'}',
                      style: const TextStyle(fontSize: 9)),
                  Text('AFTERNOON H/L: ${afternoon['range_high'] ?? '—'} / ${afternoon['range_low'] ?? '—'}',
                      style: const TextStyle(fontSize: 9)),
                ]),
              );
            }),
          ]),
        )),
        const Padding(
          padding: EdgeInsets.fromLTRB(4, 8, 4, 4),
          child: Text('SIGNALS & POSITION MONITOR',
              style: TextStyle(fontWeight: FontWeight.w900, fontSize: 11)),
        ),
        if (signals.isEmpty) const Card(child: Padding(
          padding: EdgeInsets.all(16),
          child: Text('No ORB signals generated yet. Signals appear only after the specified live conditions are met.',
              style: TextStyle(fontSize: 10)),
        )),
        ...signals.map(_signalCard),
        const Card(child: Padding(
          padding: EdgeInsets.all(11),
          child: Text('SIGNAL-ONLY MODE. No broker orders are placed by this ORB module. A live broker feed and subscription are required; NSE EOD history is not treated as live data.',
              style: TextStyle(fontSize: 9, fontWeight: FontWeight.w700)),
        )),
      ]),
    );
  }
}
