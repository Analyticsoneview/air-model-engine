import 'package:flutter/material.dart';

void main() => runApp(const AirModelEngineApp());

const ink = Color(0xFF090D16);
const panel = Color(0xFF121A28);
const gold = Color(0xFFE5B85C);
const muted = Color(0xFF8D9AAF);
const mint = Color(0xFF46D6A0);
const red = Color(0xFFFF6B75);

class AirModelEngineApp extends StatelessWidget {
  const AirModelEngineApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'AIR Model Engine',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      brightness: Brightness.dark,
      scaffoldBackgroundColor: ink,
      colorScheme: ColorScheme.fromSeed(seedColor: gold, brightness: Brightness.dark),
      useMaterial3: true,
      fontFamily: 'Roboto',
    ),
    home: const AirShell(),
  );
}

class AirShell extends StatefulWidget {
  const AirShell({super.key});
  @override
  State<AirShell> createState() => _AirShellState();
}

class _AirShellState extends State<AirShell> {
  int tab = 0;
  final screens = const [AirDashboard(), SimplePage(title:'Options Intelligence', icon:Icons.candlestick_chart_rounded, subtitle:'Discover option opportunities with strike, expiry, premium and liquidity context.'), SimplePage(title:'AIR QOC Engine', icon:Icons.radar_rounded, subtitle:'Underlying → volume → option premium → open interest. Evidence-led confluence.'), SimplePage(title:'Market Data Center', icon:Icons.dataset_rounded, subtitle:'Historical datasets, market breadth and research workspaces.')];
  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(child: screens[tab]),
    bottomNavigationBar: NavigationBar(
      backgroundColor: const Color(0xFF0D1420),
      indicatorColor: gold.withValues(alpha:.16),
      selectedIndex: tab,
      onDestinationSelected: (v)=>setState(()=>tab=v),
      destinations: const [
        NavigationDestination(icon:Icon(Icons.grid_view_rounded),label:'Home'),
        NavigationDestination(icon:Icon(Icons.show_chart_rounded),label:'Options'),
        NavigationDestination(icon:Icon(Icons.radar_rounded),label:'AIR QOC'),
        NavigationDestination(icon:Icon(Icons.storage_rounded),label:'Data'),
      ],
    ),
  );
}

