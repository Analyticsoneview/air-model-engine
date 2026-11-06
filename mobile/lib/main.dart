import 'package:flutter/material.dart';

void main() => runApp(const AirModelEngineApp());

enum AirLook { glass, dark, light }

class AirModelEngineApp extends StatefulWidget {
  const AirModelEngineApp({super.key});
  @override
  State<AirModelEngineApp> createState() => _AirModelEngineAppState();
}

class _AirModelEngineAppState extends State<AirModelEngineApp> {
  AirLook look = AirLook.glass;

  ThemeData get appTheme {
    final light = look == AirLook.light;
    final base = look == AirLook.glass
        ? const Color(0xFF0B1220)
        : light ? const Color(0xFFF3F6FB) : const Color(0xFF080D16);
    final surface = look == AirLook.glass
        ? const Color(0xB31B2A40)
        : light ? Colors.white : const Color(0xFF151E2D);
    const accent = Color(0xFFE5B85C);
    final scheme = ColorScheme.fromSeed(
      seedColor: accent,
      brightness: light ? Brightness.light : Brightness.dark,
      surface: surface,
    );
    return ThemeData(
      useMaterial3: true,
      brightness: light ? Brightness.light : Brightness.dark,
      scaffoldBackgroundColor: base,
      colorScheme: scheme,
      cardColor: surface,
      appBarTheme: AppBarTheme(
        backgroundColor: base,
        foregroundColor: light ? const Color(0xFF172235) : Colors.white,
        elevation: 0,
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: surface,
        indicatorColor: accent.withValues(alpha: .18),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'AIR Model Engine',
    debugShowCheckedModeBanner: false,
    theme: appTheme,
    home: AirShell(
      look: look,
      onLookChanged: (value) => setState(() => look = value),
    ),
  );
}

class AirShell extends StatefulWidget {
  const AirShell({super.key, required this.look, required this.onLookChanged});
  final AirLook look;
  final ValueChanged<AirLook> onLookChanged;
  @override
  State<AirShell> createState() => _AirShellState();
}

class _AirShellState extends State<AirShell> {
  int tab = 0;
  @override
  Widget build(BuildContext context) {
    final pages = [
      AirDashboard(look: widget.look, onLookChanged: widget.onLookChanged),
      const SimplePage(title: 'Options Intelligence', icon: Icons.candlestick_chart_rounded, subtitle: 'Discover option opportunities with strike, expiry, premium and liquidity context.'),
      const SimplePage(title: 'AIR QOC Engine', icon: Icons.radar_rounded, subtitle: 'Underlying → volume → option premium → open interest. Evidence-led confluence.'),
      const SimplePage(title: 'Market Data Center', icon: Icons.dataset_rounded, subtitle: 'Historical datasets, market breadth and research workspaces.'),
    ];
    return Scaffold(
      body: SafeArea(child: pages[tab]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: tab,
        onDestinationSelected: (v) => setState(() => tab = v),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.grid_view_rounded), label: 'Home'),
          NavigationDestination(icon: Icon(Icons.show_chart_rounded), label: 'Options'),
          NavigationDestination(icon: Icon(Icons.radar_rounded), label: 'AIR QOC'),
          NavigationDestination(icon: Icon(Icons.storage_rounded), label: 'Data'),
        ],
      ),
    );
  }
}

