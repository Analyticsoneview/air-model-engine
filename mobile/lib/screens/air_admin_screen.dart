import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../services/air_api_client.dart';

class AirAdminScreen extends StatefulWidget {
  const AirAdminScreen({super.key});

  @override
  State<AirAdminScreen> createState() => _AirAdminScreenState();
}

class _AirAdminScreenState extends State<AirAdminScreen> {
  final AirApiClient _api = AirApiClient();
  List<Map<String, dynamic>> _requests = [];
  String _filter = 'PENDING';
  String? _error;
  bool _loading = false;

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
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final requests = await _api.operatorAccessRequests(
        status: _filter == 'ALL' ? null : _filter,
      );
      if (mounted) setState(() => _requests = requests);
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _review(Map<String, dynamic> request, String status) async {
    final id = request['request_id']?.toString();
    if (id == null || id.isEmpty) return;
    final noteController = TextEditingController();
    final note = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text('$status access?'),
        content: TextField(
          controller: noteController,
          maxLength: 500,
          decoration: const InputDecoration(
            labelText: 'Administrator note (optional)',
            border: OutlineInputBorder(),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('CANCEL'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, noteController.text),
            child: Text(status),
          ),
        ],
      ),
    );
    noteController.dispose();
    if (note == null) return;
    setState(() => _loading = true);
    try {
      await _api.reviewOperatorAccessRequest(id, status, note: note);
      await _load();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Color _statusColor(BuildContext context, String status) {
    switch (status) {
      case 'APPROVED':
        return Colors.green;
      case 'REJECTED':
      case 'BLOCKED':
        return Theme.of(context).colorScheme.error;
      default:
        return Colors.amber.shade800;
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        title: const Text('AIR ADMINISTRATION'),
        actions: [
          IconButton(
            tooltip: 'Manage broker accounts',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => const AirAdminBrokerAccountsScreen(),
              ),
            ),
            icon: const Icon(Icons.account_balance_rounded),
          ),
          IconButton(
            tooltip: 'Market data sources',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => const AirAdminMarketDataSourcesScreen(),
              ),
            ),
            icon: const Icon(Icons.candlestick_chart_rounded),
          ),
          IconButton(
            tooltip: 'Execution controls and broker masters',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => const AirAdminExecutionScreen(),
              ),
            ),
            icon: const Icon(Icons.tune_rounded),
          ),
          IconButton(
            tooltip: 'Telegram destinations',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => const AirAdminTelegramScreen(),
              ),
            ),
            icon: const Icon(Icons.telegram_rounded),
          ),
          IconButton(
            tooltip: 'Refresh requests',
            onPressed: _loading ? null : _load,
            icon: const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'CUSTOMER DEVICE ACCESS',
                  style: TextStyle(fontSize: 11, fontWeight: FontWeight.w900, letterSpacing: .8),
                ),
                const SizedBox(height: 5),
                Text(
                  'Review requests submitted from the AIR app. Approval grants access to this mobile number on the requesting device. Blocking revokes its active sessions.',
                  style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant, height: 1.4),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: _filter,
                  decoration: const InputDecoration(
                    labelText: 'Request status',
                    border: OutlineInputBorder(),
                    isDense: true,
                  ),
                  items: const [
                    DropdownMenuItem(value: 'PENDING', child: Text('Pending')),
                    DropdownMenuItem(value: 'APPROVED', child: Text('Approved')),
                    DropdownMenuItem(value: 'REJECTED', child: Text('Rejected')),
                    DropdownMenuItem(value: 'BLOCKED', child: Text('Blocked')),
                    DropdownMenuItem(value: 'ALL', child: Text('All requests')),
                  ],
                  onChanged: _loading
                      ? null
                      : (value) {
                          if (value == null) return;
                          setState(() => _filter = value);
                          _load();
                        },
                ),
              ],
            ),
          ),
          if (_loading) const LinearProgressIndicator(minHeight: 2),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.all(16),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('ADMIN ACCESS UNAVAILABLE', style: TextStyle(fontWeight: FontWeight.w900)),
                      const SizedBox(height: 6),
                      Text(_error!, style: TextStyle(fontSize: 11, color: cs.error)),
                      const SizedBox(height: 8),
                      const Text(
                        'This screen requires an approved AIR operator mobile identity. Ordinary customers cannot view or review other customers.',
                        style: TextStyle(fontSize: 10),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          Expanded(
            child: RefreshIndicator(
              onRefresh: _load,
              child: _requests.isEmpty
                  ? ListView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      children: [
                        const SizedBox(height: 80),
                        Icon(Icons.inbox_outlined, size: 42, color: cs.onSurfaceVariant),
                        const SizedBox(height: 12),
                        Center(child: Text(_error == null ? 'No access requests in this view.' : 'Unable to load requests.', style: TextStyle(color: cs.onSurfaceVariant))),
                      ],
                    )
                  : ListView.separated(
                      padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
                      itemCount: _requests.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 8),
                      itemBuilder: (context, index) {
                        final request = _requests[index];
                        final status = request['status']?.toString() ?? 'UNKNOWN';
                        final mobile = request['mobile_e164']?.toString() ?? 'Unknown number';
                        final device = request['device_id']?.toString() ?? 'Unknown device';
                        final createdAt = request['created_at']?.toString() ?? '—';
                        final reviewerNote = request['reviewer_note']?.toString() ?? '';
                        return Card(
                          child: Padding(
                            padding: const EdgeInsets.all(13),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  children: [
                                    Expanded(child: Text(mobile, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w900))),
                                    Container(
                                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                                      decoration: BoxDecoration(
                                        color: _statusColor(context, status).withValues(alpha: .12),
                                        borderRadius: BorderRadius.circular(20),
                                      ),
                                      child: Text(status, style: TextStyle(fontSize: 9, fontWeight: FontWeight.w900, color: _statusColor(context, status))),
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 7),
                                Text('Device: $device', style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
                                Text('Submitted: $createdAt', style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
                                if (reviewerNote.isNotEmpty)
                                  Padding(
                                    padding: const EdgeInsets.only(top: 5),
                                    child: Text('Note: $reviewerNote', style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
                                  ),
                                if (status == 'PENDING' || status == 'APPROVED') ...[
                                  const SizedBox(height: 12),
                                  Wrap(
                                    spacing: 8,
                                    runSpacing: 6,
                                    children: [
                                      if (status == 'PENDING')
                                        FilledButton.tonal(
                                          onPressed: _loading ? null : () => _review(request, 'APPROVED'),
                                          child: const Text('APPROVE'),
                                        ),
                                      OutlinedButton(
                                        onPressed: _loading ? null : () => _review(request, 'REJECTED'),
                                        child: const Text('REJECT'),
                                      ),
                                      OutlinedButton(
                                        onPressed: _loading ? null : () => _review(request, 'BLOCKED'),
                                        child: const Text('BLOCK'),
                                      ),
                                    ],
                                  ),
                                ],
                              ],
                            ),
                          ),
                        );
                      },
                    ),
            ),
          ),
        ],
      ),
    );
  }
}


