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
    final cs = Theme.of(context).colorScheme;
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
        const SizedBox(height: 14),
        Center(child: Text('AIR MODEL ENGINE  •  INTERNAL LAB', style: TextStyle(color: muted, fontSize: 10, letterSpacing: 1.1))),
      ],
    );
  }
}

class AirTag extends StatelessWidget {
  const AirTag(this.text, {required this.color});
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