class AirDashboard extends StatelessWidget {
  const AirDashboard({super.key, required this.look, required this.onLookChanged});
  final AirLook look;
  final ValueChanged<AirLook> onLookChanged;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final light = look == AirLook.light;
    final glass = look == AirLook.glass;
    final accent = cs.primary;
    final panel = Theme.of(context).cardColor;
    final muted = cs.onSurfaceVariant;
    return ListView(
      padding: const EdgeInsets.fromLTRB(18, 12, 18, 28),
      children: [
        Row(children: [
          Container(width: 42, height: 42, decoration: BoxDecoration(
            color: accent.withValues(alpha: .13), borderRadius: BorderRadius.circular(13),
            border: Border.all(color: accent.withValues(alpha: .45))),
            child: Center(child: Text('AIR', style: TextStyle(color: accent, fontWeight: FontWeight.w900, letterSpacing: 1)))),
          const SizedBox(width: 11),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('ANALYTICAL INVESTMENT RESEARCH', style: TextStyle(fontSize: 9, color: muted, letterSpacing: 1, fontWeight: FontWeight.w700)),
            const Text('MODEL ENGINE', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w900, letterSpacing: 1.5)),
          ])),
          PopupMenuButton<AirLook>(
            tooltip: 'Choose appearance',
            initialValue: look,
            onSelected: onLookChanged,
            icon: Icon(Icons.palette_outlined, color: accent),
            itemBuilder: (context) => const [
              PopupMenuItem(value: AirLook.glass, child: Text('Glass theme')),
              PopupMenuItem(value: AirLook.dark, child: Text('Dark theme')),
              PopupMenuItem(value: AirLook.light, child: Text('Light theme')),
            ],
          ),
          CircleAvatar(radius: 17, backgroundColor: panel, child: Icon(Icons.person_outline_rounded, size: 19, color: accent)),
        ]),
        const SizedBox(height: 22),
        Container(
          padding: const EdgeInsets.all(20),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(24),
            gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight,
              colors: light
                ? [const Color(0xFFFFF5DF), const Color(0xFFE8EEF8)]
                : glass
                  ? [const Color(0xCC344C6B), const Color(0xAA19283E), const Color(0x99101828)]
                  : [const Color(0xFF26354B), const Color(0xFF151F30), const Color(0xFF111722)]),
            border: Border.all(color: accent.withValues(alpha: glass ? .55 : .35)),
            boxShadow: [BoxShadow(color: accent.withValues(alpha: glass ? .12 : .06), blurRadius: 28, spreadRadius: 1)],
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [AirTag('INTELLIGENCE, NOT NOISE', color: accent), const Spacer(), Icon(Icons.auto_awesome, color: accent, size: 18)]),
            const SizedBox(height: 17),
            Text('See the setup.\nUnderstand the edge.', style: TextStyle(fontSize: 29, height: 1.12, fontWeight: FontWeight.w900, letterSpacing: -.6, color: light ? const Color(0xFF172235) : Colors.white)),
            const SizedBox(height: 10),
            Text('A research-first view of Indian markets, options confluence and risk.', style: TextStyle(color: light ? const Color(0xFF526176) : const Color(0xFFB8C4D5), height: 1.45, fontSize: 13)),
            const SizedBox(height: 19),
            Row(children: [
              _Metric(value: '4', label: 'EVIDENCE LAYERS', accent: accent),
              const SizedBox(width: 24),
              _Metric(value: '3', label: 'RESEARCH MODES', accent: accent),
              const Spacer(),
              Icon(Icons.arrow_forward_rounded, color: accent),
            ]),
          ]),
        ),
        const SizedBox(height: 22),
        const SectionHeader(title: 'MARKET SNAPSHOT', caption: 'DEMO DATA · NOT LIVE'),
        const SizedBox(height: 11),
        Row(children: [
          Expanded(child: IndexCard(name: 'NIFTY 50', panel: panel, muted: muted)),
          const SizedBox(width: 10),
          Expanded(child: IndexCard(name: 'BANK NIFTY', panel: panel, muted: muted)),
        ]),
        const SizedBox(height: 20),
        const SectionHeader(title: 'MODEL ENGINE SHORTCUTS', caption: 'QUICK ACCESS'),
        const SizedBox(height: 10),
        const ModelEngineQuickTabs(),
        const SizedBox(height: 12),
        const ModelEngineRecordsTable(),
        const SizedBox(height: 10),
        const WeeklyLowRespectDashboardShortcut(),
        const SizedBox(height: 10),
        const SurvivorDashboardShortcut(),
        const SizedBox(height: 20),
        const SectionHeader(title: 'AIR RESEARCH LIBRARY', caption: 'CHAT LOGIC → MODULES'),
        const SizedBox(height: 10),
        const AirResearchLibrary(),
        const SizedBox(height: 23),
        const SectionHeader(title: 'THE AIR DIFFERENCE', caption: 'OUR RESEARCH METHOD'),
        const SizedBox(height: 12),
        CardPanel(child: Column(children: [
          EvidenceRow(number: '01', title: 'Underlying leads', detail: 'Read the stock or index structure first.', icon: Icons.show_chart_rounded, accent: accent, muted: muted),
          EvidenceRow(number: '02', title: 'Volume confirms', detail: 'Look for participation, not just a price move.', icon: Icons.bar_chart_rounded, accent: accent, muted: muted),
          EvidenceRow(number: '03', title: 'Option premium validates', detail: 'Check acceleration, liquidity and strike distance.', icon: Icons.bolt_rounded, accent: accent, muted: muted),
          EvidenceRow(number: '04', title: 'Open interest completes context', detail: 'Assess positioning before qualifying a setup.', icon: Icons.query_stats_rounded, accent: accent, muted: muted, last: true),
        ])),
        const SizedBox(height: 22),
        const SectionHeader(title: 'YOUR RESEARCH DESK', caption: 'BUILT AROUND DECISIONS'),
        const SizedBox(height: 11),
        WorkspaceTile(icon: Icons.radar_rounded, title: 'AIR QOC', subtitle: 'Qualified Options Confluence', accent: accent, panel: panel, muted: muted),
        WorkspaceTile(icon: Icons.discount_rounded, title: 'Options Opportunity Radar', subtitle: 'Premium · expiry · liquidity · strike distance', accent: const Color(0xFF46BFA0), panel: panel, muted: muted),
        WorkspaceTile(icon: Icons.account_tree_rounded, title: 'Market Structure', subtitle: 'CPR · SMC · BOS/CHOCH · order blocks', accent: const Color(0xFF789BEA), panel: panel, muted: muted),
        WorkspaceTile(icon: Icons.fact_check_outlined, title: 'Historical Proof & Risk', subtitle: 'Backtests · setup evidence · invalidation levels', accent: const Color(0xFFB184D9), panel: panel, muted: muted),
        const SizedBox(height: 22),
        const SectionHeader(title: 'MULTI-TIMEFRAME ORDER BLOCKS', caption: 'W · D · M'),
        const SizedBox(height: 11),
        const AirOrderBlockScanner(),
        const SizedBox(height: 14),
        Center(child: Text('AIR MODEL ENGINE  •  INTERNAL LAB', style: TextStyle(color: muted, fontSize: 10, letterSpacing: 1.1))),
      ],
    );
  }
}