class AirAdminBrokerAccountsScreen extends StatefulWidget {
  const AirAdminBrokerAccountsScreen({super.key});

  @override
  State<AirAdminBrokerAccountsScreen> createState() =>
      _AirAdminBrokerAccountsScreenState();
}

class _AirAdminBrokerAccountsScreenState
    extends State<AirAdminBrokerAccountsScreen> {
  final AirApiClient _api = AirApiClient();
  final _customer = TextEditingController();
  final _account = TextEditingController();
  final _broker = TextEditingController(text: 'dhan');
  List<Map<String, dynamic>> _accounts = [];
  String? _error;
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _api.dispose();
    _customer.dispose();
    _account.dispose();
    _broker.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      final rows = await _api.operatorBrokerAccounts();
      if (mounted) setState(() => _accounts = rows);
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _assign() async {
    if (_customer.text.trim().isEmpty || _account.text.trim().isEmpty ||
        _broker.text.trim().isEmpty) {
      return;
    }
    setState(() { _loading = true; _error = null; });
    try {
      await _api.operatorAssignBrokerAccount(
        _customer.text, _broker.text, _account.text,
      );
      _account.clear();
      await _load();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<String?> _promptValue(String title, String label, {bool secret = false}) async {
    final controller = TextEditingController();
    final value = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(title),
        content: TextField(
          controller: controller,
          obscureText: secret,
          decoration: InputDecoration(labelText: label, border: const OutlineInputBorder()),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext),
              child: const Text('CANCEL')),
          FilledButton(onPressed: () => Navigator.pop(dialogContext, controller.text.trim()),
              child: const Text('CONTINUE')),
        ],
      ),
    );
    controller.dispose();
    if (value == null || value.isEmpty) return null;
    return value;
  }

  Future<void> _authorize(Map<String, dynamic> row) async {
    final broker = row['broker'].toString();
    final accountId = row['account_id'].toString();
    setState(() { _loading = true; _error = null; });
    try {
      if (broker == 'custom_vendor') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Vendor endpoints and API key are saved encrypted. Enable and verify the feed in Market Data Sources.')),
          );
        }
        return;
      } else if (broker == 'dhan') {
        final result = await _api.verifyDhan(accountId);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Dhan verified · ${result['data_validity'] ?? result['verified']}')),
          );
        }
      } else if (broker == 'angelone') {
        final totp = await _promptValue('Angel One verification', 'Current TOTP', secret: true);
        if (totp == null) return;
        final result = await _api.loginAngel(accountId, totp);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Angel One verified · ${result['verified'] == true ? 'session saved' : 'check status'}')),
          );
        }
      } else {
        final login = await _api.brokerLoginUrl(broker, accountId);
        final loginUrl = login['login_url']?.toString() ?? '';
        if (loginUrl.isEmpty) throw Exception('Broker did not return a login URL.');
        final uri = Uri.tryParse(loginUrl);
        if (uri == null || uri.scheme != 'https') {
          throw Exception('Broker returned an invalid secure login URL.');
        }
        final launched = await launchUrl(uri, mode: LaunchMode.externalApplication);
        if (!launched && mounted) {
          await showDialog<void>(
            context: context,
            builder: (dialogContext) => AlertDialog(
              title: const Text('Open broker login'),
              content: SelectableText(loginUrl),
              actions: [TextButton(onPressed: () => Navigator.pop(dialogContext),
                  child: const Text('CLOSE'))],
            ),
          );
        }
        final codeLabel = broker == 'zerodha' ? 'Request token' : 'Authorization code';
        final code = await _promptValue('$broker authorization', codeLabel);
        if (code == null) return;
        final result = await _api.brokerExchange(
          broker, accountId, code,
          state: login['state']?.toString(),
        );
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('${broker.toUpperCase()} authorization verified: ${result['verified'] == true}')),
          );
        }
      }
      await _load();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _remove(Map<String, dynamic> row) async {
    final customer = row['customer_id'].toString();
    final broker = row['broker'].toString();
    final account = row['account_id'].toString();
    final confirm = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Remove broker account?'),
        content: Text('Remove $broker · $account from $customer? '
            'Its saved encrypted credentials will also be deleted.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false),
              child: const Text('CANCEL')),
          FilledButton(onPressed: () => Navigator.pop(context, true),
              child: const Text('REMOVE')),
        ],
      ),
    );
    if (confirm != true) return;
    setState(() { _loading = true; _error = null; });
    try {
      await _api.operatorRemoveBrokerAccount(customer, broker, account);
      await _load();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _useBrokerMarketData(Map<String, dynamic> row) async {
    final customer = row['customer_id'].toString();
    final broker = row['broker'].toString();
    final account = row['account_id'].toString();
    if (row['credentials_saved'] != true) {
      setState(() => _error = 'Save broker credentials before enabling this data source.');
      return;
    }
    setState(() { _loading = true; _error = null; });
    try {
      await _api.operatorSetCustomerMarketDataSelection(customer, broker, account);
      await _load();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Broker market data enabled for $customer using $broker · $account.')),
        );
      }
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _revokeBrokerMarketData(Map<String, dynamic> row) async {
    final customer = row['customer_id'].toString();
    setState(() { _loading = true; _error = null; });
    try {
      await _api.operatorSetCustomerMarketDataAccess(
        customer, tier: 'STANDARD', brokerDataEnabled: false,
      );
      await _load();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('$customer returned to the standard NSE data path.')),
        );
      }
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _credentials(Map<String, dynamic> row) async {
    final broker = row['broker'].toString();
    final fields = <String, List<String>>{
      'dhan': ['client_id', 'access_token'],
      'zerodha': ['api_key', 'api_secret'],
      'upstox': ['client_id', 'client_secret', 'redirect_uri'],
      'fyers': ['app_id', 'app_secret', 'redirect_uri'],
      'angelone': ['api_key', 'pin'],
      'custom_vendor': ['base_url', 'websocket_url', 'api_key', 'health_path', 'instruments_path', 'historical_path'],
    }[broker] ?? const <String>[];
    if (fields.isEmpty) return;
    final controllers = {for (final field in fields) field: TextEditingController()};
    final values = await showDialog<Map<String, String>>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Save $broker credentials'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: fields.map((field) => Padding(
              padding: const EdgeInsets.only(bottom: 9),
              child: TextField(
                controller: controllers[field],
                obscureText: field.contains('secret') || field.contains('token') || field == 'pin' || field == 'api_key',
                decoration: InputDecoration(
                  labelText: field.replaceAll('_', ' ').toUpperCase(),
                  border: const OutlineInputBorder(),
                ),
              ),
            )).toList(),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context),
              child: const Text('CANCEL')),
          FilledButton(
            onPressed: () {
              final result = <String, String>{
                for (final field in fields)
                  if (controllers[field]!.text.trim().isNotEmpty)
                    field: controllers[field]!.text.trim(),
              };
              if (result.length == fields.length) Navigator.pop(context, result);
            },
            child: const Text('SAVE ENCRYPTED'),
          ),
        ],
      ),
    );
    for (final controller in controllers.values) { controller.dispose(); }
    if (values == null) return;
    setState(() { _loading = true; _error = null; });
    try {
      await _api.operatorSaveBrokerCredentials(
        row['customer_id'].toString(), broker,
        row['account_id'].toString(), values,
      );
      await _load();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: const Text('BROKER ACCOUNT CONTROL')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text('ADMIN-ONLY ASSIGNMENT',
              style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: .8)),
          const SizedBox(height: 6),
          Text('Assign multiple accounts per broker to an approved customer. '
              'Customers can view assigned accounts but cannot add, edit or remove them.',
              style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant)),
          const SizedBox(height: 14),
          TextField(
            controller: _customer,
            decoration: const InputDecoration(
              labelText: 'Customer mobile / identity (E.164)',
              hintText: '+919XXXXXXXXX',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 9),
          DropdownButtonFormField<String>(
            initialValue: _broker.text,
            decoration: const InputDecoration(labelText: 'Broker', border: OutlineInputBorder()),
            items: const [
              DropdownMenuItem(value: 'dhan', child: Text('Dhan')),
              DropdownMenuItem(value: 'zerodha', child: Text('Zerodha')),
              DropdownMenuItem(value: 'upstox', child: Text('Upstox')),
              DropdownMenuItem(value: 'fyers', child: Text('Fyers')),
              DropdownMenuItem(value: 'angelone', child: Text('Angel One')),
              DropdownMenuItem(value: 'custom_vendor', child: Text('External Market-Data Vendor')),
            ],
            onChanged: _loading ? null : (value) {
              if (value != null) setState(() => _broker.text = value);
            },
          ),
          const SizedBox(height: 9),
          TextField(
            controller: _account,
            decoration: const InputDecoration(labelText: 'Broker account ID', border: OutlineInputBorder()),
          ),
          const SizedBox(height: 10),
          FilledButton.icon(
            onPressed: _loading ? null : _assign,
            icon: const Icon(Icons.add_link),
            label: const Text('ASSIGN ACCOUNT'),
          ),
          const SizedBox(height: 18),
          Row(children: [
            const Expanded(child: Text('ASSIGNED ACCOUNTS',
                style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: .8))),
            IconButton(onPressed: _loading ? null : _load,
                icon: const Icon(Icons.refresh_rounded)),
          ]),
          if (_loading) const LinearProgressIndicator(),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text(_error!, style: TextStyle(color: cs.error)),
            ),
          if (_accounts.isEmpty && !_loading)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 28),
              child: Center(child: Text('No broker accounts assigned.')),
            ),
          ..._accounts.map((row) => Card(
            child: ListTile(
              title: Text('${row['broker']} · ${row['account_id']}'),
              subtitle: Text('Customer: ${row['customer_id']}\n'
                  '${row['credentials_saved'] == true ? 'Encrypted credentials saved' : 'Credentials not saved'}\n'
                  'Requested: ${row['market_data_selection']?['provider'] ?? 'NSE DEFAULT'} · '
                  'Effective: ${row['market_data_runtime']?['effective_source'] ?? 'NSE'}\n'
                  'Connection: ${row['market_data_runtime']?['connection_status'] ?? 'unknown'}'
                  '${row['market_data_runtime']?['fallback_active'] == true ? ' · NSE FALLBACK ACTIVE (${row['market_data_runtime']?['fallback_reason'] ?? 'broker unavailable'})' : ''}'),
              isThreeLine: true,
              leading: const Icon(Icons.account_balance_wallet_outlined),
              trailing: Wrap(
                spacing: 0,
                children: [
                  IconButton(
                    tooltip: 'Save credentials',
                    onPressed: _loading ? null : () => _credentials(row),
                    icon: const Icon(Icons.vpn_key_outlined),
                  ),
                  IconButton(
                    tooltip: 'Authorize / verify broker connection',
                    onPressed: _loading || row['credentials_saved'] != true ||
                        row['broker'] == 'custom_vendor'
                        ? null : () => _authorize(row),
                    icon: const Icon(Icons.verified_user_outlined),
                  ),
                  IconButton(
                    tooltip: 'Use this broker for the customer strategy feed',
                    onPressed: _loading || row['credentials_saved'] != true
                        ? null : () => _useBrokerMarketData(row),
                    icon: const Icon(Icons.candlestick_chart_rounded),
                  ),
                  IconButton(
                    tooltip: 'Revert customer to standard NSE data',
                    onPressed: _loading ||
                        row['market_data_access']?['tier'] != 'PAID'
                        ? null : () => _revokeBrokerMarketData(row),
                    icon: const Icon(Icons.public_rounded),
                  ),
                  IconButton(
                    tooltip: 'Remove account',
                    onPressed: _loading ? null : () => _remove(row),
                    icon: Icon(Icons.delete_outline, color: cs.error),
                  ),
                ],
              ),
            ),
          )),
        ],
      ),
    );
  }
}


