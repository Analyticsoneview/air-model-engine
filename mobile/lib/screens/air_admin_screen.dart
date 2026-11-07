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
                                Text('Submitted: \${request['created_at'] ?? '—'}', style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
                                if ((request['reviewer_note'] ?? '').toString().isNotEmpty)
                                  Padding(
                                    padding: const EdgeInsets.only(top: 5),
                                    child: Text('Note: \${request['reviewer_note']}', style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant)),
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