class AirTag extends StatelessWidget {
  const AirTag(this.text, {super.key, required this.color});
  final String text; final Color color;
  @override
  Widget build(BuildContext context) => Container(padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
    decoration: BoxDecoration(color: color.withValues(alpha: .13), borderRadius: BorderRadius.circular(30), border: Border.all(color: color.withValues(alpha: .3))),
    child: Text(text, style: TextStyle(fontSize: 9, color: color, fontWeight: FontWeight.w800, letterSpacing: 1)));
}
class _Metric extends StatelessWidget {
  const _Metric({required this.value, required this.label, required this.accent});
  final String value, label; final Color accent;
  @override
  Widget build(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
    Text(value, style: TextStyle(fontSize: 21, color: accent, fontWeight: FontWeight.w900)),
    Text(label, style: TextStyle(fontSize: 8, color: Theme.of(context).colorScheme.onSurfaceVariant, letterSpacing: .8)),
  ]);
}
class SectionHeader extends StatelessWidget {
  const SectionHeader({super.key, required this.title, required this.caption});
  final String title, caption;
  @override
  Widget build(BuildContext context) => Row(children: [
    Expanded(child: Text(title, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w900, letterSpacing: 1.05))),
    Text(caption, style: TextStyle(fontSize: 8, color: Theme.of(context).colorScheme.onSurfaceVariant, letterSpacing: .7, fontWeight: FontWeight.w700)),
  ]);
}
class IndexCard extends StatelessWidget {
  const IndexCard({super.key, required this.name, required this.panel, required this.muted});
  final String name; final Color panel, muted;
  @override
  Widget build(BuildContext context) => Container(padding: const EdgeInsets.all(15),
    decoration: BoxDecoration(color: panel, borderRadius: BorderRadius.circular(17), border: Border.all(color: Theme.of(context).colorScheme.outlineVariant.withValues(alpha: .35))),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(name, style: TextStyle(color: muted, fontSize: 10, fontWeight: FontWeight.bold, letterSpacing: 1)),
      const SizedBox(height: 9), const Text('—', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w900)),
      const SizedBox(height: 3), Text('Awaiting feed', style: TextStyle(fontSize: 10, color: muted)),
    ]));
}
class CardPanel extends StatelessWidget {
  const CardPanel({super.key, required this.child}); final Widget child;
  @override
  Widget build(BuildContext context) => Container(padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(color: Theme.of(context).cardColor, borderRadius: BorderRadius.circular(20),
      border: Border.all(color: Theme.of(context).colorScheme.outlineVariant.withValues(alpha: .35))), child: child);
}
class EvidenceRow extends StatelessWidget {
  const EvidenceRow({super.key, required this.number, required this.title, required this.detail, required this.icon, required this.accent, required this.muted, this.last = false});
  final String number, title, detail; final IconData icon; final Color accent, muted; final bool last;
  @override
  Widget build(BuildContext context) => Padding(padding: EdgeInsets.only(bottom: last ? 0 : 17),
    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Container(width: 34, height: 34, decoration: BoxDecoration(color: accent.withValues(alpha: .12), borderRadius: BorderRadius.circular(10)), child: Icon(icon, color: accent, size: 17)),
      const SizedBox(width: 12), Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('$number  $title', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w800)),
        const SizedBox(height: 4), Text(detail, style: TextStyle(fontSize: 10, color: muted, height: 1.35)),
      ])),
    ]));
}
class WorkspaceTile extends StatelessWidget {
  const WorkspaceTile({super.key, required this.icon, required this.title, required this.subtitle, required this.accent, required this.panel, required this.muted});
  final IconData icon; final String title, subtitle; final Color accent, panel, muted;
  @override
  Widget build(BuildContext context) => Container(margin: const EdgeInsets.only(bottom: 9), padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(color: panel, borderRadius: BorderRadius.circular(16), border: Border.all(color: Theme.of(context).colorScheme.outlineVariant.withValues(alpha: .35))),
    child: Row(children: [
      Container(width: 40, height: 40, decoration: BoxDecoration(color: accent.withValues(alpha: .12), borderRadius: BorderRadius.circular(12)), child: Icon(icon, color: accent, size: 20)),
      const SizedBox(width: 12), Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 12)),
        const SizedBox(height: 4), Text(subtitle, style: TextStyle(color: muted, fontSize: 10)),
      ])),
      Icon(Icons.chevron_right_rounded, color: muted),
    ]));
}
class SimplePage extends StatelessWidget {
  const SimplePage({super.key, required this.title, required this.icon, required this.subtitle});
  final String title, subtitle; final IconData icon;
  @override
  Widget build(BuildContext context) => Center(child: Padding(padding: const EdgeInsets.all(28), child: Column(mainAxisSize: MainAxisSize.min, children: [
    Icon(icon, color: Theme.of(context).colorScheme.primary, size: 54),
    const SizedBox(height: 18), Text(title, style: const TextStyle(fontSize: 23, fontWeight: FontWeight.w900)),
    const SizedBox(height: 9), Text(subtitle, textAlign: TextAlign.center, style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant, height: 1.5)),
    const SizedBox(height: 18), const AirTag('LAB PREVIEW · DATA INTEGRATION PENDING', color: Color(0xFFE5B85C)),
  ])));
}