class AirDashboard extends StatelessWidget {
  const AirDashboard({super.key});
  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.fromLTRB(18,12,18,28),
    children: [
      Row(children:[
        Container(width:42,height:42,decoration:BoxDecoration(color:gold.withValues(alpha:.13),borderRadius:BorderRadius.circular(13),border:Border.all(color:gold.withValues(alpha:.4))),child:const Center(child:Text('AIR',style:TextStyle(color:gold,fontWeight:FontWeight.w900,letterSpacing:1)))),
        const SizedBox(width:11),
        const Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text('ANALYTICAL INVESTMENT RESEARCH',style:TextStyle(fontSize:10,color:muted,letterSpacing:1.1,fontWeight:FontWeight.w700)),Text('MODEL ENGINE',style:TextStyle(fontSize:17,fontWeight:FontWeight.w900,letterSpacing:1.6))])),
        IconButton(onPressed:(){},icon:const Icon(Icons.notifications_none_rounded,color:gold)),
        CircleAvatar(radius:17,backgroundColor:panel,child:const Icon(Icons.person_outline_rounded,size:19,color:gold)),
      ]),
      const SizedBox(height:24),
      Container(
        padding:const EdgeInsets.all(20),
        decoration:BoxDecoration(borderRadius:BorderRadius.circular(24),gradient:const LinearGradient(begin:Alignment.topLeft,end:Alignment.bottomRight,colors:[Color(0xFF26354B),Color(0xFF151F30),Color(0xFF111722)]),border:Border.all(color:gold.withValues(alpha:.35)),boxShadow:[BoxShadow(color:gold.withValues(alpha:.07),blurRadius:28,spreadRadius:1)]),
        child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[
          Row(children:[const _Tag('INTELLIGENCE, NOT NOISE'),const Spacer(),Icon(Icons.auto_awesome,color:gold.withValues(alpha:.9),size:18)]),
          const SizedBox(height:17),
          const Text('See the setup.\nUnderstand the edge.',style:TextStyle(fontSize:29,height:1.12,fontWeight:FontWeight.w900,letterSpacing:-.6)),
          const SizedBox(height:10),
          const Text('A research-first view of Indian markets, options confluence and risk.',style:TextStyle(color:Color(0xFFB8C4D5),height:1.45,fontSize:13)),
          const SizedBox(height:19),
          Row(children:[_HeroMetric(value:'4',label:'EVIDENCE LAYERS'),const SizedBox(width:24),_HeroMetric(value:'3',label:'RESEARCH MODES'),const Spacer(),const Icon(Icons.arrow_forward_rounded,color:gold)]),
        ]),
      ),
      const SizedBox(height:22),
      const _SectionHeader(title:'MARKET SNAPSHOT',caption:'DEMO DATA · NOT LIVE'),
      const SizedBox(height:11),
      Row(children:const [
        Expanded(child:_IndexCard(name:'NIFTY 50',value:'—',change:'Awaiting feed')),
        SizedBox(width:10),
        Expanded(child:_IndexCard(name:'BANK NIFTY',value:'—',change:'Awaiting feed')),
      ]),
      const SizedBox(height:23),
      const _SectionHeader(title:'THE AIR DIFFERENCE',caption:'OUR RESEARCH METHOD'),
      const SizedBox(height:12),
      Container(padding:const EdgeInsets.all(16),decoration:BoxDecoration(color:panel,borderRadius:BorderRadius.circular(20),border:Border.all(color:Colors.white.withValues(alpha:.06))),child:Column(children:const [
        _EvidenceRow(number:'01',title:'Underlying leads',detail:'Read the stock or index structure first.',icon:Icons.show_chart_rounded),
        _EvidenceRow(number:'02',title:'Volume confirms',detail:'Look for participation, not just a price move.',icon:Icons.bar_chart_rounded),
        _EvidenceRow(number:'03',title:'Option premium validates',detail:'Check acceleration, liquidity and strike distance.',icon:Icons.bolt_rounded),
        _EvidenceRow(number:'04',title:'Open interest completes context',detail:'Assess positioning before qualifying a setup.',icon:Icons.query_stats_rounded,last:true),
      ])),
      const SizedBox(height:22),
      const _SectionHeader(title:'YOUR RESEARCH DESK',caption:'BUILT AROUND DECISIONS'),
      const SizedBox(height:11),
      const _WorkspaceTile(icon:Icons.radar_rounded,title:'AIR QOC',subtitle:'Qualified Options Confluence',accent:gold),
      const _WorkspaceTile(icon:Icons.discount_rounded,title:'Options Opportunity Radar',subtitle:'Premium · expiry · liquidity · strike distance',accent:mint),
      const _WorkspaceTile(icon:Icons.account_tree_rounded,title:'Market Structure',subtitle:'CPR · SMC · BOS/CHOCH · order blocks',accent:Color(0xFF8DAEFF)),
      const _WorkspaceTile(icon:Icons.fact_check_outlined,title:'Historical Proof & Risk',subtitle:'Backtests · setup evidence · invalidation levels',accent:Color(0xFFD49CFF)),
      const SizedBox(height:15),
      const Center(child:Text('AIR MODEL ENGINE  •  INTERNAL LAB',style:TextStyle(color:Color(0xFF657187),fontSize:10,letterSpacing:1.2))),
    ],
  );
}

