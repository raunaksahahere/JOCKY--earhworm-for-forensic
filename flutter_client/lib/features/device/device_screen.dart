import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/tokens.dart';
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
  List<dynamic> _executionEvents = [], _artifacts = [], _eventTimeline = [];
  final _title = TextEditingController(text: 'Local device investigation');
  final _examiner = TextEditingController();
  final _search = TextEditingController();
  final _windowHours = TextEditingController(text: '168');
  final _activitySearch = TextEditingController();
  String _triageFilter = 'all';
  // How a record is presented, which is a different question from what the
  // evidence supports. An investigator wanting to skip the accounted-for
  // majority filters on this, and the triage category behind each record is
  // untouched by it.
  String _presentationFilter = 'all';
  static const _presentationLabels = {
    'ROUTINE_RECOGNIZED': 'Routine / recognized',
    'FOR_REVIEW': 'For review',
    'NEEDS_ATTENTION': 'Needs attention',
  };

  /// The presentation of one stored row.
  ///
  /// The engine decides this during analysis and stores the triage it informed;
  /// the client derives the bucket from what was stored rather than asking for
  /// a second opinion it would have to keep in step.
  String _presentationOf(dynamic row) {
    if (row['recognized_name'] != null && '${row['triage']}' != 'POTENTIALLY_HARMFUL') {
      return 'ROUTINE_RECOGNIZED';
    }
    return switch ('${row['triage']}') {
      'POTENTIALLY_HARMFUL' => 'NEEDS_ATTENTION',
      'NOT_HARMFUL_ON_AVAILABLE_EVIDENCE' => 'ROUTINE_RECOGNIZED',
      _ => 'FOR_REVIEW',
    };
  }
  // Opens on what deserves attention. "All evidence" is one click away and
  // nothing is hidden -- the appendices and the database hold every record.
  String _priorityFilter = 'leads';
  final Set<String> _expanded = {};
  final List<String> _paths = [];
  // Sources beyond the baseline. The baseline -- system, processes, execution
  // history and the files those name -- always runs, because the report is
  // built from it. These are the ones the investigator chooses.
  final Set<String> _sources = {};
  final _memoryImage = TextEditingController();
  String? _error, _notice;
  String _statusFilter = 'all';
  bool _busy = false;
  bool _includeCommandLines = false;
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
    _windowHours.dispose();
    _memoryImage.dispose();
    _activitySearch.dispose();
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
          api.jsonRequest('$base/execution-events'), api.jsonRequest('$base/artifacts'),
          api.jsonRequest('$base/event-timeline'),
        ]);
        if (mounted) { setState(() {
          _case = data[0]; _evidence = data[1]['items'] as List; _findings = data[2]['items'] as List;
          _timeline = data[3]['items'] as List; _reports = data[4]['items'] as List;
          _executionEvents = data[5]['items'] as List; _artifacts = data[6]['items'] as List;
          _eventTimeline = data[7]['items'] as List; _error = null;
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
      await api.jsonRequest('/api/v1/investigations/$id/collect', body: {
        'paths': _paths,
        'window_hours': double.tryParse(_windowHours.text.trim()) ?? 168,
        'include_command_lines': _includeCommandLines,
        'sources': _sources.toList(),
        if (_sources.contains('MEMORY')) 'memory_image': _memoryImage.text.trim(),
      });
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

  /// The engine's own report payload. Every number below is read from it
  /// rather than recomputed here, so the UI can never claim more than the
  /// backend recorded.
  Map<String, dynamic> get _report {
    final payload = _reports.isEmpty ? null : _reports.last['payload'];
    return payload is Map<String, dynamic> ? payload : const {};
  }

  Map<String, dynamic> get _history {
    final value = _report['historical_execution'];
    return value is Map<String, dynamic> ? value : const {};
  }

  List<dynamic> get _limitations => _report['limitations'] as List? ?? const [];

  Map<String, dynamic> get _counts {
    final value = _report['record_counts'];
    return value is Map<String, dynamic> ? value : const {};
  }

  List<dynamic> get _leads => _report['leads'] as List? ?? const [];
  List<dynamic> get _threads => _report['threads'] as List? ?? const [];

  Map<String, dynamic> get _significant {
    final value = _report['significant_events'];
    return value is Map<String, dynamic> ? value : const {};
  }

  Widget _sectionCard(String title, String? subtitle, List<Widget> children) => Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: Theme.of(context).textTheme.titleMedium),
            if (subtitle != null) ...[
              const SizedBox(height: 4),
              SelectableText(subtitle, style: const TextStyle(fontSize: 12)),
            ],
            const SizedBox(height: 10),
            ...children,
          ]),
        ),
      );

  /// Repeated occurrences of one pattern appear once, with every command and
  /// evidence identifier kept inside the lead.
  Widget _leadsCard() {
    if (_reports.isEmpty) return const SizedBox.shrink();
    if (_leads.isEmpty) {
      return _sectionCard('Top investigative leads', null, const [
        Text('No activity reached the review or investigate-first tiers. This means no rule '
             'combined enough signals, not that the device is clear.',
             style: TextStyle(fontSize: 12.5)),
      ]);
    }
    return _sectionCard(
      'Top investigative leads', '${_leads.length} pattern(s) worth an investigator\'s time.',
      [for (final lead in _leads) _leadTile(lead)],
    );
  }

  Widget _leadTile(dynamic lead) {
    final commands = (lead['commands'] as List? ?? const []);
    final references = (lead['evidence_references'] as List? ?? const []);
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        border: Border(left: BorderSide(color: _priorityColor('${lead['priority']}'), width: 3)),
        color: Theme.of(context).colorScheme.surfaceContainerHighest.withValues(alpha: 0.25),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 10, runSpacing: 4, children: [
          Text('${lead['lead_id']}',
              style: const TextStyle(fontSize: 11, fontFamily: 'monospace')),
          Text(_priorityLabels['${lead['priority']}'] ?? '',
              style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700,
                  color: _priorityColor('${lead['priority']}'))),
          Text(_triageLabels['${lead['classification']}'] ?? '',
              style: TextStyle(fontSize: 11, color: _triageColor('${lead['classification']}'))),
        ]),
        const SizedBox(height: 4),
        SelectableText('${lead['title']}',
            style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
        Text('${lead['activity_count']} related command(s) | ${lead['record_count']} records'
             '  |  Execution: '
             '${lead['execution_confirmed'] == true ? 'CONFIRMED' : 'NOT ESTABLISHED'}',
            style: const TextStyle(fontSize: 11.5)),
        const SizedBox(height: 6),
        for (final command in commands.take(6))
          SelectableText('$command',
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
        if (commands.length > 6)
          Text('... ${commands.length - 6} further commands in this pattern',
              style: const TextStyle(fontSize: 11.5)),
        const SizedBox(height: 4),
        for (final why in (lead['why'] as List? ?? const []))
          Text('Why it matters: $why', style: const TextStyle(fontSize: 11.5)),
        for (final note in (lead['context'] as List? ?? const []))
          Text('Context: $note', style: const TextStyle(fontSize: 11.5)),
        for (final unknown in (lead['unknowns'] as List? ?? const []))
          Text('Unknown: $unknown', style: const TextStyle(fontSize: 11.5)),
        if (lead['recommended_action'] != null)
          Text('Next step: ${lead['recommended_action']}',
              style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600)),
        SelectableText('Evidence: ${references.take(10).join(', ')}'
            '${references.length > 10 ? ', +${references.length - 10} more' : ''}',
            style: const TextStyle(fontSize: 11, fontFamily: 'monospace')),
      ]),
    );
  }

  /// Related activity read as one story. The full command list and evidence
  /// identifiers sit behind the expansion, not in the summary.
  Widget _threadsCard() {
    if (_reports.isEmpty || _threads.isEmpty) return const SizedBox.shrink();
    return _sectionCard(
      'Investigation threads',
      'Records that appear related, grouped so a sequence reads as one story. A thread states '
      'that records appear related; it does not state what anyone intended by them.',
      [
        for (final thread in _threads.take(10))
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: Text('${thread['thread_id']}  ${thread['title']}',
                style: const TextStyle(fontSize: 13)),
            subtitle: Text(
                '${_priorityLabels['${thread['priority']}'] ?? ''}  |  '
                '${thread['activity_count']} activities, ${thread['record_count']} records',
                style: TextStyle(fontSize: 11.5, color: _priorityColor('${thread['priority']}'))),
            children: [
              Padding(
                padding: const EdgeInsets.only(left: 8, right: 8, bottom: 12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  SelectableText('Why: ${thread['why']}', style: const TextStyle(fontSize: 12)),
                  SelectableText('Execution: ${thread['execution']}',
                      style: const TextStyle(fontSize: 12)),
                  const SizedBox(height: 6),
                  for (final command in (thread['commands'] as List? ?? const []))
                    SelectableText('$command',
                        style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
                  const SizedBox(height: 6),
                  for (final unknown in (thread['unknowns'] as List? ?? const []))
                    Text('Unknown: $unknown', style: const TextStyle(fontSize: 11.5)),
                  SelectableText(
                      'Evidence: ${(thread['evidence_references'] as List? ?? const []).join(', ')}',
                      style: const TextStyle(fontSize: 11, fontFamily: 'monospace')),
                ]),
              ),
            ],
          ),
      ],
    );
  }

  Widget _significantEventsCard() {
    final entries = _significant['entries'] as List? ?? const [];
    if (_reports.isEmpty) return const SizedBox.shrink();
    return _sectionCard(
      'Significant events',
      '${_significant['note'] ?? ''}',
      entries.isEmpty
          ? const [Text('No event met the significance threshold.',
              style: TextStyle(fontSize: 12.5))]
          : [
              for (final event in entries)
                Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('${event['timestamp'] ?? 'time not recorded by source'}  |  '
                         '${_kindLabels['${event['kind']}'] ?? event['kind']}',
                        style: const TextStyle(fontSize: 11)),
                    SelectableText('${event['title']}',
                        style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
                  ]),
                ),
            ],
    );
  }

  Map<String, dynamic> get _triageCounts {
    final triage = _report['triage'];
    final counts = triage is Map ? triage['counts'] : null;
    return counts is Map<String, dynamic> ? counts : const {};
  }
  List<dynamic> get _unavailableTelemetry => _report['unavailable_telemetry'] as List? ?? const [];

  Widget _summaryRow(String label, String value, {Color? color}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 260, child: Text(label, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 12.5))),
          Expanded(child: SelectableText(value, style: TextStyle(fontSize: 12.5, color: color))),
        ]),
      );

  /// Sources the investigator may add to this collection.
  ///
  /// The engine is asked what it can collect rather than the client listing
  /// sources itself: a client that hardcodes the list offers collectors the
  /// engine does not have, and hides ones it gained.
  Widget _additionalSources() {
    final available = ref.watch(collectionSourcesProvider);
    return available.when(
      loading: () => const SizedBox.shrink(),
      error: (_, _) => const SizedBox.shrink(),
      data: (sources) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Additional evidence sources', style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 4),
          const Text(
            'Each runs as its own step. A source that is unavailable on this machine becomes '
            'a named gap in the report, not a failed collection.',
            style: TextStyle(fontSize: 12),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final source in sources)
                FilterChip(
                  key: Key('source-${source.source}'),
                  label: Text(source.source),
                  tooltip: source.description,
                  selected: _sources.contains(source.source),
                  onSelected: (selected) => setState(() {
                    if (selected) {
                      _sources.add(source.source);
                    } else {
                      _sources.remove(source.source);
                    }
                  }),
                ),
            ],
          ),
          if (_sources.contains('MEMORY')) ...[
            const SizedBox(height: 12),
            TextField(
              key: const Key('memory-image-path'),
              controller: _memoryImage,
              onChanged: (_) => setState(() {}),
              decoration: const InputDecoration(
                labelText: 'Memory image to analyse (absolute path)',
                helperText: 'JOCKY analyses an image you supply. It does not acquire memory, '
                    'and it never writes to the image or executes anything from it.',
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _collectionSummary() {
    if (_reports.isEmpty) {
      return const Card(child: Padding(padding: EdgeInsets.all(16),
        child: Text('No report has been issued yet. The summary appears once collection finishes.')));
    }
    final available = _history['telemetry_available'] == true;
    final window = _report['collection_window'];
    final snapshot = _report['current_process_snapshot'];
    final statistics = snapshot is Map ? snapshot['statistics'] : null;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Collection summary', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 10),
          _summaryRow('Historical execution telemetry:', available ? 'AVAILABLE' : 'NOT AVAILABLE',
              color: available ? Colors.green.shade700 : Colors.orange.shade800),
          if (!available)
            const Padding(padding: EdgeInsets.only(top: 4, bottom: 4), child: SelectableText(
              'No historical execution source could be read on this host. This investigation records what '
              'was running at collection time and cannot establish what ran before it.',
              style: TextStyle(fontSize: 12.5))),
          _summaryRow('Collection window:', window is Map
              ? '${window['start']}  →  ${window['end']}'
              : 'not recorded'),
          // Named for what each number is. One blurred "events" total invited
          // typed commands to be read as confirmed execution.
          _summaryRow('Execution-source records:', '${_counts['execution_source_records'] ?? 0}'),
          _summaryRow('Command-history records:', '${_counts['command_history_records'] ?? 0}'
              ' (execution not established by these)'),
          _summaryRow('Session records:', '${_counts['session_records'] ?? 0}'),
          if ((_history['undated_event_count'] ?? 0) != 0)
            _summaryRow('Records with no timestamp:', '${_history['undated_event_count']}'),
          const SizedBox(height: 6),
          for (final category in _triageOrder)
            _summaryRow('${_triageLabels[category]}:', '${_triageCounts[category] ?? 0} records',
                color: _triageColor(category)),
          const SizedBox(height: 6),
          _summaryRow('Artifacts:', '${_artifacts.length}'),
          _summaryRow('Findings:', '${_findings.length}'),
          _summaryRow('Collection limitations:', '${_limitations.length}'),
          _summaryRow('Unavailable telemetry sources:', '${_unavailableTelemetry.length}'),
          _summaryRow('Current processes recorded:', statistics is Map
              ? '${statistics['processes_recorded']} of ${statistics['processes_present']} present'
              : 'not recorded'),
          const SizedBox(height: 10),
          const SelectableText(
            'CURRENT OBSERVATION describes the moment of collection. HISTORICAL EVIDENCE comes from a '
            'source that recorded the past. INFERRED findings are triage for review, never verdicts. '
            'UNAVAILABLE marks what could not be read.',
            style: TextStyle(fontSize: 12)),
        ]),
      ),
    );
  }

  static const _triageLabels = {
    'POTENTIALLY_HARMFUL': 'POTENTIALLY HARMFUL',
    'NEEDS_REVIEW': 'NOT SURE / NEEDS REVIEW',
    'NOT_HARMFUL_ON_AVAILABLE_EVIDENCE': 'NOT HARMFUL ON AVAILABLE EVIDENCE',
  };
  static const _triageOrder = ['POTENTIALLY_HARMFUL', 'NEEDS_REVIEW', 'NOT_HARMFUL_ON_AVAILABLE_EVIDENCE'];
  static const _priorityLabels = {
    'PRIORITY_1': 'Priority 1 — investigate first',
    'PRIORITY_2': 'Priority 2 — review',
    'PRIORITY_3': 'Priority 3 — informational',
  };
  static const _priorityOrder = ['PRIORITY_1', 'PRIORITY_2', 'PRIORITY_3'];
  static const _kindLabels = {
    'EXECUTION_EVIDENCE': 'EXECUTION EVIDENCE',
    'COMMAND_HISTORY': 'COMMAND HISTORY',
    'SESSION_EVENT': 'SESSION EVENT',
  };

  Color _triageColor(String? category) => switch (category) {
        'POTENTIALLY_HARMFUL' => Colors.red.shade700,
        'NEEDS_REVIEW' => Colors.orange.shade800,
        'NOT_HARMFUL_ON_AVAILABLE_EVIDENCE' => Colors.green.shade700,
        _ => Colors.grey.shade600,
      };

  Color _priorityColor(String? priority) => switch (priority) {
        'PRIORITY_1' => Colors.red.shade700,
        'PRIORITY_2' => Colors.orange.shade800,
        'PRIORITY_3' => Colors.blueGrey.shade400,
        _ => Colors.grey.shade600,
      };

  /// Records matching the search box and the triage filter.
  ///
  /// Search runs over the whole command, its search form, the executable, the
  /// source and the evidence reference — never the executable alone, so
  /// searching "github.com" or "holehe" finds the records that contain them.
  List<dynamic> get _filteredActivity {
    final needle = _activitySearch.text.trim().toLowerCase();
    final rows = _executionEvents.where((row) {
      final priority = '${row['investigator_priority']}';
      if (_priorityFilter == 'leads' &&
          !(priority == 'PRIORITY_1' || priority == 'PRIORITY_2')) {
        return false;
      }
      if (_priorityFilter != 'all' && _priorityFilter != 'leads' &&
          priority != _priorityFilter) {
        return false;
      }
      if (_triageFilter != 'all' && row['triage'] != _triageFilter) return false;
      if (_presentationFilter != 'all' && _presentationOf(row) != _presentationFilter) {
        return false;
      }
      if (needle.isEmpty) return true;
      // Recognized software is searchable by name even though the name appears
      // in no command line: "python3-minimal" is what the package manager calls
      // it, and it is what an investigator will type.
      final haystack = [
        row['full_command_line'], row['normalized_command'], row['executable'],
        row['process_name'], row['source'], row['reference'], row['account'], row['evidence_kind'],
        row['recognized_name'],
      ].where((value) => value != null).join(' ').toLowerCase();
      return haystack.contains(needle);
    }).toList();
    // Highest priority first, then the strongest score, then most recent.
    int rank(dynamic row) {
      final index = _priorityOrder.indexOf('${row['investigator_priority']}');
      return index < 0 ? 99 : index;
    }

    rows.sort((a, b) {
      final byPriority = rank(a).compareTo(rank(b));
      if (byPriority != 0) return byPriority;
      final byScore =
          ((b['priority_score'] ?? 0) as num).compareTo((a['priority_score'] ?? 0) as num);
      if (byScore != 0) return byScore;
      return '${b['timestamp'] ?? ''}'.compareTo('${a['timestamp'] ?? ''}');
    });
    return rows;
  }

  /// Full evidence. Keyed so tests can address this list rather than the
  /// summary cards above, which deliberately repeat some of the same commands.
  Widget _activityPanel() {
    final rows = _filteredActivity;
    final counts = <String, int>{};
    final priorityCounts = <String, int>{};
    final presentationCounts = <String, int>{};
    for (final row in _executionEvents) {
      counts['${row['triage']}'] = (counts['${row['triage']}'] ?? 0) + 1;
      final priority = '${row['investigator_priority']}';
      priorityCounts[priority] = (priorityCounts[priority] ?? 0) + 1;
      final presentation = _presentationOf(row);
      presentationCounts[presentation] = (presentationCounts[presentation] ?? 0) + 1;
    }
    final leadCount =
        (priorityCounts['PRIORITY_1'] ?? 0) + (priorityCounts['PRIORITY_2'] ?? 0);
    return Card(
      key: const Key('activity-panel'),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Observed activity', style: Theme.of(context).textTheme.titleMedium),
          const SelectableText(
            'Triage categories, not verdicts. "Not harmful on available evidence" means nothing in '
            'what was collected stood out — it is not a statement that the activity was safe.',
            style: TextStyle(fontSize: 12)),
          const SizedBox(height: 12),
          // Wraps rather than overflowing: three controls do not fit on one
          // line at a narrow window width.
          Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center,
               children: [
            ConstrainedBox(
              constraints: const BoxConstraints(minWidth: 260, maxWidth: 460),
              child: TextField(
                controller: _activitySearch,
                onChanged: (_) => setState(() {}),
                decoration: const InputDecoration(
                  labelText: 'Search commands, URLs, paths, users, sources or evidence IDs',
                  prefixIcon: Icon(Icons.search), isDense: true),
              ),
            ),
            DropdownButton<String>(
              value: _priorityFilter,
              items: [
                DropdownMenuItem(
                  value: 'leads',
                  child: Text('Leads — priority 1 and 2 ($leadCount)',
                      style: const TextStyle(fontSize: 12)),
                ),
                for (final priority in _priorityOrder)
                  DropdownMenuItem(
                    value: priority,
                    child: Text('${_priorityLabels[priority]} (${priorityCounts[priority] ?? 0})',
                        style: const TextStyle(fontSize: 12)),
                  ),
                const DropdownMenuItem(value: 'all', child: Text('All evidence')),
              ],
              onChanged: (value) => setState(() => _priorityFilter = value ?? 'leads'),
            ),
            DropdownButton<String>(
              value: _presentationFilter,
              items: [
                const DropdownMenuItem(
                    value: 'all', child: Text('Any presentation', style: TextStyle(fontSize: 12))),
                for (final entry in _presentationLabels.entries)
                  DropdownMenuItem(
                    value: entry.key,
                    child: Text('${entry.value} (${presentationCounts[entry.key] ?? 0})',
                        style: const TextStyle(fontSize: 12)),
                  ),
              ],
              onChanged: (value) => setState(() => _presentationFilter = value ?? 'all'),
            ),
            DropdownButton<String>(
              value: _triageFilter,
              items: [
                const DropdownMenuItem(value: 'all', child: Text('Any classification')),
                for (final category in _triageOrder)
                  DropdownMenuItem(
                    value: category,
                    child: Text('${_triageLabels[category]} (${counts[category] ?? 0})',
                        style: const TextStyle(fontSize: 12)),
                  ),
              ],
              onChanged: (value) => setState(() => _triageFilter = value ?? 'all'),
            ),
          ]),
          const SizedBox(height: 8),
          Text('${rows.length} of ${_executionEvents.length} records'
               '${_priorityFilter == 'leads' ? ' — showing leads only; choose "All evidence" for everything' : ''}',
              style: const TextStyle(fontSize: 12)),
          const SizedBox(height: 8),
          if (rows.isEmpty)
            const Padding(padding: EdgeInsets.all(16),
              child: Text('No activity records match.'))
          else
            for (final row in rows.take(200)) _activityRow(row),
          if (rows.length > 200)
            Padding(padding: const EdgeInsets.only(top: 8), child: Text(
              '${rows.length - 200} further records are not shown here. Narrow the search, or read '
              'them in the report appendices and the JSON export.',
              style: const TextStyle(fontSize: 12))),
        ]),
      ),
    );
  }

  Widget _activityRow(dynamic row) {
    final reference = '${row['reference'] ?? row['id']}';
    final confirmed = row['execution_confirmed'] == true;
    final command = row['full_command_line'] as String?;
    final kind = '${row['evidence_kind']}';
    final open = _expanded.contains(reference);
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        border: Border(
          left: BorderSide(color: _priorityColor('${row['investigator_priority']}'), width: 3)),
        color: Theme.of(context).colorScheme.surfaceContainerHighest.withValues(alpha: 0.25),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 10, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
          Text(_priorityLabels['${row['investigator_priority']}'] ?? 'UNPRIORITISED',
              style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700,
                  color: _priorityColor('${row['investigator_priority']}'))),
          Text(_triageLabels['${row['triage']}'] ?? 'UNCLASSIFIED',
              style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600,
                  color: _triageColor('${row['triage']}'))),
          Text('${row['timestamp'] ?? 'time not recorded by source'}',
              style: const TextStyle(fontSize: 11.5)),
          Text(reference, style: const TextStyle(fontSize: 11, fontFamily: 'monospace')),
          if (row['recognized_name'] != null)
            Tooltip(
              message: 'Accounted for by the machine\'s own records. Recognition says what '
                  'something is, not that it is safe.',
              child: Text('RECOGNIZED: ${row['recognized_name']}',
                  style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600,
                      color: JockyColors.textMuted)),
            ),
        ]),
        const SizedBox(height: 4),
        // The command exactly as its source recorded it, never shortened to the
        // executable.
        SelectableText(
          command ?? '${row['executable'] ?? row['process_name'] ?? 'unnamed process'}',
          style: const TextStyle(fontFamily: 'monospace', fontSize: 12.5)),
        if (command == null)
          Text('Full command line: not available from collected evidence '
               '(${row['command_reconstruction_status'] ?? 'NOT_AVAILABLE'})',
              style: const TextStyle(fontSize: 11.5)),
        const SizedBox(height: 4),
        Text('${_kindLabels[kind] ?? kind}  |  '
             '${confirmed ? 'execution confirmed by the source' : 'execution NOT established'}'
             '  |  command ${row['command_reconstruction_status'] ?? 'NOT_AVAILABLE'}'
             '/${row['command_evidence_strength'] ?? 'n/a'}  |  ${row['source']}',
            style: const TextStyle(fontSize: 11.5)),
        Wrap(spacing: 4, children: [
          TextButton(
            onPressed: () => setState(() => open ? _expanded.remove(reference) : _expanded.add(reference)),
            child: Text(open ? 'Hide details' : 'Details'),
          ),
          TextButton.icon(
            key: Key('brief-$reference'),
            onPressed: () => _openBrief('activity', reference),
            icon: const Icon(Icons.description_outlined, size: 15),
            label: const Text('Review brief'),
          ),
        ]),
        if (open) Padding(padding: const EdgeInsets.only(left: 8, bottom: 8), child: _json(row['payload'])),
      ]),
    );
  }

  /// Fetch and show a review brief for one subject.
  ///
  /// The brief is generated by the engine from stored evidence; the client
  /// renders it and offers the PDF. Nothing is recomputed here, and nothing is
  /// collected again.
  Future<void> _openBrief(String subjectType, String subjectId) async {
    final caseId = widget.caseId;
    if (caseId == null) return;
    setState(() => _notice = null);
    try {
      final brief = await ref.read(apiClientProvider).jsonRequest(
        '/api/v1/investigations/$caseId/briefs',
        body: {'subject_type': subjectType, 'subject_id': subjectId});
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (context) => _BriefDialog(
          brief: brief,
          onExport: () => _exportBrief(subjectType, subjectId),
        ),
      );
    } on Object catch (error) {
      if (mounted) setState(() => _error = '$error');
    }
  }

  Future<void> _exportBrief(String subjectType, String subjectId) async {
    final caseId = widget.caseId;
    if (caseId == null) return;
    final path = await ref.read(fileSelectionProvider).pickSaveLocation(
      suggestedName: 'JOCKY_ReviewBrief_$subjectId.pdf', extension: 'pdf');
    if (path == null) return;
    try {
      final response = await ref.read(apiClientProvider).request(
        '/api/v1/investigations/$caseId/briefs/export',
        body: {'subject_type': subjectType, 'subject_id': subjectId});
      await File(path).writeAsBytes(response.bodyBytes);
      if (mounted) setState(() => _notice = 'Review brief written to $path');
    } on Object catch (error) {
      if (mounted) setState(() => _error = '$error');
    }
  }

  Future<void> _exportRoutine({bool detailed = false}) async {
    final caseId = widget.caseId;
    if (caseId == null) return;
    final path = await ref.read(fileSelectionProvider).pickSaveLocation(
      suggestedName: 'jocky-routine-$caseId.pdf', extension: 'pdf');
    if (path == null) return;
    try {
      final response = await ref.read(apiClientProvider).request(
        '/api/v1/investigations/$caseId/routine/export', body: {'detailed': detailed});
      await File(path).writeAsBytes(response.bodyBytes);
      if (mounted) {
        setState(() => _notice = 'Routine activity report written to $path. It describes activity '
            'that raised no concern signal; it is not a guarantee of safety.');
      }
    } on Object catch (error) {
      if (mounted) setState(() => _error = '$error');
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
        const Text('System information, current processes and historical execution evidence are collected. Add file sources explicitly; no whole-disk scan is performed. Up to 20 sources, files up to 128 MiB.'),
        const SizedBox(height: 12),
        Row(children: [
          SizedBox(width: 220, child: TextField(controller: _windowHours, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'History window (hours)', helperText: 'Bounded; 2160 hours maximum'))),
        ]),
        const SizedBox(height: 8),
        CheckboxListTile(
          value: _includeCommandLines,
          onChanged: (value) => setState(() => _includeCommandLines = value ?? false),
          controlAffinity: ListTileControlAffinity.leading,
          contentPadding: EdgeInsets.zero,
          title: const Text('Collect command-line arguments'),
          subtitle: const Text('Off by default. Command lines frequently contain passwords and tokens. When enabled, values matching common credential patterns are masked before storage — a mitigation, not a guarantee.'),
        ),
        const SizedBox(height: 16),
        _additionalSources(),
        const SizedBox(height: 8),
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
          // Deliberately a separate document. The investigator report stays
          // about what needs attention; everything the machine accounted for
          // goes here, grouped, so it can be put on the record without being
          // read line by line.
          if (_reports.isNotEmpty)
            OutlinedButton.icon(
              key: const Key('export-routine-pdf'),
              onPressed: _busy ? null : () => _exportRoutine(),
              icon: const Icon(Icons.inventory_2_outlined, size: 16),
              label: const Text('Routine activity PDF'),
            ),
          if (_case != null && !terminal.contains(_case!['status']) && _case!['status'] != 'created') OutlinedButton(onPressed: () async { await ref.read(apiClientProvider).jsonRequest('/api/v1/investigations/${widget.caseId}/cancel', body: {}); if (mounted) setState(() => _notice = 'Cancellation requested; the current bounded step may finish first.'); }, child: const Text('Cancel collection')),
          TextButton(onPressed: () => context.go('/device'), child: const Text('All investigations')),
        ]),
        if (!terminal.contains(_case?['status'])) const Padding(padding: EdgeInsets.all(16), child: Text('Preparing → Collecting → Analyzing → Finalizing. Exact progress is unavailable; stages reflect persisted backend state.')),
        // Investigator summary first: the conclusion, then the leads, threads
        // and significant events. Full evidence sits below and is never hidden.
        _collectionSummary(),
        const SizedBox(height: 16),
        _leadsCard(),
        const SizedBox(height: 16),
        _threadsCard(),
        const SizedBox(height: 16),
        _significantEventsCard(),
        const SizedBox(height: 16),
        _activityPanel(),
        _section('Device information', _case?['device']),
        _section('Investigation context', _case),
        _section('Historical execution — HISTORICAL EVIDENCE (${_executionEvents.length})', _executionEvents),
        _section('Event timeline — ordered by recorded time (${_eventTimeline.length})', _eventTimeline),
        _section('Artifacts — observed files (${_artifacts.length})', _artifacts),
        _section('Findings — INFERRED; requires review (${_findings.length})', _findings),
        _section('Collection limitations (${_limitations.length})', _limitations),
        _section('Unavailable telemetry (${_unavailableTelemetry.length})', _unavailableTelemetry),
        _section('Investigation state history', _timeline),
        _section('Processes — CURRENT OBSERVATION', _evidence.where((e) => e['type'] == 'PROCESSES').toList()),
        _section('Files, hashes, indicators and integrity', _evidence.where((e) => e['type'] == 'FILES').toList()),
        _section('Evidence references', _evidence),
        _section('Reports', _reports),
      ],
    ]);
  }
}