enum AirCandleDirection { bullish, bearish, neutral }
enum AirOrderBlockSignal { bullish, bearish, none }

class AirCandle {
  const AirCandle({required this.open, required this.high, required this.low, required this.close});
  final double open, high, low, close;
  AirCandleDirection get direction => close > open
      ? AirCandleDirection.bullish
      : close < open ? AirCandleDirection.bearish : AirCandleDirection.neutral;
  bool isInside(AirCandle parent) => high <= parent.high && low >= parent.low;
}

/// Evaluates three completed candles in chronological order:
/// inside-1, parent, inside-2. Both outer candles must be fully
/// contained by the middle candle's high-low range.
AirOrderBlockSignal detectAirOrderBlock(List<AirCandle> candles) {
  if (candles.length < 3) return AirOrderBlockSignal.none;
  final first = candles[candles.length - 3];
  final parent = candles[candles.length - 2];
  final last = candles[candles.length - 1];
  if (!first.isInside(parent) || !last.isInside(parent)) return AirOrderBlockSignal.none;
  if (parent.direction == AirCandleDirection.bearish &&
      first.direction == AirCandleDirection.bullish &&
      last.direction == AirCandleDirection.bullish) {
    return AirOrderBlockSignal.bullish;
  }
  if (parent.direction == AirCandleDirection.bullish &&
      first.direction == AirCandleDirection.bearish &&
      last.direction == AirCandleDirection.bearish) {
    return AirOrderBlockSignal.bearish;
  }
  return AirOrderBlockSignal.none;
}

class AirOrderBlockScanner extends StatefulWidget {
  const AirOrderBlockScanner({super.key});
  @override
  State<AirOrderBlockScanner> createState() => _AirOrderBlockScannerState();
}

class _AirOrderBlockScannerState extends State<AirOrderBlockScanner> {
  String timeframe = 'Daily';
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final muted = cs.onSurfaceVariant;
    final accent = cs.primary;
    return CardPanel(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Expanded(child: Text('AIR Order Block Scanner', style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w900))),
        AirTag('RULE-BASED', color: accent),
      ]),
      const SizedBox(height: 5),
      Text('Find the three-candle containment pattern on completed candles.', style: TextStyle(color: muted, fontSize: 11, height: 1.4)),
      const SizedBox(height: 14),
      SegmentedButton<String>(
        segments: const [
          ButtonSegment(value: 'Weekly', label: Text('W')),
          ButtonSegment(value: 'Daily', label: Text('D')),
          ButtonSegment(value: 'Monthly', label: Text('M')),
        ],
        selected: {timeframe},
        onSelectionChanged: (selection) => setState(() => timeframe = selection.first),
      ),
      const SizedBox(height: 14),
      _OrderBlockPatternRow(
        title: 'Bullish order block',
        detail: 'Green inside 1 → Red parent → Green inside 2',
        signal: 'BULLISH',
        color: const Color(0xFF20A879),
        muted: muted,
      ),
      const SizedBox(height: 10),
      _OrderBlockPatternRow(
        title: 'Bearish order block',
        detail: 'Red inside 1 → Green parent → Red inside 2',
        signal: 'BEARISH',
        color: const Color(0xFFD65A63),
        muted: muted,
      ),
      const SizedBox(height: 13),
      Container(
        width: double.infinity,
        padding: const EdgeInsets.all(11),
        decoration: BoxDecoration(
          color: cs.surfaceContainerHighest.withValues(alpha: .45),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(Icons.info_outline_rounded, color: accent, size: 17),
          const SizedBox(width: 8),
          Expanded(child: Text(
            '$timeframe scan · Waiting for OHLC data feed. Both outer candles must have their full high-low range inside the middle parent candle.',
            style: TextStyle(color: muted, fontSize: 10, height: 1.4),
          )),
        ]),
      ),
    ]));
  }
}