class _Tag extends StatelessWidget {
  const _Tag(this.text);
  final String text;
  @override
  Widget build(BuildContext context)=>Container(padding:const EdgeInsets.symmetric(horizontal:9,vertical:6),decoration:BoxDecoration(color:gold.withValues(alpha:.13),borderRadius:BorderRadius.circular(30),border:Border.all(color:gold.withValues(alpha:.25))),child:Text(text,style:const TextStyle(fontSize:9,color:gold,fontWeight:FontWeight.w800,letterSpacing:1)));
}
class _HeroMetric extends StatelessWidget {
  const _HeroMetric({required this.value,required this.label});
  final String value,label;
  @override
  Widget build(BuildContext context)=>Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text(value,style:const TextStyle(fontSize:21,color:gold,fontWeight:FontWeight.w900)),Text(label,style:const TextStyle(fontSize:8,color:muted,letterSpacing:.8))]);
}
class _SectionHeader extends StatelessWidget {
  const _SectionHeader({required this.title,required this.caption});
  final String title,caption;
  @override
  Widget build(BuildContext context)=>Row(children:[Expanded(child:Text(title,style:const TextStyle(fontSize:13,fontWeight:FontWeight.w900,letterSpacing:1.1))),Text(caption,style:const TextStyle(fontSize:8,color:muted,letterSpacing:.8,fontWeight:FontWeight.w700))]);
}
class _IndexCard extends StatelessWidget {
  const _IndexCard({required this.name,required this.value,required this.change});
  final String name,value,change;
  @override
  Widget build(BuildContext context)=>Container(padding:const EdgeInsets.all(15),decoration:BoxDecoration(color:panel,borderRadius:BorderRadius.circular(17),border:Border.all(color:Colors.white.withValues(alpha:.06))),child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text(name,style:const TextStyle(color:muted,fontSize:10,fontWeight:FontWeight.bold,letterSpacing:1)),const SizedBox(height:9),Text(value,style:const TextStyle(fontSize:22,fontWeight:FontWeight.w900)),const SizedBox(height:3),Text(change,style:const TextStyle(fontSize:10,color:muted))]));
}
class _EvidenceRow extends StatelessWidget {
  const _EvidenceRow({required this.number,required this.title,required this.detail,required this.icon,this.last=false});
  final String number,title,detail; final IconData icon; final bool last;
  @override
  Widget build(BuildContext context)=>Padding(padding:EdgeInsets.only(bottom:last?0:17),child:Row(crossAxisAlignment:CrossAxisAlignment.start,children:[Container(width:34,height:34,decoration:BoxDecoration(color:gold.withValues(alpha:.1),borderRadius:BorderRadius.circular(10)),child:Icon(icon,color:gold,size:17)),const SizedBox(width:12),Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text('$number  $title',style:const TextStyle(fontSize:12,fontWeight:FontWeight.w800)),const SizedBox(height:4),Text(detail,style:const TextStyle(fontSize:10,color:muted,height:1.35))]))]));
}
class _WorkspaceTile extends StatelessWidget {
  const _WorkspaceTile({required this.icon,required this.title,required this.subtitle,required this.accent});
  final IconData icon; final String title,subtitle; final Color accent;
  @override
  Widget build(BuildContext context)=>Container(margin:const EdgeInsets.only(bottom:9),padding:const EdgeInsets.all(14),decoration:BoxDecoration(color:panel,borderRadius:BorderRadius.circular(16),border:Border.all(color:Colors.white.withValues(alpha:.055))),child:Row(children:[Container(width:40,height:40,decoration:BoxDecoration(color:accent.withValues(alpha:.12),borderRadius:BorderRadius.circular(12)),child:Icon(icon,color:accent,size:20)),const SizedBox(width:12),Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text(title,style:const TextStyle(fontWeight:FontWeight.w800,fontSize:12)),const SizedBox(height:4),Text(subtitle,style:const TextStyle(color:muted,fontSize:10))])),const Icon(Icons.chevron_right_rounded,color:muted)]);
}
class SimplePage extends StatelessWidget {
  const SimplePage({super.key,required this.title,required this.icon,required this.subtitle});
  final String title,subtitle; final IconData icon;
  @override
  Widget build(BuildContext context)=>Center(child:Padding(padding:const EdgeInsets.all(28),child:Column(mainAxisSize:MainAxisSize.min,children:[Icon(icon,color:gold,size:54),const SizedBox(height:18),Text(title,style:const TextStyle(fontSize:23,fontWeight:FontWeight.w900)),const SizedBox(height:9),Text(subtitle,textAlign:TextAlign.center,style:const TextStyle(color:muted,height:1.5)),const SizedBox(height:18),const _Tag('LAB PREVIEW · DATA INTEGRATION PENDING') ])));
}
