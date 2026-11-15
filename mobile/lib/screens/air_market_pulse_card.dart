import 'package:flutter/material.dart';

import '../services/air_api_client.dart';

class AirMarketPulseCard extends StatefulWidget {
  const AirMarketPulseCard({super.key});

  @override
  State<AirMarketPulseCard> createState() => _AirMarketPulseCardState();
}

class _AirMarketPulseCardState extends State<AirMarketPulseCard> {
  final AirApiClient _api = AirApiClient();
  Map<String, dynamic>? _pulse;
  String? _error;
  bool _loading = true;

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

  Future<void> _load() async {
    if (mounted) setState(() { _loading = true; _error = null; });
    try {
      final result = await _api.marketIntelligencePulse();
      if (mounted) setState(() => _pulse = result);
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final breadth = _pulse?['breadth'] as Map<String, dynamic>? ?? const {};
    final indices = _pulse?['indices'] as Map<String, dynamic>? ?? const {};
    final sectors = _pulse?['sectors'] as Map<String, dynamic>? ?? const {};
    final available = breadth['status'] == 'available';
    final advances = breadth['advances'] as int? ?? 0;
    final declines = breadth['declines'] as int? ?? 0;
    final unchanged = breadth['unchanged'] as int? ?? 0;
    final total = breadth['total'] as int? ?? 0;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(15),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            const Expanded(child: Text('MARKET PULSE', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w900, letterSpacing: .8))),
            if (_loading) const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
            else IconButton(onPressed: _load, tooltip: 'Refresh market pulse', icon: const Icon(Icons.refresh_rounded, size: 18)),
          ]),
          Text(_pulse?['source']?.toString() ?? 'Official NSE source', style: TextStyle(fontSize: 10, color: colors.onSurfaceVariant)),
          const SizedBox(height: 4),
          Text('Session: ${_pulse?['as_of'] ?? 'Not imported'} · EOD data', style: TextStyle(fontSize: 10, color: colors.onSurfaceVariant)),
          const SizedBox(height: 12),
          if (_error != null)
            Text('Market pulse unavailable: $_error', style: TextStyle(fontSize: 11, color: colors.error))
          else if (available) ...[
            Row(children: [
              Expanded(child: _BreadthMetric(label: 'ADVANCES', value: advances, color: const Color(0xFF20A879))),
              const SizedBox(width: 8),
              Expanded(child: _BreadthMetric(label: 'DECLINES', value: declines, color: colors.error)),
              const SizedBox(width: 8),
              Expanded(child: _BreadthMetric(label: 'UNCHANGED', value: unchanged, color: colors.onSurfaceVariant)),
            ]),
            const SizedBox(height: 8),
            ClipRRect(borderRadius: BorderRadius.circular(8), child: SizedBox(height: 8, child: Row(children: [
              if (total > 0) Expanded(flex: advances, child: const ColoredBox(color: Color(0xFF20A879))),
              if (total > 0) Expanded(flex: declines, child: ColoredBox(color: colors.error)),
              if (total > 0) Expanded(flex: unchanged, child: ColoredBox(color: colors.outlineVariant)),
            ]))),
            Text('$total NSE equity instruments with valid close/previous-close values', style: TextStyle(fontSize: 9, color: colors.onSurfaceVariant)),
          ] else
            Text(_loading ? 'Loading verified NSE session data…' : 'No imported NSE cash-market session is available yet.', style: TextStyle(fontSize: 11, color: colors.onSurfaceVariant)),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(child: _UnavailableMetric(title: 'NIFTY · BANK NIFTY · SENSEX', reason: indices['reason']?.toString() ?? 'Verified index quotes unavailable', color: colors)),
            const SizedBox(width: 8),
            Expanded(child: _UnavailableMetric(title: 'SECTOR STRENGTH', reason: sectors['reason']?.toString() ?? 'Verified sector mapping unavailable', color: colors)),
          ]),
          const SizedBox(height: 9),
          Text(_pulse?['disclosure']?.toString() ?? 'Only verified data is displayed. Live values are not inferred from EOD records.',
            style: TextStyle(fontSize: 9, height: 1.35, color: colors.onSurfaceVariant)),
        ]),
      ),
    );
  }
}

class _BreadthMetric extends StatelessWidget {
  const _BreadthMetric({required this.label, required this.value, required this.color});
  final String label;
  final int value;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(10),
    decoration: BoxDecoration(color: color.withValues(alpha: .08), borderRadius: BorderRadius.circular(11)),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(value.toString(), style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900, color: color)),
      Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 8, fontWeight: FontWeight.w800, color: color)),
    ]),
  );
}

class _UnavailableMetric extends StatelessWidget {
  const _UnavailableMetric({required this.title, required this.reason, required this.color});
  final String title, reason;
  final ColorScheme color;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(10),
    decoration: BoxDecoration(border: Border.all(color: color.outlineVariant.withValues(alpha: .5)), borderRadius: BorderRadius.circular(11)),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(title, style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w900)),
      const SizedBox(height: 4),
      Text('NOT VERIFIED', style: TextStyle(fontSize: 8, fontWeight: FontWeight.w800, color: color.onSurfaceVariant)),
      const SizedBox(height: 3),
      Text(reason, maxLines: 3, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 8, color: color.onSurfaceVariant)),
    ]),
  );
}