class _OrderBlockPatternRow extends StatelessWidget {
  const _OrderBlockPatternRow({required this.title, required this.detail, required this.signal, required this.color, required this.muted});
  final String title, detail, signal;
  final Color color, muted;
  @override
  Widget build(BuildContext context) => Row(children: [
    Container(width: 8, height: 38, decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(5))),
    const SizedBox(width: 10),
    Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(title, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w800)),
      const SizedBox(height: 3),
      Text(detail, style: TextStyle(fontSize: 9, color: muted)),
    ])),
    Text(signal, style: TextStyle(color: color, fontSize: 9, fontWeight: FontWeight.w900, letterSpacing: .5)),
  ]);
}


class ModelEngineQuickTabs extends StatefulWidget {
  const ModelEngineQuickTabs({super.key});
  @override
  State<ModelEngineQuickTabs> createState() => _ModelEngineQuickTabsState();
}

class _ModelEngineQuickTabsState extends State<ModelEngineQuickTabs> {
  static const labels = ['NEW', 'HOLD', 'RE-ENTRY', 'SL', 'TARGETS', 'EXPIRED', 'EXPIRYSCAN'];
  bool expanded = false;
  String selected = 'NEW';

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final visible = expanded ? labels : labels.take(5).toList();
    return CardPanel(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Wrap(
        spacing: 7,
        runSpacing: 7,
        children: [
          for (final label in visible)
            ChoiceChip(
              label: Text(label, style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w800, letterSpacing: .35)),
              selected: selected == label,
              onSelected: (_) => setState(() => selected = label),
              visualDensity: VisualDensity.compact,
              materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
            ),
          ActionChip(
            avatar: Icon(expanded ? Icons.expand_less_rounded : Icons.expand_more_rounded, size: 16),
            label: Text(expanded ? 'LESS' : 'ALL 7', style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w900)),
            onPressed: () => setState(() => expanded = !expanded),
            visualDensity: VisualDensity.compact,
            materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
          ),
        ],
      ),
      const SizedBox(height: 12),
      Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(
          color: cs.primary.withValues(alpha: .08),
          borderRadius: BorderRadius.circular(11),
          border: Border.all(color: cs.primary.withValues(alpha: .18)),
        ),
        child: Row(children: [
          Icon(Icons.dashboard_customize_outlined, size: 16, color: cs.primary),
          const SizedBox(width: 8),
          Expanded(child: Text('Selected workspace: $selected', style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w800))),
          Text(expanded ? '7 TABS' : '5 OF 7', style: TextStyle(fontSize: 8, color: cs.onSurfaceVariant, fontWeight: FontWeight.w800, letterSpacing: .7)),
        ]),
      ),
    ]));
  }
}


class AirResearchItem {
  const AirResearchItem(this.name, this.subtitle, this.category, this.icon);
  final String name, subtitle, category;
  final IconData icon;
}

class AirResearchLibrary extends StatefulWidget {
  const AirResearchLibrary({super.key});
  @override
  State<AirResearchLibrary> createState() => _AirResearchLibraryState();
}