class AirAdminTelegramScreen extends StatefulWidget {
  const AirAdminTelegramScreen({super.key});

  @override
  State<AirAdminTelegramScreen> createState() => _AirAdminTelegramScreenState();
}

class _AirAdminTelegramScreenState extends State<AirAdminTelegramScreen> {
  final AirApiClient _api = AirApiClient();
  List<Map<String, dynamic>> _destinations = [];
  bool _loading = false;
  String? _error;
  bool _botConfigured = false;
  bool _legacyFallback = false;

  static const _strategies = ['RECOVERED', 'EXPIRY78', 'EXPIRYSCAN'];

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
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final data = await _api.operatorTelegramDestinations();
      if (!mounted) return;
      setState(() {
        _destinations = (data['destinations'] as List<dynamic>? ?? const [])
            .whereType<Map<String, dynamic>>().toList();
        _botConfigured = data['bot_configured'] == true;
        _legacyFallback = data['legacy_env_fallback'] == true;
      });
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _edit([Map<String, dynamic>? existing]) async {
    final name = TextEditingController(text: existing?['name']?.toString() ?? '');
    final chatId = TextEditingController(text: existing?['chat_id']?.toString() ?? '');
    var type = existing?['destination_type']?.toString() ?? 'GROUP';
    var enabled = existing?['enabled'] != false;
    final selected = <String>{
      ...((existing?['strategies'] as List<dynamic>? ?? _strategies)
          .map((value) => value.toString())),
    };
    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, refreshDialog) => AlertDialog(
          title: Text(existing == null ? 'Add Telegram destination' : 'Edit Telegram destination'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: name,
                  maxLength: 80,
                  decoration: const InputDecoration(
                    labelText: 'Destination name',
                    hintText: 'AIR QOC group',
                  ),
                ),
                const SizedBox(height: 8),
                TextField(
                  controller: chatId,
                  keyboardType: const TextInputType.numberWithOptions(signed: true),
                  decoration: const InputDecoration(
                    labelText: 'Telegram chat ID',
                    hintText: '-1001234567890',
                    helperText: 'Private chat: positive ID • Group: negative ID',
                  ),
                ),
                const SizedBox(height: 8),
                DropdownButtonFormField<String>(
                  initialValue: type,
                  decoration: const InputDecoration(labelText: 'Destination type'),
                  items: const [
                    DropdownMenuItem(value: 'PRIVATE', child: Text('Private chat')),
                    DropdownMenuItem(value: 'GROUP', child: Text('Group / supergroup')),
                  ],
                  onChanged: (value) {
                    if (value != null) refreshDialog(() => type = value);
                  },
                ),
                const SizedBox(height: 12),
                Align(
                  alignment: Alignment.centerLeft,
                  child: Text('Receive strategies', style: Theme.of(context).textTheme.titleSmall),
                ),
                ..._strategies.map((strategy) => CheckboxListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  title: Text(strategy),
                  value: selected.contains(strategy),
                  onChanged: (checked) => refreshDialog(() {
                    if (checked == true) {
                      selected.add(strategy);
                    } else {
                      selected.remove(strategy);
                    }
                  }),
                )),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Destination enabled'),
                  value: enabled,
                  onChanged: (value) => refreshDialog(() => enabled = value),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('CANCEL'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, {
                'name': name.text,
                'chat_id': chatId.text,
                'destination_type': type,
                'strategies': selected.toList(),
                'enabled': enabled,
              }),
              child: const Text('SAVE'),
            ),
          ],
        ),
      ),
    );
    name.dispose();
    chatId.dispose();
    if (result == null) return;
    try {
      await _api.operatorSaveTelegramDestination(
        id: existing?['id'] as int?,
        name: result['name'] as String,
        chatId: result['chat_id'] as String,
        destinationType: result['destination_type'] as String,
        strategies: (result['strategies'] as List<dynamic>).cast<String>(),
        enabled: result['enabled'] as bool,
      );
      await _load();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    }
  }

  Future<void> _test([int? id]) async {
    setState(() => _loading = true);
    try {
      final result = await _api.operatorTestTelegramDestination(id: id);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Telegram test delivered to ${result['sent']} destination(s).')),
      );
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) {
        setState(() => _loading = false);
        await _load();
      }
    }
  }

  Future<void> _delete(Map<String, dynamic> row) async {
    final id = row['id'] as int?;
    if (id == null) return;
    final confirm = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Remove destination?'),
        content: Text('Remove ${row['name']} (${row['chat_id']}) from Telegram routing?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('CANCEL')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('REMOVE')),
        ],
      ),
    );
    if (confirm != true) return;
    try {
      await _api.operatorDeleteTelegramDestination(id);
      await _load();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        title: const Text('TELEGRAM ROUTING'),
        actions: [
          IconButton(
            tooltip: 'Test all enabled destinations',
            onPressed: _loading ? null : () => _test(),
            icon: const Icon(Icons.send_rounded),
          ),
          IconButton(
            tooltip: 'Refresh',
            onPressed: _loading ? null : _load,
            icon: const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _loading ? null : () => _edit(),
        icon: const Icon(Icons.add),
        label: const Text('ADD DESTINATION'),
      ),
      body: Column(
        children: [
          if (_loading) const LinearProgressIndicator(minHeight: 2),
          Padding(
            padding: const EdgeInsets.all(14),
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(children: [
                      Icon(Icons.telegram_rounded, color: cs.primary),
                      const SizedBox(width: 8),
                      const Expanded(child: Text('BOT CONNECTION', style: TextStyle(fontWeight: FontWeight.w900))),
                      Text(_botConfigured ? 'TOKEN SECRET PRESENT' : 'TOKEN MISSING',
                          style: TextStyle(fontSize: 10, fontWeight: FontWeight.w900,
                              color: _botConfigured ? Colors.green : cs.error)),
                    ]),
                    const SizedBox(height: 6),
                    Text(
                      _legacyFallback
                          ? 'No managed destinations yet. Legacy environment chat IDs remain active until the first destination is saved.'
                          : 'Destinations are stored on the AIR server. Bot token remains in Docker secrets and is never shown here.',
                      style: TextStyle(fontSize: 11, color: cs.onSurfaceVariant, height: 1.4),
                    ),
                  ],
                ),
              ),
            ),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 14),
              child: Text(_error!, style: TextStyle(color: cs.error, fontSize: 11)),
            ),
          Expanded(
            child: _destinations.isEmpty
                ? Center(
                    child: Text('No managed destinations. Add a private chat or group.',
                        style: TextStyle(color: cs.onSurfaceVariant)),
                  )
                : ListView.separated(
                    padding: const EdgeInsets.fromLTRB(14, 0, 14, 90),
                    itemCount: _destinations.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 8),
                    itemBuilder: (context, index) {
                      final row = _destinations[index];
                      final strategies = (row['strategies'] as List<dynamic>? ?? const [])
                          .map((value) => value.toString()).join(' • ');
                      final enabled = row['enabled'] == true;
                      final id = row['id'] as int?;
                      return Card(
                        child: Padding(
                          padding: const EdgeInsets.all(13),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(children: [
                                Icon(row['destination_type'] == 'GROUP'
                                    ? Icons.groups_rounded : Icons.person_outline_rounded),
                                const SizedBox(width: 8),
                                Expanded(child: Text(row['name']?.toString() ?? 'Telegram destination',
                                    style: const TextStyle(fontWeight: FontWeight.w900))),
                                Text(enabled ? 'ACTIVE' : 'DISABLED',
                                    style: TextStyle(fontSize: 9, fontWeight: FontWeight.w900,
                                        color: enabled ? Colors.green : cs.onSurfaceVariant)),
                              ]),
                              const SizedBox(height: 6),
                              SelectableText(row['chat_id']?.toString() ?? '—',
                                  style: const TextStyle(fontFeatures: [])),
                              const SizedBox(height: 5),
                              Text('Routes: $strategies',
                                  style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
                              const SizedBox(height: 10),
                              Wrap(spacing: 6, children: [
                                TextButton.icon(
                                  onPressed: _loading || !enabled ? null : () => _test(id),
                                  icon: const Icon(Icons.send_outlined, size: 16),
                                  label: const Text('TEST'),
                                ),
                                TextButton.icon(
                                  onPressed: _loading ? null : () => _edit(row),
                                  icon: const Icon(Icons.edit_outlined, size: 16),
                                  label: const Text('EDIT'),
                                ),
                                TextButton.icon(
                                  onPressed: _loading ? null : () => _delete(row),
                                  icon: Icon(Icons.delete_outline, size: 16, color: cs.error),
                                  label: Text('REMOVE', style: TextStyle(color: cs.error)),
                                ),
                              ]),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}


class AirAdminMarketDataSourcesScreen extends StatefulWidget {
  const AirAdminMarketDataSourcesScreen({super.key});

  @override
  State<AirAdminMarketDataSourcesScreen> createState() =>
      _AirAdminMarketDataSourcesScreenState();
}

class _AirAdminMarketDataSourcesScreenState
    extends State<AirAdminMarketDataSourcesScreen> {
  final AirApiClient _api = AirApiClient();
  List<Map<String, dynamic>> _providers = [];
  Map<String, dynamic> _selections = {};
  Map<String, dynamic> _runtime = {};
  final _account = TextEditingController();
  final _instrumentExchange = TextEditingController(text: 'NSE');
  final _instrumentSymbol = TextEditingController();
  final _instrumentToken = TextEditingController();
  final _instrumentSegment = TextEditingController(text: 'NSE_EQ');
  final _failoverCandidates = TextEditingController();
  bool _failoverEnabled = false;
  String _channel = 'historical';
  String? _provider;
  String? _error;
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _api.dispose();
    _account.dispose();
    _instrumentExchange.dispose();
    _instrumentSymbol.dispose();
    _instrumentToken.dispose();
    _instrumentSegment.dispose();
    _failoverCandidates.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      final data = await _api.operatorMarketDataSources();
      if (!mounted) return;
      final providers = (data['providers'] as List<dynamic>? ?? const [])
          .whereType<Map<String, dynamic>>().toList();
      final selections = data['selections'] as Map<String, dynamic>? ?? {};
      setState(() {
        _providers = providers;
        _selections = selections;
        _runtime = data['runtime'] as Map<String, dynamic>? ?? {};
        final failover = (data['failover'] as Map<String, dynamic>? ?? {})[_channel]
            as Map<String, dynamic>? ?? {};
        _failoverEnabled = failover['enabled'] == true;
        final candidates = (failover['candidates'] as List<dynamic>? ?? const [])
            .whereType<Map<String, dynamic>>()
            .map((item) => '${item['provider']}|${item['account_id']}')
            .join(', ');
        _failoverCandidates.text = candidates;
        final current = selections[_channel] as Map<String, dynamic>?;
        _provider = current?['provider']?.toString() ??
            (_providers.isNotEmpty ? _providers.first['code']?.toString() : null);
        _account.text = current?['account_id']?.toString() ?? '';
      });
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  bool _ready(Map<String, dynamic> provider, String channel) {
    final channels = (provider['adapter_ready'] as Map?) ?? const {};
    return channels[channel] == true;
  }

  List<Map<String, dynamic>> get _channelProviders => _providers
      .where((provider) =>
          (provider['channels'] as List<dynamic>? ?? const []).contains(_channel))
      .toList();

  Map<String, dynamic>? _providerByCode(List<Map<String, dynamic>> rows, Object? code) {
    for (final row in rows) {
      if (row['code'] == code) return row;
    }
    return null;
  }

  Future<void> _save(bool enabled) async {
    if (_provider == null) return;
    final selected = _providerByCode(_providers, _provider);
    if (selected == null) return;
    if (enabled && !_ready(selected, _channel)) {
      setState(() => _error = 'This provider adapter is not ready for $_channel data yet.');
      return;
    }
    setState(() { _loading = true; _error = null; });
    try {
      await _api.operatorSelectMarketDataSource(
        _channel, _provider!,
        accountId: selected['requires_account'] == true ? _account.text.trim() : null,
        enabled: enabled,
      );
      await _load();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _verifySource() async {
    setState(() { _loading = true; _error = null; });
    try {
      final result = await _api.operatorVerifyMarketDataSource(_channel);
      if (!mounted) return;
      final verified = result['verified'] == true;
      final status = result['status']?.toString() ?? 'UNKNOWN';
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${_channel.toUpperCase()} verification: $status')),
      );
      if (!verified) setState(() => _error = result['note']?.toString() ?? status);
      await _load();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _saveFailover() async {
    final candidates = <Map<String, String>>[];
    for (final raw in _failoverCandidates.text.split(',')) {
      final parts = raw.trim().split('|');
      if (raw.trim().isEmpty) continue;
      if (parts.length != 2 || parts.any((part) => part.trim().isEmpty)) {
        setState(() => _error = 'Use provider|account_id entries separated by commas.');
        return;
      }
      candidates.add({'provider': parts[0].trim(), 'account_id': parts[1].trim()});
    }
    setState(() { _loading = true; _error = null; });
    try {
      await _api.operatorConfigureMarketDataFailover(
          _channel, _failoverEnabled, candidates);
      await _load();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _saveInstrumentMapping() async {
    if (_provider == null || _account.text.trim().isEmpty ||
        _instrumentExchange.text.trim().isEmpty ||
        _instrumentSymbol.text.trim().isEmpty ||
        _instrumentToken.text.trim().isEmpty ||
        _instrumentSegment.text.trim().isEmpty) {
      setState(() => _error = 'Complete provider, account and all instrument mapping fields.');
      return;
    }
    setState(() { _loading = true; _error = null; });
    try {
      await _api.operatorSaveMarketInstrument(
        provider: _provider!,
        accountId: _account.text.trim(),
        exchange: _instrumentExchange.text.trim(),
        symbol: _instrumentSymbol.text.trim(),
        token: _instrumentToken.text.trim(),
        segment: _instrumentSegment.text.trim(),
      );
      _instrumentSymbol.clear();
      _instrumentToken.clear();
      await _load();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  String _channelState(String channel) {
    final states = (_runtime['connection_state'] as Map?) ?? const {};
    return states[channel]?.toString() ?? 'not_configured';
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final providers = _channelProviders;
    final current = _selections[_channel] as Map<String, dynamic>?;
    final selectedProvider = _providerByCode(providers, _provider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('MARKET DATA SOURCES'),
        actions: [
          IconButton(onPressed: _loading ? null : _load,
              icon: const Icon(Icons.refresh_rounded)),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text('Choose historical and live feeds independently. Credentials are stored in the encrypted AIR vault; provider availability depends on the adapter and your vendor subscription.',
              style: TextStyle(fontSize: 11, height: 1.45, color: cs.onSurfaceVariant)),
          const SizedBox(height: 14),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'historical', label: Text('HISTORICAL')),
              ButtonSegment(value: 'live', label: Text('LIVE')),
            ],
            selected: {_channel},
            onSelectionChanged: _loading ? null : (values) {
              final channel = values.first;
              final choice = _selections[channel] as Map<String, dynamic>?;
              setState(() {
                _channel = channel;
                _provider = choice?['provider']?.toString() ??
                    (_channelProviders.isNotEmpty ? _channelProviders.first['code']?.toString() : null);
                _account.text = choice?['account_id']?.toString() ?? '';
                _error = null;
              });
            },
          ),
          const SizedBox(height: 12),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${_channel.toUpperCase()} SOURCE',
                    style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w900)),
                const SizedBox(height: 8),
                DropdownButtonFormField<String>(
                  initialValue: providers.any((provider) => provider['code'] == _provider) ? _provider : null,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Provider', border: OutlineInputBorder()),
                  items: providers.map((p) => DropdownMenuItem<String>(
                    value: p['code']?.toString(),
                    child: Text(p['name']?.toString() ?? p['code'].toString(),
                        overflow: TextOverflow.ellipsis),
                  )).toList(),
                  onChanged: _loading ? null : (value) {
                    setState(() {
                      _provider = value;
                      _account.text = '';
                      _error = null;
                    });
                  },
                ),
                if (selectedProvider?['requires_account'] == true) ...[
                  const SizedBox(height: 10),
                  TextField(
                    controller: _account,
                    decoration: const InputDecoration(
                      labelText: 'Broker / vendor account ID',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ],
                if (selectedProvider != null) ...[
                  const SizedBox(height: 10),
                  Text(selectedProvider['data_scope']?.toString() ?? '',
                      style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
                  const SizedBox(height: 8),
                  Row(children: [
                    Icon(_ready(selectedProvider, _channel) ? Icons.check_circle : Icons.pending_outlined,
                        size: 15, color: _ready(selectedProvider, _channel) ? Colors.green : Colors.orange),
                    const SizedBox(width: 6),
                    Expanded(child: Text(
                      _ready(selectedProvider, _channel)
                          ? 'Adapter implemented — connection can be enabled'
                          : 'Catalog only — adapter implementation / verification pending',
                      style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700),
                    )),
                  ]),
                ],
                const SizedBox(height: 12),
                Wrap(spacing: 8, runSpacing: 8, children: [
                  FilledButton.icon(
                    onPressed: _loading || selectedProvider == null ||
                        !_ready(selectedProvider, _channel) ? null : () => _save(true),
                    icon: const Icon(Icons.link_rounded),
                    label: const Text('ENABLE & CONNECT'),
                  ),
                  OutlinedButton(
                    onPressed: _loading || current == null ? null : () => _save(false),
                    child: const Text('DISABLE SOURCE'),
                  ),
                  OutlinedButton.icon(
                    onPressed: _loading || current == null ? null : _verifySource,
                    icon: const Icon(Icons.fact_check_outlined),
                    label: const Text('VERIFY DATA'),
                  ),
                ]),
                if (current != null) ...[
                  const Divider(height: 22),
                  Text('Saved: ${current['provider']} · ${current['enabled'] == true ? 'ENABLED' : 'DISABLED'}',
                      style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w800)),
                  Text('Runtime: ${_channelState(_channel)}',
                      style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
                ],
              ]),
            ),
          ),
          const SizedBox(height: 12),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('OPTIONAL AUTOMATIC FAILOVER',
                    style: TextStyle(fontSize: 11, fontWeight: FontWeight.w900)),
                const SizedBox(height: 5),
                Text('When the primary feed is degraded or stale, AIR can switch to the first authenticated candidate. Use a secondary account on the same broker only; cross-broker token remapping is not enabled yet.',
                    style: TextStyle(fontSize: 10, height: 1.4, color: cs.onSurfaceVariant)),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Enable failover', style: TextStyle(fontSize: 12)),
                  value: _failoverEnabled,
                  onChanged: _loading ? null : (value) => setState(() => _failoverEnabled = value),
                ),
                TextField(
                  controller: _failoverCandidates,
                  minLines: 1,
                  maxLines: 3,
                  decoration: const InputDecoration(
                    labelText: 'Candidates: provider|account_id, ...',
                    hintText: 'zerodha|AB1234, upstox|123456',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  onPressed: _loading ? null : _saveFailover,
                  icon: const Icon(Icons.alt_route_rounded),
                  label: const Text('SAVE FAILOVER POLICY'),
                ),
              ]),
            ),
          ),

          if (selectedProvider != null && selectedProvider['requires_account'] == true) ...[
            const SizedBox(height: 12),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Text('BROKER INSTRUMENT TOKEN MAPPING',
                      style: TextStyle(fontSize: 11, fontWeight: FontWeight.w900)),
                  const SizedBox(height: 5),
                  Text('Broker instrument tokens are provider-specific. Add the symbol and token from the selected broker instrument master before requesting history or subscribing to live quotes.',
                      style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant, height: 1.4)),
                  const SizedBox(height: 10),
                  TextField(controller: _instrumentExchange,
                      decoration: const InputDecoration(labelText: 'Exchange', border: OutlineInputBorder())),
                  const SizedBox(height: 8),
                  TextField(controller: _instrumentSymbol,
                      decoration: const InputDecoration(labelText: 'Trading symbol', border: OutlineInputBorder())),
                  const SizedBox(height: 8),
                  TextField(controller: _instrumentToken,
                      decoration: const InputDecoration(labelText: 'Broker instrument token / key', border: OutlineInputBorder())),
                  const SizedBox(height: 8),
                  TextField(controller: _instrumentSegment,
                      decoration: const InputDecoration(labelText: 'Broker exchange segment', border: OutlineInputBorder())),
                  const SizedBox(height: 10),
                  FilledButton.icon(
                    onPressed: _loading ? null : _saveInstrumentMapping,
                    icon: const Icon(Icons.save_outlined),
                    label: const Text('SAVE INSTRUMENT MAPPING'),
                  ),
                ]),
              ),
            ),
          ],
          const SizedBox(height: 12),
          const Text('PROVIDER READINESS', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w900)),
          const SizedBox(height: 7),
          ...providers.map((provider) {
            final ready = _ready(provider, _channel);
            return Card(
              child: ListTile(
                dense: true,
                title: Text(provider['name']?.toString() ?? ''),
                subtitle: Text(provider['data_scope']?.toString() ?? '',
                    maxLines: 2, overflow: TextOverflow.ellipsis),
                trailing: Icon(ready ? Icons.check_circle : Icons.hourglass_empty,
                    color: ready ? Colors.green : Colors.orange),
              ),
            );
          }),
          if (_error != null) ...[
            const SizedBox(height: 8),
            Text(_error!, style: TextStyle(color: cs.error, fontSize: 11)),
          ],
          if (_loading) const LinearProgressIndicator(),
        ],
      ),
    );
  }
}


