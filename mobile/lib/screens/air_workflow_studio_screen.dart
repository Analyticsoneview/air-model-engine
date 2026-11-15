import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

/// Administrator Workflow Studio for creating, activating and inspecting AIR workflows.
class AirWorkflowStudioScreen extends StatefulWidget {
  const AirWorkflowStudioScreen({
    super.key,
    required this.apiBase,
    required this.accessToken,
    this.httpClient,
  });

  final String apiBase;
  final String accessToken;
  final http.Client? httpClient;

  @override
  State<AirWorkflowStudioScreen> createState() => _AirWorkflowStudioScreenState();
}

class _AirWorkflowStudioScreenState extends State<AirWorkflowStudioScreen> {
  late final http.Client _client = widget.httpClient ?? http.Client();
  late final bool _ownsClient = widget.httpClient == null;
  final _name = TextEditingController();
  final _customerId = TextEditingController();
  final _accountId = TextEditingController();
  final _eventType = TextEditingController(text: 'qoc.candidate.qualified');
  final _strategy = TextEditingController(text: 'ORB');
  final _notificationStrategy = TextEditingController(text: 'AIR_QOC');
  final _hour = TextEditingController(text: '09');
  final _minute = TextEditingController(text: '18');
  final _params = TextEditingController(text: '{"mode":"LIVE","max_candidates":20}');
  final _filters = TextEditingController(
    text: '[{"field":"score","operator":"gte","value":80}]',
  );
  String _trigger = 'EVENT';
  String _action = 'qoc.qualify';
  String _mode = 'RESEARCH_ONLY';
  String _match = 'ALL';
  String? _editingWorkflowId;
  bool _notifyAfter = false;
  bool _busy = false;
  String? _error;
  List<Map<String, dynamic>> _workflows = [];
  List<Map<String, dynamic>> _runs = [];
  final Map<String, List<Map<String, dynamic>>> _steps = {};
  final Set<String> _expandedRuns = {};

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
        response = await _client.post(_uri(path), headers: headers,
            body: body == null ? null : jsonEncode(body));
        break;
      case 'PUT':
        response = await _client.put(_uri(path), headers: headers,
            body: body == null ? null : jsonEncode(body));
        break;
      default:
        response = await _client.get(_uri(path), headers: headers);
    }
    final decoded = jsonDecode(response.body);
    final data = decoded is Map<String, dynamic>
        ? decoded
        : <String, dynamic>{};
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(data['detail']?.toString() ??
          'AIR workflow API returned HTTP ${response.statusCode}');
    }
    return data;
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant AirWorkflowStudioScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.accessToken != widget.accessToken ||
        oldWidget.apiBase != widget.apiBase) {
      _load();
    }
  }

  @override
  void dispose() {
    _name.dispose();
    _customerId.dispose();
    _accountId.dispose();
    _eventType.dispose();
    _strategy.dispose();
    _notificationStrategy.dispose();
    _hour.dispose();
    _minute.dispose();
    _params.dispose();
    _filters.dispose();
    if (_ownsClient) _client.close();
    super.dispose();
  }

  Future<void> _load() async {
    if (!mounted) return;
    setState(() { _busy = true; _error = null; });
    try {
      final results = await Future.wait([
        _request('GET', '/api/v1/admin/workflows?limit=200'),
        _request('GET', '/api/v1/admin/workflows/runs?limit=100'),
      ]);
      _workflows = (results[0]['workflows'] as List? ?? [])
          .whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
      _runs = (results[1]['runs'] as List? ?? [])
          .whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
    } catch (e) {
      _error = e.toString();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Map<String, dynamic> _triggerConfig() {
    final customer = _customerId.text.trim();
    final event = _eventType.text.trim();
    if (_trigger == 'TIME') {
      final hour = int.tryParse(_hour.text.trim());
      final minute = int.tryParse(_minute.text.trim());
      if (hour == null || hour < 0 || hour > 23 ||
          minute == null || minute < 0 || minute > 59) {
        throw const FormatException('Enter a valid 24-hour time.');
      }
      return {
        'timezone': 'Asia/Kolkata',
        'hour': hour,
        'minute': minute,
        'days_of_week': [0, 1, 2, 3, 4],
        'misfire_grace_seconds': 300,
        if (customer.isNotEmpty) 'customer_id': customer,
      };
    }
    if (event.isEmpty) throw const FormatException('Enter an event type.');
    if (_trigger == 'CONDITION') {
      final filters = jsonDecode(_filters.text);
      if (filters is! List || filters.isEmpty) {
        throw const FormatException('Condition filters must be a non-empty JSON array.');
      }
      return {
        'event_type': event,
        'match': _match,
        'filters': filters,
        if (customer.isNotEmpty) 'customer_id': customer,
      };
    }
    if (_trigger == 'STRATEGY') {
      if (_strategy.text.trim().isEmpty) {
        throw const FormatException('Enter a strategy name.');
      }
      return {
        'event_type': event,
        'strategy': _notificationStrategy.text.trim().toUpperCase(),
        if (customer.isNotEmpty) 'customer_id': customer,
      };
    }
    return {
      'event_type': event,
      if (customer.isNotEmpty) 'customer_id': customer,
    };
  }

  Future<void> _createWorkflow() async {
    if (_name.text.trim().isEmpty) {
      setState(() => _error = 'Enter a workflow name.');
      return;
    }
    setState(() { _busy = true; _error = null; });
    try {
      final paramsValue = jsonDecode(_params.text);
      if (paramsValue is! Map) {
        throw const FormatException('Action parameters must be a JSON object.');
      }
      final params = Map<String, dynamic>.from(paramsValue);
      final customerScopedAction = _action.startsWith('qoc.') ||
          _action == 'portfolio.overview' || _action == 'notify.telegram' || _notifyAfter;
      if (customerScopedAction && _customerId.text.trim().isEmpty) {
        throw const FormatException('Customer ID is required for customer-owned research and notification actions.');
      }
      if (_accountId.text.trim().isNotEmpty && _action.startsWith('qoc.')) {
        params['account_id'] = _accountId.text.trim();
      }
      final steps = <Map<String, dynamic>>[
        {'id': 'research', 'action': _action, 'params': params},
      ];
      var mode = _mode;
      if (_action == 'notify.telegram') {
        mode = 'ALERT_NOTIFY';
        params['strategy'] = _notificationStrategy.text.trim().toUpperCase();
      } else if (_notifyAfter) {
        mode = 'ALERT_NOTIFY';
        steps.add({
          'id': 'notify',
          'action': 'notify.telegram',
          'params': {
            'strategy': _strategy.text.trim().toUpperCase(),
            'source_step': 'research',
          },
        });
      }
      final body = {
        'name': _name.text.trim(),
        'description': 'Created in AIR Workflow Studio',
        'trigger_type': _trigger,
        'trigger_config': _triggerConfig(),
        'workflow_spec': {'steps': steps},
        'execution_mode': mode,
      };
      final editingId = _editingWorkflowId;
      final created = await _request(editingId == null ? 'POST' : 'PUT',
          editingId == null ? '/api/v1/admin/workflows' : '/api/v1/admin/workflows/${Uri.encodeComponent(editingId)}', body: body);
      _name.clear();
      _editingWorkflowId = null;
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('${editingId == null ? 'Workflow created' : 'New version saved'} · version ${created['version'] ?? 1}. Enable it when ready.'),
        ));
      }
      await _load();
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _editWorkflow(Map<String, dynamic> workflow) {
    final spec = Map<String, dynamic>.from(workflow['workflow_spec'] as Map? ?? {});
    final steps = (spec['steps'] as List? ?? [])
        .whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
    if (steps.isEmpty || steps.length > 2 || (steps.length == 2 && steps[1]['action'] != 'notify.telegram')) {
      _error = 'This workflow has a step layout that the simple editor cannot safely preserve. Use the workflow API for this advanced definition.';
      setState(() {});
      return;
    }
    final first = steps.first;
    final firstParams = Map<String, dynamic>.from(first['params'] as Map? ?? {});
    final notifyStep = steps.length > 1 && steps[1]['action'] == 'notify.telegram'
        ? steps[1] : null;
    final notifyParams = Map<String, dynamic>.from(notifyStep?['params'] as Map? ?? {});
    final triggerConfig = Map<String, dynamic>.from(workflow['trigger_config'] as Map? ?? {});
    setState(() {
      _editingWorkflowId = workflow['workflow_id'].toString();
      _name.text = workflow['name']?.toString() ?? '';
      _trigger = workflow['trigger_type']?.toString() ?? 'EVENT';
      _eventType.text = (triggerConfig['event_type'] ??
          (triggerConfig['event_types'] is List && (triggerConfig['event_types'] as List).isNotEmpty
              ? (triggerConfig['event_types'] as List).first : 'qoc.candidate.qualified')).toString();
      _strategy.text = (triggerConfig['strategy'] ?? 'ORB').toString();
      _notificationStrategy.text = (notifyParams['strategy'] ?? firstParams['strategy'] ?? 'AIR_QOC').toString();
      _customerId.text = triggerConfig['customer_id']?.toString() ?? '';
      _accountId.text = firstParams['account_id']?.toString() ?? '';
      _hour.text = (triggerConfig['hour'] ?? 9).toString().padLeft(2, '0');
      _minute.text = (triggerConfig['minute'] ?? 18).toString().padLeft(2, '0');
      _match = triggerConfig['match']?.toString() ?? 'ALL';
      _filters.text = jsonEncode(triggerConfig['filters'] ?? []);
      _action = first['action']?.toString() ?? 'qoc.qualify';
      _params.text = const JsonEncoder.withIndent('  ').convert(firstParams);
      _notifyAfter = notifyStep != null;
      _mode = workflow['execution_mode']?.toString() ?? 'RESEARCH_ONLY';
      _error = null;
    });
  }

  void _cancelEdit() {
    setState(() {
      _editingWorkflowId = null;
      _name.clear();
      _customerId.clear();
      _accountId.clear();
      _strategy.text = 'ORB';
      _notificationStrategy.text = 'AIR_QOC';
      _trigger = 'EVENT';
      _action = 'qoc.qualify';
      _mode = 'RESEARCH_ONLY';
      _notifyAfter = false;
      _params.text = '{"mode":"LIVE","max_candidates":20}';
      _error = null;
    });
  }

  Future<void> _toggleWorkflow(Map<String, dynamic> workflow, bool enabled) async {
    final id = Uri.encodeComponent(workflow['workflow_id'].toString());
    setState(() { _busy = true; _error = null; });
    try {
      await _request('POST',
          '/api/v1/admin/workflows/$id/enabled?enabled=$enabled');
      await _load();
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _loadRunSteps(String runId) async {
    try {
      final result = await _request('GET',
          '/api/v1/admin/workflows/runs/${Uri.encodeComponent(runId)}/steps');
      _steps[runId] = (result['steps'] as List? ?? [])
          .whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
      if (mounted) setState(() {});
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    }
  }

  Future<void> _showVersions(Map<String, dynamic> workflow) async {
    final id = Uri.encodeComponent(workflow['workflow_id'].toString());
    try {
      final result = await _request('GET', '/api/v1/admin/workflows/$id/versions');
      final versions = (result['versions'] as List? ?? [])
          .whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
      if (!mounted) return;
      await showDialog<void>(context: context, builder: (ctx) => AlertDialog(
        title: const Text('IMMUTABLE WORKFLOW VERSIONS'),
        content: SizedBox(width: 520, child: ListView(
          shrinkWrap: true,
          children: versions.map((version) => ListTile(
            leading: CircleAvatar(child: Text('v${version['version']}')),
            title: Text(version['name']?.toString() ?? 'Workflow'),
            subtitle: Text('${version['trigger_type']} · ${version['execution_mode']} · ${version['created_at']}'),
          )).toList(),
        )),
        actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('CLOSE'))],
      ));
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    }
  }

  Widget _field(TextEditingController controller, String label, {String? hint, int maxLines = 1}) =>
      Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: TextField(
          controller: controller,
          maxLines: maxLines,
          decoration: InputDecoration(
            labelText: label, hintText: hint, isDense: true,
            border: const OutlineInputBorder(),
          ),
        ),
      );

  Widget _builder() => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('WORKFLOW BUILDER', style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: .8)),
        const SizedBox(height: 5),
        const Text('Choose a trigger, define the research action and optionally notify a customer-owned Telegram destination.'),
        const SizedBox(height: 14),
        _field(_name, 'Workflow name', hint: 'Example: Morning AIR QOC scan'),
        DropdownButtonFormField<String>(
          value: _trigger,
          decoration: const InputDecoration(labelText: 'Trigger type', border: OutlineInputBorder(), isDense: true),
          items: const [
            DropdownMenuItem(value: 'TIME', child: Text('Time based')),
            DropdownMenuItem(value: 'EVENT', child: Text('Event based')),
            DropdownMenuItem(value: 'STRATEGY', child: Text('Strategy based')),
            DropdownMenuItem(value: 'CONDITION', child: Text('Condition based')),
          ],
          onChanged: _busy ? null : (value) => setState(() => _trigger = value ?? 'EVENT'),
        ),
        const SizedBox(height: 10),
        if (_trigger == 'TIME') Row(children: [
          Expanded(child: _field(_hour, 'Hour (IST)', hint: '09')),
          const SizedBox(width: 8),
          Expanded(child: _field(_minute, 'Minute', hint: '18')),
        ]),
        if (_trigger != 'TIME') _field(_eventType, 'Event type', hint: 'qoc.candidate.qualified'),
        if (_trigger == 'STRATEGY') _field(_strategy, 'Strategy name', hint: 'ORB'),
        if (_trigger == 'CONDITION') ...[
          DropdownButtonFormField<String>(
            value: _match,
            decoration: const InputDecoration(labelText: 'Condition matching', border: OutlineInputBorder(), isDense: true),
            items: const [
              DropdownMenuItem(value: 'ALL', child: Text('ALL conditions')),
              DropdownMenuItem(value: 'ANY', child: Text('ANY condition')),
            ],
            onChanged: _busy ? null : (value) => setState(() => _match = value ?? 'ALL'),
          ),
          const SizedBox(height: 10),
          _field(_filters, 'Condition filters (JSON)', maxLines: 4),
        ],
        _field(_customerId, 'Customer ID', hint: 'Required for customer-owned actions'),
        if (_action.startsWith('qoc.'))
          _field(_accountId, 'Broker account ID (optional if supplied by trigger)', hint: 'Account ID linked to this customer'),
        DropdownButtonFormField<String>(
          value: _action,
          decoration: const InputDecoration(labelText: 'Workflow action', border: OutlineInputBorder(), isDense: true),
          items: const [
            DropdownMenuItem(value: 'qoc.qualify', child: Text('AIR QOC qualification')),
            DropdownMenuItem(value: 'qoc.backtest', child: Text('AIR QOC backtest')),
            DropdownMenuItem(value: 'portfolio.overview', child: Text('Portfolio risk overview')),
            DropdownMenuItem(value: 'event.emit', child: Text('Emit follow-up event')),
            DropdownMenuItem(value: 'notify.telegram', child: Text('Telegram notification')),
          ],
          onChanged: _busy ? null : (value) => setState(() => _action = value ?? 'qoc.qualify'),
        ),
        const SizedBox(height: 10),
        if (_action == 'notify.telegram' || _notifyAfter)
          _field(_notificationStrategy, 'Telegram strategy route', hint: 'AIR_QOC'),
        if (_action != 'notify.telegram')
          _field(_params, 'Action parameters (JSON)', maxLines: 3),
        if (_action != 'notify.telegram')
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            value: _notifyAfter,
            onChanged: _busy ? null : (value) => setState(() => _notifyAfter = value),
            title: const Text('Send Telegram notification after action'),
            subtitle: const Text('Uses only the matching customer-owned destination.'),
          ),
        DropdownButtonFormField<String>(
          value: _mode,
          decoration: const InputDecoration(labelText: 'Execution mode', border: OutlineInputBorder(), isDense: true),
          items: const [
            DropdownMenuItem(value: 'RESEARCH_ONLY', child: Text('Research only')),
            DropdownMenuItem(value: 'ALERT_NOTIFY', child: Text('Alert and notify')),
          ],
          onChanged: _busy || _action == 'notify.telegram' || _notifyAfter
              ? null : (value) => setState(() => _mode = value ?? 'RESEARCH_ONLY'),
        ),
        const SizedBox(height: 12),
        if (_editingWorkflowId != null)
          Align(alignment: Alignment.centerRight, child: TextButton(
            onPressed: _busy ? null : _cancelEdit, child: const Text('CANCEL EDIT'),
          )),
        SizedBox(width: double.infinity, child: FilledButton.icon(
          onPressed: _busy ? null : _createWorkflow,
          icon: const Icon(Icons.add_task),
          label: Text(_editingWorkflowId == null ? 'CREATE WORKFLOW' : 'SAVE NEW VERSION'),
        )),
      ]),
    ),
  );

  Widget _workflowList() => Card(
    child: Padding(
      padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Expanded(child: Text('WORKFLOWS', style: TextStyle(fontWeight: FontWeight.w900))),
          TextButton.icon(onPressed: _busy ? null : _load,
              icon: const Icon(Icons.refresh), label: const Text('Refresh')),
        ]),
        if (_workflows.isEmpty) const Padding(
          padding: EdgeInsets.all(12),
          child: Text('No workflows created yet. Use the builder to add one.'),
        ),
        for (final workflow in _workflows)
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(workflow['name']?.toString() ?? 'Workflow',
                style: const TextStyle(fontWeight: FontWeight.w800)),
            subtitle: Text('${workflow['trigger_type']} · v${workflow['version']} · ${workflow['execution_mode']}'),
            leading: Icon(workflow['enabled'] == true ? Icons.play_circle_fill : Icons.pause_circle_outline,
                color: workflow['enabled'] == true ? Colors.green : Colors.grey),
            trailing: Row(mainAxisSize: MainAxisSize.min, children: [
              IconButton(tooltip: 'Edit as new version',
                onPressed: _busy ? null : () => _editWorkflow(workflow),
                icon: const Icon(Icons.edit_outlined)),
              IconButton(tooltip: 'Version history',
                onPressed: _busy ? null : () => _showVersions(workflow),
                icon: const Icon(Icons.history)),
              Switch(value: workflow['enabled'] == true,
                onChanged: _busy ? null : (value) => _toggleWorkflow(workflow, value)),
            ]),
          ),
      ]),
    ),
  );

  Widget _runHistory() => Card(
    child: Padding(
      padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('EXECUTION HISTORY', style: TextStyle(fontWeight: FontWeight.w900)),
        const SizedBox(height: 8),
        if (_runs.isEmpty) const Text('No workflow runs recorded yet.'),
        for (final run in _runs)
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: Text('${run['status']} · ${run['execution_mode']}',
                style: const TextStyle(fontWeight: FontWeight.w800)),
            subtitle: Text('${run['run_id']}\n${run['started_at'] ?? ''}'),
            onExpansionChanged: (expanded) {
              final id = run['run_id'].toString();
              if (expanded && !_expandedRuns.contains(id)) {
                _expandedRuns.add(id);
                _loadRunSteps(id);
              }
            },
            children: [
              if (_steps[run['run_id']] == null)
                const Padding(padding: EdgeInsets.all(8), child: CircularProgressIndicator()),
              for (final step in _steps[run['run_id']] ?? [])
                ListTile(
                  dense: true,
                  leading: Icon(
                    step['status'] == 'SUCCEEDED' ? Icons.check_circle :
                    step['status'] == 'FAILED' ? Icons.error_outline : Icons.pending,
                  ),
                  title: Text('${step['step_key']} · ${step['action']}'),
                  subtitle: Text('${step['status']} · attempts ${step['attempts']}'
                      '${step['error'] == null ? '' : '\n${step['error']}'}'),
                ),
            ],
          ),
      ]),
    ),
  );

  @override
  Widget build(BuildContext context) => RefreshIndicator(
    onRefresh: _load,
    child: ListView(
      padding: const EdgeInsets.all(12),
      children: [
        const Text('AIR WORKFLOW STUDIO',
            style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: 1.0)),
        const SizedBox(height: 4),
        const Text('Automate time, event, strategy and condition-driven AIR research. No broker orders are executed.'),
        if (_error != null) Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
        ),
        _builder(),
        _workflowList(),
        _runHistory(),
        if (_busy) const LinearProgressIndicator(),
      ],
    ),
  );
}