class _AirResearchLibraryState extends State<AirResearchLibrary> {
  final search = TextEditingController();
  String category = 'All';
  bool showAll = false;
  String? selected;
  static const items = [
    AirResearchItem('AIR QOC LIVE / POSITIONAL / POST-MARKET', 'Options confluence, premium movement, OI, volume and liquidity validation.', 'Options', Icons.radar_rounded),
    AirResearchItem('AIR QOC HIGH TARGET', 'Discounted premium research, exhaustion, reversal and target planning.', 'Options', Icons.track_changes_rounded),
    AirResearchItem('EXPIRYSCAN', 'Expiry-wise index and stock option opportunity discovery.', 'Options', Icons.calendar_month_rounded),
    AirResearchItem('Stock Options Recommendations', 'Stock-first selection followed by CE/PE contract validation.', 'Options', Icons.candlestick_chart_rounded),
    AirResearchItem('NSE Reversal Watchlist', 'Three-candle reversal, underlying OHLCV and next-session validation.', 'Setups', Icons.swap_vert_circle_outlined),
    AirResearchItem('WEEKLY LOW RESPECT REVERSAL', 'Bullish weekly reversal: weekly low holds with a bullish inverted hammer (close above open), or a bottom formation confirms with a break above the weekly high.', 'Setups', Icons.trending_up_rounded),
    AirResearchItem('Parabolic Selling Reversal', 'Selling exhaustion, liquidity sweep, CHOCH/BOS and demand-zone confirmation.', 'Setups', Icons.trending_down_rounded),
    AirResearchItem('Monthly Double Bottom Stocks', 'Monthly base formation, neckline and confirmation tracking.', 'Setups', Icons.stacked_line_chart_rounded),
    AirResearchItem('Fib 50% Rejection Stocks', 'Fibonacci retracement rejection and price-action screening.', 'Setups', Icons.show_chart_rounded),
    AirResearchItem('WIN TRADING SETUPS', 'Structured winning-setup research with entry, stop, targets, confirmation and invalidation tracking.', 'Setups', Icons.bolt_rounded),
    AirResearchItem('SMC Scanner', 'Scan market structure for liquidity sweeps, supply/demand, order blocks, CHOCH, BOS and retests.', 'Structure', Icons.account_tree_rounded),
    AirResearchItem('Inside-Candle Order Blocks', 'Green-red-green bullish and red-green-red bearish containment patterns.', 'Structure', Icons.view_agenda_rounded),
    AirResearchItem('NARROW CPR DAILY', 'Daily narrow CPR width scan, levels, range context and next-session breakout watchlist.', 'Structure', Icons.compress_rounded),
    AirResearchItem('NARROW CPR WEEKLY', 'Weekly narrow CPR scan, multi-session compression and directional breakout context.', 'Structure', Icons.calendar_view_week_rounded),
    AirResearchItem('NARROW CPR MONTHLY', 'Monthly narrow CPR scan, positional compression and monthly pivot levels.', 'Structure', Icons.calendar_month_rounded),
    AirResearchItem('CPR CHECK', 'CPR levels, breakout/retest conditions and directional context.', 'Structure', Icons.rule_rounded),
    AirResearchItem('Watchlist Screening Request', 'Custom universe scans, ranking, filters and exportable watchlists.', 'Research', Icons.filter_alt_rounded),
    AirResearchItem('AIR Historical Proof', 'Session-wise backtests, validation logs and performance evidence.', 'Research', Icons.fact_check_outlined),
    AirResearchItem('Sensex Capital Calculation', 'Lot size, quantity, premium and capital requirement calculator.', 'Calculators', Icons.calculate_outlined),
    AirResearchItem('Total K Calculation', 'Quantity and capital arithmetic workspace.', 'Calculators', Icons.functions_rounded),
    AirResearchItem('Convert USD to INR Crores', 'Currency and large-number conversion utility.', 'Calculators', Icons.currency_exchange_rounded),
  ];
  static const categories = ['All', 'Options', 'Setups', 'Structure', 'Research', 'Calculators'];

  @override
  void dispose() {
    search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final q = search.text.trim().toLowerCase();
    final filtered = items.where((item) =>
      (category == 'All' || item.category == category) &&
      (q.isEmpty || item.name.toLowerCase().contains(q) || item.subtitle.toLowerCase().contains(q))
    ).toList();
    final shown = showAll || q.isNotEmpty || category != 'All' ? filtered : filtered.take(5).toList();
    return CardPanel(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Expanded(child: Text('Your chat workflows, organised', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w900))),
        AirTag('${items.length} MODULES', color: cs.primary),
      ]),
      const SizedBox(height: 10),
      TextField(
        controller: search,
        onChanged: (_) => setState(() {}),
        decoration: InputDecoration(
          hintText: 'Search a strategy, scanner or calculator',
          prefixIcon: const Icon(Icons.search_rounded, size: 18),
          isDense: true,
          filled: true,
          fillColor: cs.surfaceContainerHighest.withValues(alpha: .35),
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
        ),
      ),
      const SizedBox(height: 10),
      SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(children: [
          for (final value in categories)
            Padding(padding: const EdgeInsets.only(right: 6), child: ChoiceChip(
              label: Text(value, style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w800)),
              selected: category == value,
              onSelected: (_) => setState(() { category = value; showAll = false; }),
              visualDensity: VisualDensity.compact,
            )),
        ]),
      ),
      const SizedBox(height: 8),
      for (final item in shown)
        _ResearchLibraryTile(
          item: item,
          selected: selected == item.name,
          onTap: () => setState(() => selected = selected == item.name ? null : item.name),
        ),
      if (filtered.isEmpty)
        Padding(padding: const EdgeInsets.all(12), child: Text('No matching AIR modules found.', style: TextStyle(color: cs.onSurfaceVariant, fontSize: 11))),
      if (filtered.length > 5 && q.isEmpty && category == 'All')
        Align(alignment: Alignment.center, child: TextButton.icon(
          onPressed: () => setState(() => showAll = !showAll),
          icon: Icon(showAll ? Icons.expand_less_rounded : Icons.expand_more_rounded),
          label: Text(showAll ? 'SHOW LESS' : 'VIEW ALL MODULES'),
        )),
      if (selected != null)
        Container(
          width: double.infinity,
          margin: const EdgeInsets.only(top: 8),
          padding: const EdgeInsets.all(11),
          decoration: BoxDecoration(color: cs.primary.withValues(alpha: .08), borderRadius: BorderRadius.circular(11)),
          child: Text('$selected selected · Module interface preview. Logic and live data connections will be enabled module by module.',
            style: TextStyle(fontSize: 10, height: 1.4, color: cs.onSurface)),
        ),
    ]));
  }
}

