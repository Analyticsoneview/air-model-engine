import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

class AirInternalWorkspaceScreen extends StatefulWidget {
  const AirInternalWorkspaceScreen({
    super.key,
    required this.apiBase,
    required this.accessToken,
    required this.httpClient,
  });

  final String apiBase;
  final String accessToken;
  final http.Client httpClient;

  @override
  State<AirInternalWorkspaceScreen> createState() => _AirInternalWorkspaceScreenState();
}

class _AirInternalWorkspaceScreenState extends State<AirInternalWorkspaceScreen> {
  bool _busy = false;
  String? _error;
  String _section = 'watchlists';
  Map<String, dynamic>? _policy;
  List<Map<String, dynamic>> _watchlists = [];
  List<Map<String, dynamic>> _notes = [];

  Uri _uri(String path) => Uri.parse('${widget.apiBase}$path');

  Future<Map<String, dynamic>> _request(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final headers = {
      'Accept': 'application/json',
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ${widget.accessToken}',
    };
    late http.Response response;
    switch (method) {
      case 'POST':
        response = await widget.httpClient.post(_uri(path), headers: headers, body: jsonEncode(body));
        break;
      case 'PUT':
        response = await widget.httpClient.put(_uri(path), headers: headers, body: jsonEncode(body));
        break;
      case 'DELETE':
        response = await widget.httpClient.delete(_uri(path), headers: headers);
        break;
      default:
        response = await widget.httpClient.get(_uri(path), headers: headers);
    }
    final decoded = response.body.isEmpty ? <String, dynamic>{} : jsonDecode(response.body);
    final data = decoded is Map<String, dynamic> ? decoded : <String, dynamic>{};
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(data['detail']?.toString() ?? 'AIR API returned HTTP ${response.statusCode}');
    }
    return data;
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() { _busy = true; _error = null; });
    try {
      final results = await Future.wait([
        _request('GET', '/api/v1/internal-workspace/policy'),
        _request('GET', '/api/v1/internal-workspace/watchlists'),
        _request('GET', '/api/v1/internal-workspace/notes'),
      ]);
      if (!mounted) return;
      setState(() {
        _policy = results[0];
        _watchlists = (results[1]['items'] as List? ?? const [])
            .whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
        _notes = (results[2]['items'] as List? ?? const [])
            .whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
      });
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _editWatchlist([Map<String, dynamic>? existing]) async {
    final payload = Map<String, dynamic>.from(existing?['payload'] as Map? ?? {});
    final name = TextEditingController(text: existing?['title']?.toString() ?? '');
    final symbols = TextEditingController(text: (payload['symbols'] as List? ?? const []).join(', '));
    final accepted = await showDialog<bool>(context: context, builder: (ctx) => AlertDialog(
      title: Text(existing == null ? 'New private watchlist' : 'Edit private watchlist'),
      content: Column(mainAxisSize: MainAxisSize.min, children: [
        TextField(controller: name, maxLength: 120, decoration: const InputDecoration(labelText: 'Watchlist name')),
        TextField(controller: symbols, maxLines: 3, decoration: const InputDecoration(
          labelText: 'Symbols (comma separated)', hintText: 'NIFTY, BANKNIFTY, RELIANCE')),
      ]),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('CANCEL')),
        FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('SAVE')),
      ],
    ));
    final title = name.text.trim();
    final values = symbols.text.split(',').map((e) => e.trim().toUpperCase()).where((e) => e.isNotEmpty).toSet().toList();
    name.dispose(); symbols.dispose();
    if (accepted != true || !mounted) return;
    if (title.isEmpty || values.isEmpty) {
      setState(() => _error = 'Enter a watchlist name and at least one symbol.');
      return;
    }
    await _mutate(() async {
      final id = existing?['item_id']?.toString();
      await _request(id == null ? 'POST' : 'PUT',
          id == null ? '/api/v1/internal-workspace/watchlists' : '/api/v1/internal-workspace/watchlists/$id',
          body: {'name': title, 'symbols': values});
      await _load();
    });
  }

  Future<void> _editNote([Map<String, dynamic>? existing]) async {
    final payload = Map<String, dynamic>.from(existing?['payload'] as Map? ?? {});
    final title = TextEditingController(text: existing?['title']?.toString() ?? '');
    final content = TextEditingController(text: payload['content']?.toString() ?? '');
    final tags = TextEditingController(text: (payload['tags'] as List? ?? const []).join(', '));
    final symbols = TextEditingController(text: (payload['related_symbols'] as List? ?? const []).join(', '));
    final accepted = await showDialog<bool>(context: context, builder: (ctx) => AlertDialog(
      title: Text(existing == null ? 'New private research note' : 'Edit private research note'),
      content: SingleChildScrollView(child: Column(mainAxisSize: MainAxisSize.min, children: [
        TextField(controller: title, maxLength: 160, decoration: const InputDecoration(labelText: 'Title')),
        TextField(controller: content, minLines: 4, maxLines: 8, maxLength: 20000,
          decoration: const InputDecoration(labelText: 'Research notes')),
        TextField(controller: tags, decoration: const InputDecoration(labelText: 'Tags (comma separated)')),
        TextField(controller: symbols, decoration: const InputDecoration(labelText: 'Related symbols (comma separated)')),
      ])),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('CANCEL')),
        FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('SAVE')),
      ],
    ));
    final noteTitle = title.text.trim();
    final noteContent = content.text.trim();
    final tagValues = tags.text.split(',').map((e) => e.trim()).where((e) => e.isNotEmpty).toSet().toList();
    final symbolValues = symbols.text.split(',').map((e) => e.trim().toUpperCase()).where((e) => e.isNotEmpty).toSet().toList();
    title.dispose(); content.dispose(); tags.dispose(); symbols.dispose();
    if (accepted != true || !mounted) return;
    if (noteTitle.isEmpty || noteContent.isEmpty) {
      setState(() => _error = 'Enter a note title and note content.');
      return;
    }
    await _mutate(() async {
      final id = existing?['item_id']?.toString();
      await _request(id == null ? 'POST' : 'PUT',
          id == null ? '/api/v1/internal-workspace/notes' : '/api/v1/internal-workspace/notes/$id',
          body: {'title': noteTitle, 'content': noteContent, 'tags': tagValues, 'related_symbols': symbolValues});
      await _load();
    });
  }

  Future<void> _deleteItem(Map<String, dynamic> item, String kind) async {
    final accepted = await showDialog<bool>(context: context, builder: (ctx) => AlertDialog(
      title: const Text('Delete private item?'),
      content: Text('Delete "${item['title']}" from this internal workspace?'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('CANCEL')),
        FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('DELETE')),
      ],
    ));
    if (accepted != true || !mounted) return;
    await _mutate(() async {
      await _request('DELETE', '/api/v1/internal-workspace/$kind/${item['item_id']}');
      await _load();
    });
  }

  Future<void> _mutate(Future<void> Function() action) async {
    setState(() { _busy = true; _error = null; });
    try {
      await action();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final items = _section == 'watchlists' ? _watchlists : _notes;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Card(
        color: Theme.of(context).colorScheme.errorContainer,
        child: const ListTile(
          leading: Icon(Icons.lock),
          title: Text('INTERNAL — NOT FOR DISTRIBUTION'),
          subtitle: Text('Owner-only personal analysis. Do not share or publish these research records.'),
        ),
      ),
      if (_policy != null)
        Padding(padding: const EdgeInsets.symmetric(horizontal: 12), child: Text(
          'Access: ${_policy!['access']} • External distribution: disabled',
          style: Theme.of(context).textTheme.bodySmall,
        )),
      if (_error != null)
        Padding(padding: const EdgeInsets.all(12), child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
      Padding(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8), child: Row(children: [
        SegmentedButton<String>(
          segments: const [
            ButtonSegment(value: 'watchlists', label: Text('Watchlists'), icon: Icon(Icons.visibility)),
            ButtonSegment(value: 'notes', label: Text('Research notes'), icon: Icon(Icons.notes)),
          ],
          selected: {_section},
          onSelectionChanged: (value) => setState(() => _section = value.first),
        ),
        const Spacer(),
        IconButton(onPressed: _busy ? null : _load, tooltip: 'Refresh', icon: const Icon(Icons.refresh)),
        FilledButton.icon(
          onPressed: _busy ? null : () => _section == 'watchlists' ? _editWatchlist() : _editNote(),
          icon: const Icon(Icons.add),
          label: Text(_section == 'watchlists' ? 'NEW WATCHLIST' : 'NEW NOTE'),
        ),
      ])),
      if (_busy) const LinearProgressIndicator(),
      Expanded(child: items.isEmpty
          ? const Center(child: Text('No private records yet. Add a watchlist or research note.'))
          : ListView.builder(
              padding: const EdgeInsets.all(12),
              itemCount: items.length,
              itemBuilder: (context, index) {
                final item = items[index];
                final payload = Map<String, dynamic>.from(item['payload'] as Map? ?? {});
                final subtitle = _section == 'watchlists'
                    ? (payload['symbols'] as List? ?? const []).join(', ')
                    : payload['content']?.toString() ?? '';
                return Card(child: ListTile(
                  title: Text(item['title']?.toString() ?? 'Untitled'),
                  subtitle: Text(subtitle, maxLines: 3, overflow: TextOverflow.ellipsis),
                  trailing: Wrap(spacing: 4, children: [
                    IconButton(tooltip: 'Edit', onPressed: _busy ? null : () => _section == 'watchlists' ? _editWatchlist(item) : _editNote(item), icon: const Icon(Icons.edit_outlined)),
                    IconButton(tooltip: 'Delete', onPressed: _busy ? null : () => _deleteItem(item, _section), icon: const Icon(Icons.delete_outline)),
                  ]),
                ));
              },
            )),
    ]);
  }
}
