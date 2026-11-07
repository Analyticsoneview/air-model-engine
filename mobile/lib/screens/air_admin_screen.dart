import 'package:flutter/material.dart';

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
        _broker.text.trim().isEmpty) return;
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

  Future<void> _credentials(Map<String, dynamic> row) async {
    final broker = row['broker'].toString();
    final fields = <String>{
      'dhan': ['client_id', 'access_token'],
      'zerodha': ['api_key', 'api_secret'],
      'upstox': ['client_id', 'client_secret', 'redirect_uri'],
      'fyers': ['app_id', 'app_secret', 'redirect_uri'],
      'angelone': ['api_key', 'pin'],
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
                obscureText: field.contains('secret') || field.contains('token') || field == 'pin',
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
            value: _broker.text,
            decoration: const InputDecoration(labelText: 'Broker', border: OutlineInputBorder()),
            items: const [
              DropdownMenuItem(value: 'dhan', child: Text('Dhan')),
              DropdownMenuItem(value: 'zerodha', child: Text('Zerodha')),
              DropdownMenuItem(value: 'upstox', child: Text('Upstox')),
              DropdownMenuItem(value: 'fyers', child: Text('Fyers')),
              DropdownMenuItem(value: 'angelone', child: Text('Angel One')),
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
                  '${row['credentials_saved'] == true ? 'Encrypted credentials saved' : 'Credentials not saved'}'),
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