/// A review brief, rendered as the investigator reads it.
///
/// Deliberately the same sections in the same order as the PDF: someone who
/// reads one on screen and hands the other to a colleague should be looking at
/// the same document.
class _BriefDialog extends StatelessWidget {
  const _BriefDialog({required this.brief, required this.onExport});

  final Map<String, dynamic> brief;
  final VoidCallback onExport;

  @override
  Widget build(BuildContext context) {
    final subject = brief['subject'] as Map<String, dynamic>? ?? const {};
    final execution = brief['execution'] as Map<String, dynamic>? ?? const {};
    final recognition = brief['recognition'] as Map<String, dynamic>? ?? const {};
    final sections = (brief['sections'] as List? ?? const []).whereType<Map>();

    Widget heading(String text) => Padding(
          padding: const EdgeInsets.only(top: 14, bottom: 4),
          child: Text(text, style: const TextStyle(
              fontSize: 12, fontWeight: FontWeight.w700, color: JockyColors.accent)),
        );
    Widget line(String text, {bool mono = false}) => Padding(
          padding: const EdgeInsets.only(bottom: 3),
          child: SelectableText(text, style: TextStyle(
              fontSize: mono ? 11.5 : 12.5,
              fontFamily: mono ? 'monospace' : null)),
        );

    return AlertDialog(
      key: const Key('review-brief'),
      title: Text('Review brief — ${subject['id']}'),
      content: SizedBox(
        width: 720,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              line('${subject['label'] ?? subject['id']}', mono: true),
              heading('Status'),
              line('Classification: ${brief['classification'] ?? 'not classified'}'),
              if (brief['presentation'] != null) line('Presentation: ${brief['presentation']}'),
              line('Priority: ${brief['priority'] ?? 'not ranked'}'),
              line('Execution: ${execution['state']} — ${execution['detail']}'),
              line('Recognition: ${recognition['state']} — ${recognition['detail']}'),
              heading('Summary'),
              line('${brief['summary'] ?? ''}'),
              heading('Why this was surfaced'),
              line('${brief['why_surfaced'] ?? 'Not stated.'}'),
              for (final section in sections) ...[
                heading('${section['title']}'),
                for (final entry in (section['body'] as List? ?? const []).take(12))
                  line('$entry', mono: true),
              ],
              heading('What is known'),
              for (final entry in brief['known'] as List? ?? const []) line('— $entry'),
              heading('What is unknown'),
              for (final entry in brief['unknown'] as List? ?? const []) line('— $entry'),
              if ((brief['collection_limitations'] as List? ?? const []).isNotEmpty) ...[
                heading('Collection limitations'),
                for (final entry in brief['collection_limitations'] as List) line('— $entry'),
              ],
              heading('Suggested investigator review'),
              for (final entry in brief['suggested_review'] as List? ?? const []) line('— $entry'),
              heading('Evidence cited'),
              line((brief['evidence_ids'] as List? ?? const []).join(', '), mono: true),
              const SizedBox(height: 14),
              SelectableText('${brief['disclaimer'] ?? ''}',
                  style: const TextStyle(fontSize: 11.5, color: JockyColors.textMuted)),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Close')),
        FilledButton.icon(
          key: const Key('export-brief'),
          onPressed: () {
            Navigator.of(context).pop();
            onExport();
          },
          icon: const Icon(Icons.picture_as_pdf_outlined, size: 16),
          label: const Text('Export PDF'),
        ),
      ],
    );
  }
}