class _ResearchLibraryTile extends StatelessWidget {
  const _ResearchLibraryTile({required this.item, required this.selected, required this.onTap});
  final AirResearchItem item;
  final bool selected;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Padding(padding: const EdgeInsets.only(top: 5), child: Material(
      color: selected ? cs.primary.withValues(alpha: .09) : Colors.transparent,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10), child: Row(children: [
          Container(width: 34, height: 34, decoration: BoxDecoration(color: cs.primary.withValues(alpha: .1), borderRadius: BorderRadius.circular(10)),
            child: Icon(item.icon, color: cs.primary, size: 17)),
          const SizedBox(width: 10),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(item.name, style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w800)),
            const SizedBox(height: 3),
            Text(item.subtitle, maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 9, height: 1.3, color: cs.onSurfaceVariant)),
          ])),
          const SizedBox(width: 5),
          Icon(selected ? Icons.expand_less_rounded : Icons.chevron_right_rounded, size: 18, color: cs.onSurfaceVariant),
        ])),
      ),
    ));
  }
}


class WeeklyLowRespectDashboardShortcut extends StatelessWidget {
  const WeeklyLowRespectDashboardShortcut({super.key});

  void _openDetails(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Theme.of(context).cardColor,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 28),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Icon(Icons.trending_up_rounded, color: cs.primary, size: 22),
              const SizedBox(width: 9),
              const Expanded(child: Text('WEEKLY LOW RESPECT REVERSAL', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w900))),
              AirTag('SETUP', color: cs.primary),
            ]),
            const SizedBox(height: 16),
            const Text('Setup A · Bullish inverted hammer', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800)),
            const SizedBox(height: 6),
            Text('Weekly low holds as support. Weekly candle forms an inverted hammer near the bottom, with a prominent upper wick and close above open.', style: TextStyle(fontSize: 11, height: 1.45, color: cs.onSurfaceVariant)),
            const SizedBox(height: 14),
            const Text('Setup B · Breakout confirmation', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800)),
            const SizedBox(height: 6),
            Text('After a bottom formation, monitor a confirmed break above the relevant weekly high. Define invalidation around the support structure.', style: TextStyle(fontSize: 11, height: 1.45, color: cs.onSurfaceVariant)),
            const SizedBox(height: 14),
            Container(width: double.infinity, padding: const EdgeInsets.all(11),
              decoration: BoxDecoration(color: cs.surfaceContainerHighest.withValues(alpha: .45), borderRadius: BorderRadius.circular(12)),
              child: Text('Scanner status: waiting for verified weekly OHLC data. This shortcut opens the strategy rules; it does not yet produce live signals.', style: TextStyle(fontSize: 10, height: 1.4, color: cs.onSurfaceVariant))),
          ]),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Material(
      color: Theme.of(context).cardColor,
      borderRadius: BorderRadius.circular(16),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: () => _openDetails(context),
        child: Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: cs.primary.withValues(alpha: .38)),
          ),
          child: Row(children: [
            Container(width: 40, height: 40,
              decoration: BoxDecoration(color: cs.primary.withValues(alpha: .13), borderRadius: BorderRadius.circular(12)),
              child: Icon(Icons.trending_up_rounded, color: cs.primary, size: 21)),
            const SizedBox(width: 12),
            const Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('WEEKLY LOW RESPECT', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w900, letterSpacing: .4)),
              SizedBox(height: 4),
              Text('One-tap reversal strategy', style: TextStyle(fontSize: 10, color: Colors.grey)),
            ])),
            Icon(Icons.arrow_forward_ios_rounded, size: 15, color: cs.primary),
          ]),
        ),
      ),
    );
  }
}


