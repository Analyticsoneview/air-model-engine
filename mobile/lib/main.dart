import 'package:flutter/material.dart';

void main() => runApp(const AirModelEngineApp());

class AirModelEngineApp extends StatelessWidget {
  const AirModelEngineApp({super.key});

  @override
  Widget build(BuildContext context) {
    const gold = Color(0xFFD6AD60);
    return MaterialApp(
      title: 'AIR Model Engine',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF101114),
        colorScheme: ColorScheme.fromSeed(
          seedColor: gold,
          brightness: Brightness.dark,
        ),
        appBarTheme: const AppBarTheme(
          backgroundColor: Color(0xFF101114),
          foregroundColor: Colors.white,
          centerTitle: false,
        ),
        useMaterial3: true,
      ),
      home: const AirHome(),
    );
  }
}

class AirHome extends StatefulWidget {
  const AirHome({super.key});

  @override
  State<AirHome> createState() => _AirHomeState();
}

class _AirHomeState extends State<AirHome> {
  int selected = 0;
  static const pages = <Widget>[
    DashboardScreen(),
    PlaceholderScreen(title: 'Options', subtitle: 'Options workspace will appear here.'),
    PlaceholderScreen(title: 'AIR QOC', subtitle: 'Qualified Options Confluence workspace.'),
    PlaceholderScreen(title: 'Data Center', subtitle: 'Market data and historical datasets.'),
  ];
  static const labels = ['Dashboard', 'Options', 'AIR QOC', 'Data'];
  static const icons = [
    Icons.dashboard_rounded,
    Icons.candlestick_chart_rounded,
    Icons.track_changes_rounded,
    Icons.storage_rounded,
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Row(
          children: [
            Text('AIR', style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: 2, color: Color(0xFFD6AD60))),
            SizedBox(width: 10),
            Text('MODEL ENGINE', style: TextStyle(fontSize: 15, letterSpacing: 1.2)),
          ],
        ),
      ),
      body: SafeArea(child: pages[selected]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: selected,
        onDestinationSelected: (value) => setState(() => selected = value),
        destinations: [
          for (var i = 0; i < labels.length; i++)
            NavigationDestination(icon: Icon(icons[i]), label: labels[i]),
        ],
      ),
    );
  }
}

class DashboardScreen extends StatelessWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(18),
      children: [
        const Text('INTERNAL LAB BUILD', style: TextStyle(color: Color(0xFFD6AD60), letterSpacing: 2, fontSize: 11, fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        Text('Analytical Investment Research', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
        const SizedBox(height: 6),
        const Text('Your market research workspace', style: TextStyle(color: Colors.white60)),
        const SizedBox(height: 22),
        const _StatusCard(),
        const SizedBox(height: 14),
        const _FeatureCard(icon: Icons.candlestick_chart, title: 'Options workspace', detail: 'Option-chain interface — integration pending'),
        const _FeatureCard(icon: Icons.track_changes, title: 'AIR QOC', detail: 'Live, positional and post-market workflows — integration pending'),
        const _FeatureCard(icon: Icons.storage, title: 'Data Center', detail: 'Historical and live market data — integration pending'),
        const SizedBox(height: 16),
        const Text('This lab build validates navigation and layout only. It does not provide live market data, trading signals or order placement.', style: TextStyle(color: Colors.white54, fontSize: 12)),
      ],
    );
  }
}

class _StatusCard extends StatelessWidget {
  const _StatusCard();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: const Color(0xFFD6AD60).withValues(alpha: .5)),
        gradient: const LinearGradient(colors: [Color(0xFF28231B), Color(0xFF17181C)]),
      ),
      child: const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('SYSTEM STATUS', style: TextStyle(color: Color(0xFFD6AD60), fontSize: 11, letterSpacing: 1.5)),
          SizedBox(height: 10),
          Text('Lab shell ready', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
          SizedBox(height: 5),
          Text('Backend and market-data connections are not configured yet.', style: TextStyle(color: Colors.white60)),
        ],
      ),
    );
  }
}

class _FeatureCard extends StatelessWidget {
  const _FeatureCard({required this.icon, required this.title, required this.detail});
  final IconData icon;
  final String title;
  final String detail;

  @override
  Widget build(BuildContext context) {
    return Card(
      color: const Color(0xFF1A1C21),
      margin: const EdgeInsets.only(bottom: 10),
      child: ListTile(
        leading: Icon(icon, color: const Color(0xFFD6AD60)),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text(detail),
        trailing: const Icon(Icons.chevron_right, color: Colors.white38),
      ),
    );
  }
}

class PlaceholderScreen extends StatelessWidget {
  const PlaceholderScreen({super.key, required this.title, required this.subtitle});
  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(28),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.construction_rounded, size: 48, color: Color(0xFFD6AD60)),
          const SizedBox(height: 16),
          Text(title, style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 8),
          Text(subtitle, textAlign: TextAlign.center, style: const TextStyle(color: Colors.white60)),
          const SizedBox(height: 18),
          const Text('Internal lab placeholder', style: TextStyle(color: Color(0xFFD6AD60), fontSize: 12)),
        ],
      ),
    ),
  );
}
