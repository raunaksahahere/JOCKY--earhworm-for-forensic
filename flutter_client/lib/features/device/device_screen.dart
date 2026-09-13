import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../state/providers.dart';

/// Views display backend observations verbatim; no forensic decisions in Dart.
class DeviceScreen extends ConsumerStatefulWidget {
  const DeviceScreen({super.key, this.caseId});
  final String? caseId;
  @override
  ConsumerState<DeviceScreen> createState() => _DeviceScreenState();
}

class _DeviceScreenState extends ConsumerState<DeviceScreen> {
  Map<String, dynamic>? _case;
  List<dynamic> _cases = [], _evidence = [], _findings = [], _timeline = [], _reports = [];
  final _title = TextEditingController(text: 'Local device investigation');
  final _examiner = TextEditingController();
  final _search = TextEditingController();
  final List<String> _paths = [];
  String? _error, _notice;
  String _statusFilter = 'all';
  bool _busy = false;
  Timer? _timer;
  static const terminal = {'completed', 'partially_completed', 'failed', 'cancelled', 'interrupted'};

  @override
  void initState() {
    super.initState();
    Future.microtask(_load);
    _timer = Timer.periodic(const Duration(seconds: 2), (_) {
      if (widget.caseId != null && !terminal.contains(_case?['status'])) _load();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _title.dispose();
    _examiner.dispose();
    _search.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final api = ref.read(apiClientProvider);
    if (!api.hasSession) return;
    try {
      if (widget.caseId == null) {
        final data = await api.jsonRequest('/api/v1/investigations?search=${Uri.encodeQueryComponent(_search.text)}${_statusFilter == 'all' ? '' : '&status=$_statusFilter'}');
        if (mounted) { setState(() { _cases = data['items'] as List; _error = null; }); }
      } else {
        final base = '/api/v1/investigations/${widget.caseId}';
        final data = await Future.wait([
          api.jsonRequest(base), api.jsonRequest('$base/evidence'), api.jsonRequest('$base/findings'),
          api.jsonRequest('$base/timeline'), api.jsonRequest('$base/reports'),
        ]);
        if (mounted) { setState(() {
          _case = data[0]; _evidence = data[1]['items'] as List; _findings = data[2]['items'] as List;
          _timeline = data[3]['items'] as List; _reports = data[4]['items'] as List; _error = null;
        }); }
        if (terminal.contains(_case?['status'])) await ref.read(recordsControllerProvider.notifier).refresh();
      }
    } on Object catch (error) {
      if (mounted) setState(() => _error = '$error');
    }
  }

  Future<void> _analyze() async {
    setState(() { _busy = true; _error = null; });
    try {
      final api = ref.read(apiClientProvider);
      final investigation = await api.jsonRequest('/api/v1/investigations', body: {'title': _title.text, 'examiner': _examiner.text});
      final id = investigation['id'] as String;
      await api.jsonRequest('/api/v1/investigations/$id/collect', body: {'paths': _paths});
      await ref.read(recordsControllerProvider.notifier).refresh();
      if (mounted) context.go('/device/$id');
    } on Object catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _export(String format) async {
    final path = await ref.read(fileSelectionProvider).pickSaveLocation(suggestedName: 'jocky-${widget.caseId}.$format', extension: format);
    if (path == null) return;
    setState(() => _busy = true);
    try {
      final response = await ref.read(apiClientProvider).request('/api/v1/investigations/${widget.caseId}/report/export', body: {'format': format});
      // Native save dialog obtains overwrite consent; write a sibling temporary
      // first so export failures do not destroy an existing selected file.
      final temporary = File('$path.jocky-export.tmp');
      await temporary.writeAsBytes(response.bodyBytes, flush: true);
      await temporary.rename(path);
      if (mounted) setState(() => _notice = 'Exported $path');
    } on Object catch (error) {
      if (mounted) setState(() => _error = 'Export failed: $error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _json(Object? value) => SelectableText(const JsonEncoder.withIndent('  ').convert(value), style: const TextStyle(fontFamily: 'monospace', fontSize: 12));
  Widget _section(String title, Object? value) => ExpansionTile(title: Text(title), initiallyExpanded: title == 'Device information', children: [Padding(padding: const EdgeInsets.all(16), child: Align(alignment: Alignment.centerLeft, child: _json(value)))]);

  @override
  Widget build(BuildContext context) {
    ref.listen(backendReadyProvider, (previous, next) { if (next) _load(); });
    final ready = ref.watch(backendReadyProvider);
    return ListView(padding: const EdgeInsets.all(24), children: [
      Row(children: [Expanded(child: Text(widget.caseId == null ? 'Portable forensic workstation' : '${_case?['title'] ?? 'Preparing investigation'}', style: Theme.of(context).textTheme.headlineSmall)),
        IconButton(tooltip: 'Refresh investigations', onPressed: _load, icon: const Icon(Icons.refresh))]),
      const SizedBox(height: 12),
      const Text('Run JOCKY on the authorized investigation machine. Collection is local and observation-only. Process snapshots are CURRENT OBSERVATIONS, not historical execution evidence.'),
      if (!ready) const Padding(padding: EdgeInsets.all(12), child: Text('Waiting for the authenticated local engine. Check System Status if it does not become ready.')),
      if (_error != null) Padding(padding: const EdgeInsets.all(12), child: SelectableText(_error!, style: const TextStyle(color: Colors.redAccent))),
      if (_notice != null) Padding(padding: const EdgeInsets.all(12), child: SelectableText(_notice!)),
      const SizedBox(height: 20),
      if (widget.caseId == null) ...[
        TextField(controller: _title, decoration: const InputDecoration(labelText: 'Investigation title')),
        const SizedBox(height: 12),
        TextField(controller: _examiner, decoration: const InputDecoration(labelText: 'Investigator (optional)')),
        const SizedBox(height: 12),
        const Text('System information and current processes are collected. Add file sources explicitly; no whole-disk scan is performed. Up to 20 sources, files up to 128 MiB.'),
        Wrap(spacing: 12, children: [
          TextButton.icon(onPressed: _paths.length >= 20 ? null : () async { final path = await ref.read(fileSelectionProvider).pickFile(); if (path != null && mounted) setState(() => _paths.add(path)); }, icon: const Icon(Icons.attach_file), label: const Text('Add file')),
          TextButton.icon(onPressed: _paths.length >= 20 ? null : () async { final path = await ref.read(fileSelectionProvider).pickDirectory(); if (path != null && mounted) setState(() => _paths.add(path)); }, icon: const Icon(Icons.folder_open), label: const Text('Add directory')),
        ]),
        for (final path in _paths) ListTile(title: Text(path), trailing: IconButton(icon: const Icon(Icons.close), onPressed: () => setState(() => _paths.remove(path)))),
        Align(alignment: Alignment.centerLeft, child: FilledButton.icon(key: const Key('analyze-device'), onPressed: ready && !_busy ? _analyze : null, icon: const Icon(Icons.manage_search), label: Text(_busy ? 'Preparing investigation…' : 'Analyze This Device'))),
        const SizedBox(height: 32),
        Text('Previous investigations', style: Theme.of(context).textTheme.titleLarge),
        Row(children: [Expanded(child: TextField(controller: _search, onChanged: (_) => _load(), decoration: const InputDecoration(labelText: 'Search title, device or investigation ID', prefixIcon: Icon(Icons.search)))),
          const SizedBox(width: 12), DropdownButton<String>(value: _statusFilter, items: ['all', 'created', 'collecting', 'completed', 'partially_completed', 'failed', 'interrupted', 'cancelled'].map((s) => DropdownMenuItem(value: s, child: Text(s.replaceAll('_', ' ')))).toList(), onChanged: (value) { setState(() => _statusFilter = value!); _load(); })]),
        if (_cases.isEmpty) const Padding(padding: EdgeInsets.all(24), child: Text('No investigations match.')),
        for (final item in _cases) Card(child: ListTile(title: Text('${item['title']}'), subtitle: Text('${item['created_at']} · ${item['device']['hostname'] ?? 'Device not collected'}\n${item['status']} · ${item['finding_count']} findings · ${item['evidence_count']} evidence records'), trailing: const Icon(Icons.chevron_right), onTap: () => context.go('/device/${item['id']}'))),
      ] else ...[
        Wrap(spacing: 12, runSpacing: 8, children: [
          Chip(label: Text('Stage: ${_case?['status'] ?? 'preparing'}')),
          if (_reports.isNotEmpty) FilledButton.icon(key: const Key('export-investigation-pdf'), onPressed: _busy ? null : () => _export('pdf'), icon: const Icon(Icons.picture_as_pdf), label: const Text('Export PDF')),
          if (_reports.isNotEmpty) OutlinedButton(onPressed: _busy ? null : () => _export('json'), child: const Text('Export JSON')),
          if (_case != null && !terminal.contains(_case!['status']) && _case!['status'] != 'created') OutlinedButton(onPressed: () async { await ref.read(apiClientProvider).jsonRequest('/api/v1/investigations/${widget.caseId}/cancel', body: {}); if (mounted) setState(() => _notice = 'Cancellation requested; the current bounded step may finish first.'); }, child: const Text('Cancel collection')),
          TextButton(onPressed: () => context.go('/device'), child: const Text('All investigations')),
        ]),
        if (!terminal.contains(_case?['status'])) const Padding(padding: EdgeInsets.all(16), child: Text('Preparing → Collecting → Analyzing → Finalizing. Exact progress is unavailable; stages reflect persisted backend state.')),
        _section('Device information', _case?['device']),
        _section('Investigation context', _case),
        _section('Timeline', _timeline),
        _section('Processes — CURRENT OBSERVATION', _evidence.where((e) => e['type'] == 'PROCESSES').toList()),
        _section('Files, hashes, indicators and integrity', _evidence.where((e) => e['type'] == 'FILES').toList()),
        _section('Findings — INFERRED; requires review', _findings),
        _section('Evidence references', _evidence),
        _section('Reports and limitations', _reports),
      ],
    ]);
  }
}