class SurvivorDashboardShortcut extends StatelessWidget {
  const SurvivorDashboardShortcut({super.key});

  void _openSurvivor(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Theme.of(context).cardColor,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 28),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Icon(Icons.shield_rounded, color: cs.primary, size: 23),
              const SizedBox(width: 9),
              const Expanded(child: Text('SURVIVOR', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900, letterSpacing: .8))),
              AirTag('HIGH PRIORITY', color: const Color(0xFFE5B85C)),
            ]),
            const SizedBox(height: 12),
            Text('AIR Survivor research workspace', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: cs.onSurface)),
            const SizedBox(height: 6),
            Text('A dedicated high-priority watch for option contracts with 7 or fewer calendar days to expiry, alongside resilient-stock research. These are watch candidates for close monitoring—not automatic entries or rejections. Apply the normal setup and risk validation before any trade.', style: TextStyle(fontSize: 11, height: 1.45, color: cs.onSurfaceVariant)),
            const SizedBox(height: 14),
            Container(width: double.infinity, padding: const EdgeInsets.all(11),
              decoration: BoxDecoration(color: cs.surfaceContainerHighest.withValues(alpha: .45), borderRadius: BorderRadius.circular(12)),
              child: Text('SURVIVOR rule: highlight contracts with 7 or fewer calendar days remaining. No expiry-age rejection applies in other one-taps. Live contract data and validated survivor results are not connected yet.', style: TextStyle(fontSize: 10, height: 1.4, color: cs.onSurfaceVariant))),
          ]),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Material(
      color: Theme.of(context).cardColor,
      borderRadius: BorderRadius.circular(16),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: () => _openSurvivor(context),
        child: Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: const Color(0xFFE5B85C).withValues(alpha: .75), width: 1.4),
            boxShadow: [BoxShadow(color: const Color(0xFFE5B85C).withValues(alpha: .08), blurRadius: 15)],
          ),
          child: Row(children: [
            Container(width: 40, height: 40,
              decoration: BoxDecoration(color: const Color(0xFFE5B85C).withValues(alpha: .16), borderRadius: BorderRadius.circular(12)),
              child: const Icon(Icons.shield_rounded, color: Color(0xFFE5B85C), size: 22)),
            const SizedBox(width: 12),
            const Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('SURVIVOR', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w900, letterSpacing: .7)),
              SizedBox(height: 4),
              Text('Dedicated 7-day contract shelf-life watch', style: TextStyle(fontSize: 10, color: Colors.grey)),
            ])),
            const AirTag('PRIORITY 1', color: Color(0xFFE5B85C)),
            const SizedBox(width: 7),
            Icon(Icons.arrow_forward_ios_rounded, size: 14, color: cs.primary),
          ]),
        ),
      ),
    );
  }
}


class ModelEngineRecordsTable extends StatelessWidget {
  const ModelEngineRecordsTable({super.key});

  static const columns = [
    'Signal Date',
    'Entry Date',
    'Entry Classification',
    'Entry Price',
    'Latest Price',
    'Expiry Date',
    'Days to Expiry',
    'Stop',
    'Lot Size',
    'P&L',
  ];

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final muted = cs.onSurfaceVariant;
    return CardPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            const Expanded(child: Text('MODEL ENGINE RECORDS',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w900, letterSpacing: .8))),
            AirTag('MASTER TABLE', color: cs.primary),
          ]),
          const SizedBox(height: 5),
          Text('Shows contract expiry date and days to expiry across every options one-tap. Seven-day contracts get a dedicated SURVIVOR watch classification, never an automatic rejection.',
            style: TextStyle(fontSize: 10, color: muted)),
          const SizedBox(height: 12),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              columnSpacing: 18,
              horizontalMargin: 8,
              headingRowHeight: 42,
              dataRowMinHeight: 46,
              dataRowMaxHeight: 54,
              columns: [
                for (final column in columns)
                  DataColumn(label: Text(column,
                    style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w900))),
              ],
              rows: const [],
            ),
          ),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 12),
            decoration: BoxDecoration(
              color: cs.surfaceContainerHighest.withValues(alpha: .3),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Row(children: [
              Icon(Icons.sync_rounded, size: 16, color: muted),
              const SizedBox(width: 8),
              Expanded(child: Text(
                'No ledger records synced yet. Every options one-tap displays actual expiry date and calendar days remaining. No DTE-based rejection is applied: contracts with 7 or fewer calendar days remaining are highlighted for the dedicated SURVIVOR watch, while all other contracts remain eligible for their respective setup rules. Expired contracts are clearly marked EXPIRED; missing expiry data is shown as unavailable.',
                style: TextStyle(fontSize: 10, height: 1.4, color: muted),
              )),
            ]),
          ),
        ],
      ),
    );
  }
}