class AirAdminExecutionScreen extends StatefulWidget {
  const AirAdminExecutionScreen({super.key});

  @override
  State<AirAdminExecutionScreen> createState() => _AirAdminExecutionScreenState();
}

class _AirAdminExecutionScreenState extends State<AirAdminExecutionScreen> {
  final AirApiClient _api = AirApiClient();
  bool _loading = false;
  bool _masterAuto = false;
  bool _expiry78 = false;
  bool _expiryScan = false;
  bool _recovered = false;
  String? _error;
  Map<String, dynamic> _masterStatus = const {};

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
    setState(() { _loading = true; _error = null; });
    try {
      final policy = await _api.operatorExecutionPolicy();
      final strategies = policy['strategies'] as Map<String, dynamic>? ?? {};
      final masters = await _api.brokerMasterStatus();
      if (!mounted) return;
      setState(() {
        _masterAuto = policy['master_auto_enabled'] == true;
        _expiry78 = strategies['EXPIRY78'] == true;
        _expiryScan = strategies['EXPIRYSCAN'] == true;
        _recovered = strategies['RECOVERED'] == true;
        _masterStatus = masters;
      });
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _save() async {
    setState(() { _loading = true; _error = null; });
    try {
      await _api.updateOperatorExecutionPolicy(
        masterAutoEnabled: _masterAuto,
        strategies: {
          'EXPIRY78': _expiry78,
          'EXPIRYSCAN': _expiryScan,
          'RECOVERED': _recovered,
        },
      );
      await _load();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _refreshMasters() async {
    setState(() { _loading = true; _error = null; });
    try {
      await _api.refreshBrokerMasters();
      final masters = await _api.brokerMasterStatus();
      if (mounted) setState(() => _masterStatus = masters);
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final masters = (_masterStatus['masters'] as List<dynamic>? ?? const []);
    return Scaffold(
      appBar: AppBar(
        title: const Text('EXECUTION & BROKER MASTERS'),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            onPressed: _loading ? null : _load,
            icon: const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('AUTOMATIC ORDER CONTROL',
                    style: TextStyle(fontWeight: FontWeight.w900, fontSize: 12)),
                const SizedBox(height: 6),
                Text(
                  'OFF = manual review only; no automatic orders. ON = automatic execution becomes eligible only for strategies enabled below and broker accounts separately approved. Live order submission is still locked pending broker execution verification.',
                  style: TextStyle(color: cs.onSurfaceVariant, fontSize: 11, height: 1.4),
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('MASTER AUTO EXECUTION'),
                  subtitle: Text(_masterAuto ? 'Automatic mode eligible' : 'Manual-only mode'),
                  value: _masterAuto,
                  onChanged: _loading ? null : (value) => setState(() => _masterAuto = value),
                ),
                const Divider(),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('EXPIRY78'),
                  value: _expiry78,
                  onChanged: _loading ? null : (value) => setState(() => _expiry78 = value),
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('EXPIRYSCAN'),
                  value: _expiryScan,
                  onChanged: _loading ? null : (value) => setState(() => _expiryScan = value),
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('RECOVERED'),
                  value: _recovered,
                  onChanged: _loading ? null : (value) => setState(() => _recovered = value),
                ),
                const SizedBox(height: 8),
                FilledButton.icon(
                  onPressed: _loading ? null : _save,
                  icon: const Icon(Icons.save_rounded),
                  label: const Text('SAVE EXECUTION POLICY'),
                ),
                const SizedBox(height: 8),
                Text('Manual and automatic broker submission are not yet enabled. This screen controls eligibility only; broker-specific order adapters, risk checks and account verification must pass first.',
                    style: TextStyle(color: cs.error, fontSize: 10, height: 1.4)),
              ]),
            ),
          ),
          const SizedBox(height: 12),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('BROKER INSTRUMENT MASTERS',
                    style: TextStyle(fontWeight: FontWeight.w900, fontSize: 12)),
                const SizedBox(height: 5),
                Text('Daily refresh is scheduled for 07:00 IST on weekdays. Refresh validates the downloaded master before replacing the last good snapshot.',
                    style: TextStyle(color: cs.onSurfaceVariant, fontSize: 11, height: 1.4)),
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  onPressed: _loading ? null : _refreshMasters,
                  icon: const Icon(Icons.sync_rounded),
                  label: const Text('REFRESH BROKER MASTERS NOW'),
                ),
                const SizedBox(height: 8),
                for (final item in masters.whereType<Map<String, dynamic>>())
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text('${item['provider']} · ${item['account_id']}',
                        style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700)),
                    subtitle: Text('${item['row_count']} instruments · ${item['refreshed_at']}',
                        style: const TextStyle(fontSize: 10)),
                    trailing: const Icon(Icons.verified_outlined, size: 17),
                  ),
                if (masters.isEmpty)
                  const Text('No successful broker master refresh recorded yet.',
                      style: TextStyle(fontSize: 11)),
                const SizedBox(height: 6),
                const Text('FYERS and custom broker deployments may require an official master URL configured by the operator. Failed imports keep the previous master.',
                    style: TextStyle(fontSize: 10)),
              ]),
            ),
          ),
          if (_error != null) ...[
            const SizedBox(height: 10),
            Text(_error!, style: TextStyle(color: cs.error, fontSize: 11)),
          ],
        ],
      ),
    );
  }
}
