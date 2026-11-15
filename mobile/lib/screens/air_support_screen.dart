import 'package:flutter/material.dart';
import '../services/air_api_client.dart';

class AirSupportScreen extends StatefulWidget {
  const AirSupportScreen({super.key, this.apiClient});
  final AirApiClient? apiClient;

  @override
  State<AirSupportScreen> createState() => _AirSupportScreenState();
}

class _AirSupportScreenState extends State<AirSupportScreen> {
  late final AirApiClient _api = widget.apiClient ?? AirApiClient();
  final _subject = TextEditingController();
  final _message = TextEditingController();
  String _category = 'GENERAL';
  List<Map<String, dynamic>> _tickets = [];
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() { _busy = true; _error = null; });
    try {
      _tickets = await _api.supportTickets();
    } catch (e) {
      _error = e.toString();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _createTicket() async {
    if (_subject.text.trim().length < 5 || _message.text.trim().length < 10) {
      setState(() => _error = 'Enter a subject and a message with at least 10 characters.');
      return;
    }
    setState(() { _busy = true; _error = null; });
    try {
      await _api.createSupportTicket(
        subject: _subject.text.trim(), category: _category, message: _message.text.trim(),
      );
      _subject.clear();
      _message.clear();
      await _load();
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Support ticket created.')),
      );
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted && _busy) setState(() => _busy = false);
    }
  }

  Future<void> _reply(Map<String, dynamic> ticket) async {
    final controller = TextEditingController();
    final send = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Reply to AIR Support'),
        content: TextField(controller: controller, minLines: 3, maxLines: 6,
          decoration: const InputDecoration(labelText: 'Message', border: OutlineInputBorder())),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext, false), child: const Text('CANCEL')),
          FilledButton(onPressed: () => Navigator.pop(dialogContext, true), child: const Text('SEND REPLY')),
        ],
      ),
    );
    final message = controller.text.trim();
    controller.dispose();
    if (send != true || message.length < 10 || !mounted) return;
    setState(() { _busy = true; _error = null; });
    try {
      await _api.replySupportTicket(ticket['ticket_id'].toString(), message);
      await _load();
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted && _busy) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _subject.dispose();
    _message.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('AIR CUSTOMER SUPPORT'), actions: [
      IconButton(onPressed: _busy ? null : _load, icon: const Icon(Icons.refresh), tooltip: 'Refresh tickets'),
    ]),
    body: ListView(padding: const EdgeInsets.all(16), children: [
      const Text('HOW CAN WE HELP?', style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: 1)),
      const SizedBox(height: 6),
      const Text('Create a support request. Replies and status changes remain attached to your ticket.'),
      const SizedBox(height: 12),
      TextField(controller: _subject, maxLength: 120,
        decoration: const InputDecoration(labelText: 'Subject', border: OutlineInputBorder())),
      const SizedBox(height: 8),
      DropdownButtonFormField<String>(
        value: _category,
        decoration: const InputDecoration(labelText: 'Category', border: OutlineInputBorder()),
        items: const [
          DropdownMenuItem(value: 'ACCOUNT', child: Text('Account')),
          DropdownMenuItem(value: 'BILLING', child: Text('Billing')),
          DropdownMenuItem(value: 'BROKER', child: Text('Broker connection')),
          DropdownMenuItem(value: 'TECHNICAL', child: Text('Technical')),
          DropdownMenuItem(value: 'GENERAL', child: Text('General')),
        ],
        onChanged: _busy ? null : (value) { if (value != null) setState(() => _category = value); },
      ),
      const SizedBox(height: 8),
      TextField(controller: _message, minLines: 3, maxLines: 6, maxLength: 5000,
        decoration: const InputDecoration(labelText: 'Describe the issue', border: OutlineInputBorder())),
      Align(alignment: Alignment.centerRight, child: FilledButton.icon(
        onPressed: _busy ? null : _createTicket,
        icon: const Icon(Icons.send), label: const Text('SUBMIT TICKET'),
      )),
      if (_error != null) Padding(padding: const EdgeInsets.symmetric(vertical: 8),
        child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
      const Divider(height: 28),
      Row(children: [
        const Expanded(child: Text('YOUR SUPPORT TICKETS', style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: 1))),
        Text('${_tickets.length}', style: Theme.of(context).textTheme.labelLarge),
      ]),
      if (_busy && _tickets.isEmpty) const Padding(padding: EdgeInsets.all(24),
        child: Center(child: CircularProgressIndicator())),
      if (!_busy && _tickets.isEmpty) const Padding(padding: EdgeInsets.all(20),
        child: Center(child: Text('No support tickets yet.'))),
      for (final ticket in _tickets)
        Card(child: Padding(padding: const EdgeInsets.all(14), child: Column(
          crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Expanded(child: Text(ticket['subject']?.toString() ?? 'Support request',
                style: const TextStyle(fontWeight: FontWeight.w800))),
              Chip(label: Text(ticket['status']?.toString() ?? 'OPEN')),
            ]),
            Text('Ticket ${ticket['ticket_id']} · ${ticket['category']}'),
            for (final event in (ticket['events'] as List? ?? []).whereType<Map>())
              Padding(padding: const EdgeInsets.only(top: 8), child: Text(
                '${event['actor_type']}: ${event['message']}',
                style: Theme.of(context).textTheme.bodySmall,
              )),
            if (ticket['status'] != 'CLOSED')
              Align(alignment: Alignment.centerRight, child: TextButton.icon(
                onPressed: _busy ? null : () => _reply(ticket),
                icon: const Icon(Icons.reply), label: const Text('REPLY'),
              )),
          ],
        ))),
    ]),
  );
}
