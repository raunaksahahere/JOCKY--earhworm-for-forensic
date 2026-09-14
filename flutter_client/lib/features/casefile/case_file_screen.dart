import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/errors/failure.dart';
import '../../core/theme/tokens.dart';
import '../../core/utils/format.dart';
import '../../models/casework/casework_models.dart';
import '../../state/providers.dart';
import '../../widgets/data_grid.dart';
import '../../widgets/empty_state.dart';
import '../../widgets/failure_view.dart';
import '../../widgets/mono_value.dart';
import '../../widgets/panel.dart';
import '../../widgets/status_chip.dart';

/// The case file: cases, evidence sources, authorized endpoints and the audit
/// trail.
///
/// These four sit together because they answer one question between them —
/// what is this enquiry, what was it given to work with, where is it allowed to
/// look, and what has been done so far. They are kept in separate tabs because
/// conflating the audit trail with evidence is the mistake this whole design
/// exists to avoid: one records what the machine did, the other what JOCKY and
/// the investigator did.
class CaseFileScreen extends ConsumerStatefulWidget {
  const CaseFileScreen({super.key, this.initialTab = 0});

  final int initialTab;

  @override
  ConsumerState<CaseFileScreen> createState() => _CaseFileScreenState();
}

class _CaseFileScreenState extends ConsumerState<CaseFileScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabs =
      TabController(length: 4, vsync: this, initialIndex: widget.initialTab);
  String? _selectedCase;

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(
              JockySpace.lg, JockySpace.lg, JockySpace.lg, JockySpace.sm),
          child: Row(
            children: [
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Case File',
                        style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600)),
                    SizedBox(height: 2),
                    Text('Enquiries, the evidence they were given, the machines they may '
                        'collect from, and the record of what was done.',
                        style: TextStyle(fontSize: 12, color: JockyColors.textMuted)),
                  ],
                ),
              ),
              if (_selectedCase != null)
                Padding(
                  padding: const EdgeInsets.only(left: JockySpace.md),
                  child: InputChip(
                    label: Text('Scoped to $_selectedCase'),
                    onDeleted: () => setState(() => _selectedCase = null),
                  ),
                ),
            ],
          ),
        ),
        TabBar(
          controller: _tabs,
          isScrollable: true,
          tabAlignment: TabAlignment.start,
          tabs: const [
            Tab(text: 'Cases', icon: Icon(Icons.folder_outlined, size: 16)),
            Tab(text: 'Evidence sources', icon: Icon(Icons.inventory_2_outlined, size: 16)),
            Tab(text: 'Endpoints', icon: Icon(Icons.devices_outlined, size: 16)),
            Tab(text: 'Audit trail', icon: Icon(Icons.fact_check_outlined, size: 16)),
          ],
        ),
        Expanded(
          child: TabBarView(
            controller: _tabs,
            children: [
              _CasesTab(
                selected: _selectedCase,
                onScope: (id) => setState(() => _selectedCase = id),
              ),
              _EvidenceTab(caseId: _selectedCase),
              const _EndpointsTab(),
              _AuditTab(caseId: _selectedCase),
            ],
          ),
        ),
      ],
    );
  }
}

/// One rendering for every listing on this screen.
///
/// The retry is passed in rather than derived: a failure here is usually an
/// engine that has not finished starting, and the investigator should be able
/// to ask again without losing the tab they were on.
Widget _async<T>(AsyncValue<T> value, Widget Function(T) build, {required VoidCallback onRetry}) {
  return value.when(
    data: build,
    loading: () => const Center(child: CircularProgressIndicator()),
    error: (error, _) => Padding(
      padding: const EdgeInsets.all(JockySpace.lg),
      child: FailureView(
        failure: error is JockyFailure
            ? error
            : JockyFailure(kind: FailureKind.execution, message: '$error'),
        onRetry: onRetry,
      ),
    ),
  );
}

// --- cases -------------------------------------------------------------------
class _CasesTab extends ConsumerWidget {
  const _CasesTab({required this.selected, required this.onScope});

  final String? selected;
  final ValueChanged<String> onScope;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cases = ref.watch(casesProvider);
    return Padding(
      padding: const EdgeInsets.all(JockySpace.lg),
      child: Panel(
        title: 'Cases',
        subtitle: 'An enquiry can hold several collections. An investigation '
            'without a case still works exactly as before.',
        actions: [
          FilledButton.icon(
            key: const Key('new-case'),
            onPressed: () => _openCreateDialog(context, ref),
            icon: const Icon(Icons.add, size: 16),
            label: const Text('New case'),
          ),
        ],
        padding: EdgeInsets.zero,
        child: _async(cases, (rows) {
          if (rows.isEmpty) {
            return const EmptyState(
              icon: Icons.folder_outlined,
              title: 'No cases yet',
              description: 'Open a case to hold the collections, evidence sources and '
                  'notes that belong to one enquiry.',
            );
          }
          return DataGrid<CaseRecord>(
            rows: rows,
            rowKey: (row) => row.id,
            selected: (row) => row.id == selected,
            onSelect: (row) => onScope(row.id),
            columns: [
              GridColumn(
                label: 'Case',
                width: 150,
                cell: (row) => MonoValue(row.id, copyable: true),
                sortValue: (row) => row.id,
              ),
              GridColumn(
                label: 'Title',
                flex: 3,
                cell: (row) => Text(row.title, overflow: TextOverflow.ellipsis),
                sortValue: (row) => row.title,
              ),
              GridColumn(
                label: 'Examiner',
                flex: 2,
                cell: (row) => Text(row.examiner ?? '—',
                    style: const TextStyle(color: JockyColors.textMuted)),
              ),
              GridColumn(
                label: 'Collections',
                width: 100,
                alignRight: true,
                cell: (row) => Text('${row.investigationCount}'),
                sortValue: (row) => row.investigationCount,
              ),
              GridColumn(
                label: 'Evidence',
                width: 90,
                alignRight: true,
                cell: (row) => Text('${row.evidenceSourceCount}'),
                sortValue: (row) => row.evidenceSourceCount,
              ),
              GridColumn(
                label: 'Status',
                width: 110,
                cell: (row) => StatusChip(
                  label: row.status,
                  tone: row.isOpen ? StatusTone.accent : StatusTone.neutral,
                ),
              ),
              GridColumn(
                label: 'Opened',
                width: 170,
                cell: (row) => MonoValue(formatIsoTimestamp(row.createdAt), fontSize: 11),
                sortValue: (row) => row.createdAt,
              ),
            ],
          );
        }, onRetry: () => ref.invalidate(casesProvider)),
      ),
    );
  }

  Future<void> _openCreateDialog(BuildContext context, WidgetRef ref) async {
    final created = await showDialog<bool>(
      context: context,
      builder: (context) => const _NewCaseDialog(),
    );
    if (created == true) ref.invalidate(casesProvider);
  }
}

class _NewCaseDialog extends ConsumerStatefulWidget {
  const _NewCaseDialog();

  @override
  ConsumerState<_NewCaseDialog> createState() => _NewCaseDialogState();
}

class _NewCaseDialogState extends ConsumerState<_NewCaseDialog> {
  final _title = TextEditingController();
  final _examiner = TextEditingController();
  final _reference = TextEditingController();
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    _title.dispose();
    _examiner.dispose();
    _reference.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(caseworkRepositoryProvider).createCase(
            title: _title.text.trim(),
            examiner: _examiner.text.trim(),
            reference: _reference.text.trim(),
          );
      if (mounted) Navigator.of(context).pop(true);
    } on JockyFailure catch (failure) {
      setState(() {
        _error = failure.message;
        _busy = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Open a case'),
      content: SizedBox(
        width: 460,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(
              key: const Key('case-title'),
              controller: _title,
              autofocus: true,
              decoration: const InputDecoration(labelText: 'Title'),
            ),
            const SizedBox(height: JockySpace.md),
            TextField(
              controller: _examiner,
              decoration: const InputDecoration(
                labelText: 'Examiner',
                helperText: 'Recorded with the case; it is not an identity JOCKY verifies.',
              ),
            ),
            const SizedBox(height: JockySpace.md),
            TextField(
              controller: _reference,
              decoration: const InputDecoration(
                labelText: 'Reference',
                helperText: 'Your own case or ticket number.',
              ),
            ),
            if (_error != null) ...[
              const SizedBox(height: JockySpace.md),
              Text(_error!, style: const TextStyle(color: JockyColors.danger, fontSize: 12)),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
        FilledButton(
          onPressed: _busy || _title.text.trim().isEmpty ? null : _submit,
          child: Text(_busy ? 'Opening…' : 'Open case'),
        ),
      ],
    );
  }
}

// --- evidence sources --------------------------------------------------------
class _EvidenceTab extends ConsumerWidget {
  const _EvidenceTab({this.caseId});

  final String? caseId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final provider = evidenceSourcesProvider(caseId);
    final sources = ref.watch(provider);
    return Padding(
      padding: const EdgeInsets.all(JockySpace.lg),
      child: Panel(
        title: 'Evidence sources',
        subtitle: 'Registered and hashed in place. JOCKY never writes to an evidence '
            'source, and registering the same bytes again records a further '
            'acquisition rather than replacing the first.',
        actions: [
          FilledButton.icon(
            key: const Key('register-evidence'),
            onPressed: () => _register(context, ref),
            icon: const Icon(Icons.add, size: 16),
            label: const Text('Register source'),
          ),
        ],
        padding: EdgeInsets.zero,
        child: _async(sources, (rows) {
          if (rows.isEmpty) {
            return const EmptyState(
              icon: Icons.inventory_2_outlined,
              title: 'No evidence sources registered',
              description: 'Register a disk image, log export or any other file so its '
                  'digest and provenance are recorded before anything acts on it.',
            );
          }
          return DataGrid<EvidenceSource>(
            rows: rows,
            rowKey: (row) => row.id,
            minWidth: 980,
            columns: [
              GridColumn(
                label: 'Source',
                width: 140,
                cell: (row) => MonoValue(row.id, copyable: true),
              ),
              GridColumn(
                label: 'Path',
                flex: 3,
                cell: (row) => MonoValue(row.originalPath ?? '—', fontSize: 11),
              ),
              GridColumn(
                label: 'SHA-256',
                width: 150,
                cell: (row) => MonoValue(
                  row.sha256 == null ? 'not hashed' : '${row.sha256!.substring(0, 16)}…',
                  fontSize: 11,
                  color: row.sha256 == null ? JockyColors.textMuted : JockyColors.text,
                ),
              ),
              GridColumn(
                label: 'Integrity',
                width: 140,
                cell: (row) => StatusChip(
                  label: row.verificationState,
                  tone: switch (row.verificationState) {
                    'VERIFIED' => StatusTone.ok,
                    'MISMATCH' => StatusTone.danger,
                    'MISSING' => StatusTone.warn,
                    _ => StatusTone.neutral,
                  },
                ),
              ),
              GridColumn(
                label: 'Supersedes',
                width: 130,
                cell: (row) => MonoValue(row.supersedes ?? '—', fontSize: 11),
              ),
              GridColumn(
                label: '',
                width: 96,
                cell: (row) => TextButton(
                  onPressed: () async {
                    await ref.read(caseworkRepositoryProvider).verifyEvidence(row.id);
                    ref.invalidate(provider);
                  },
                  child: const Text('Verify'),
                ),
              ),
            ],
          );
        }, onRetry: () => ref.invalidate(provider)),
      ),
    );
  }

  Future<void> _register(BuildContext context, WidgetRef ref) async {
    final registered = await showDialog<bool>(
      context: context,
      builder: (context) => _RegisterEvidenceDialog(caseId: caseId),
    );
    if (registered == true) ref.invalidate(evidenceSourcesProvider(caseId));
  }
}

class _RegisterEvidenceDialog extends ConsumerStatefulWidget {
  const _RegisterEvidenceDialog({this.caseId});

  final String? caseId;

  @override
  ConsumerState<_RegisterEvidenceDialog> createState() => _RegisterEvidenceDialogState();
}

class _RegisterEvidenceDialogState extends ConsumerState<_RegisterEvidenceDialog> {
  final _path = TextEditingController();
  final _description = TextEditingController();
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    _path.dispose();
    _description.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(caseworkRepositoryProvider).registerEvidence(
            path: _path.text.trim(),
            caseId: widget.caseId,
            description: _description.text.trim(),
          );
      if (mounted) Navigator.of(context).pop(true);
    } on JockyFailure catch (failure) {
      setState(() {
        _error = failure.message;
        _busy = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Register an evidence source'),
      content: SizedBox(
        width: 520,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(
              key: const Key('evidence-path'),
              controller: _path,
              autofocus: true,
              decoration: const InputDecoration(
                labelText: 'Absolute path',
                helperText: 'The file is read to compute its digest. It is never written to, '
                    'moved or renamed.',
              ),
            ),
            const SizedBox(height: JockySpace.md),
            TextField(
              controller: _description,
              decoration: const InputDecoration(labelText: 'Description'),
            ),
            if (_error != null) ...[
              const SizedBox(height: JockySpace.md),
              Text(_error!, style: const TextStyle(color: JockyColors.danger, fontSize: 12)),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
        FilledButton(
          onPressed: _busy ? null : _submit,
          child: Text(_busy ? 'Hashing…' : 'Register'),
        ),
      ],
    );
  }
}

// --- endpoints ---------------------------------------------------------------
class _EndpointsTab extends ConsumerWidget {
  const _EndpointsTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final endpoints = ref.watch(endpointsProvider);
    return Padding(
      padding: const EdgeInsets.all(JockySpace.lg),
      child: Panel(
        title: 'Authorized endpoints',
        subtitle: 'An endpoint receives named forensic collection requests and nothing '
            'else. There is no remote command, and health means only whether JOCKY '
            'has heard from the machine.',
        actions: [
          FilledButton.icon(
            key: const Key('authorize-endpoint'),
            onPressed: () => _authorize(context, ref),
            icon: const Icon(Icons.key_outlined, size: 16),
            label: const Text('Authorize endpoint'),
          ),
        ],
        padding: EdgeInsets.zero,
        child: _async(endpoints, (rows) {
          if (rows.isEmpty) {
            return const EmptyState(
              icon: Icons.devices_outlined,
              title: 'No endpoints authorized',
              description: 'Authorizing an endpoint issues a one-time token for one named '
                  'machine. Record the authority under which you may collect from it.',
            );
          }
          return DataGrid<EndpointRecord>(
            rows: rows,
            rowKey: (row) => row.id,
            minWidth: 1020,
            columns: [
              GridColumn(
                label: 'Endpoint',
                width: 140,
                cell: (row) => MonoValue(row.id, copyable: true),
              ),
              GridColumn(
                label: 'Name',
                flex: 2,
                cell: (row) => Text(row.name, overflow: TextOverflow.ellipsis),
                sortValue: (row) => row.name,
              ),
              GridColumn(
                label: 'Platform',
                width: 110,
                cell: (row) => Text(row.platform ?? '—',
                    style: const TextStyle(color: JockyColors.textMuted)),
              ),
              GridColumn(
                label: 'Contact',
                width: 130,
                cell: (row) => Tooltip(
                  message: row.healthDetail ?? '',
                  child: StatusChip(
                    label: row.healthState,
                    tone: switch (row.healthState) {
                      'healthy' => StatusTone.ok,
                      'stale' => StatusTone.warn,
                      'revoked' => StatusTone.danger,
                      _ => StatusTone.neutral,
                    },
                  ),
                ),
              ),
              GridColumn(
                label: 'Collectors',
                width: 100,
                alignRight: true,
                cell: (row) => Tooltip(
                  message: row.capabilities.join(', '),
                  child: Text('${row.capabilities.length}'),
                ),
              ),
              GridColumn(
                label: 'Authority',
                flex: 2,
                cell: (row) => Text(row.authorizationReference ?? '—',
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 11, color: JockyColors.textMuted)),
              ),
              GridColumn(
                label: '',
                width: 96,
                cell: (row) => row.isRevoked
                    ? const SizedBox.shrink()
                    : TextButton(
                        onPressed: () async {
                          await ref.read(caseworkRepositoryProvider).revokeEndpoint(row.id);
                          ref.invalidate(endpointsProvider);
                        },
                        child: const Text('Revoke'),
                      ),
              ),
            ],
          );
        }, onRetry: () => ref.invalidate(endpointsProvider)),
      ),
    );
  }

  Future<void> _authorize(BuildContext context, WidgetRef ref) async {
    final issued = await showDialog<bool>(
      context: context,
      builder: (context) => const _AuthorizeEndpointDialog(),
    );
    if (issued == true) ref.invalidate(endpointsProvider);
  }
}

class _AuthorizeEndpointDialog extends ConsumerStatefulWidget {
  const _AuthorizeEndpointDialog();

  @override
  ConsumerState<_AuthorizeEndpointDialog> createState() => _AuthorizeEndpointDialogState();
}

class _AuthorizeEndpointDialogState extends ConsumerState<_AuthorizeEndpointDialog> {
  final _name = TextEditingController();
  final _authority = TextEditingController();
  String? _error;
  Map<String, dynamic>? _issued;
  bool _busy = false;

  @override
  void dispose() {
    _name.dispose();
    _authority.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final issued = await ref.read(caseworkRepositoryProvider).authorizeEndpoint(
            name: _name.text.trim(),
            authorizationReference: _authority.text.trim(),
          );
      setState(() {
        _issued = issued;
        _busy = false;
      });
    } on JockyFailure catch (failure) {
      setState(() {
        _error = failure.message;
        _busy = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final issued = _issued;
    return AlertDialog(
      title: Text(issued == null ? 'Authorize an endpoint' : 'Enrollment token'),
      content: SizedBox(
        width: 560,
        child: issued == null ? _form() : _token(issued),
      ),
      actions: issued == null
          ? [
              TextButton(
                  onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
              FilledButton(
                onPressed: _busy ? null : _submit,
                child: Text(_busy ? 'Issuing…' : 'Issue token'),
              ),
            ]
          : [
              FilledButton(
                  onPressed: () => Navigator.of(context).pop(true), child: const Text('Done')),
            ],
    );
  }

  Widget _form() => Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextField(
            key: const Key('endpoint-name'),
            controller: _name,
            autofocus: true,
            decoration: const InputDecoration(
              labelText: 'Endpoint name',
              helperText: 'The name the agent will present when it enrolls.',
            ),
          ),
          const SizedBox(height: JockySpace.md),
          TextField(
            key: const Key('endpoint-authority'),
            controller: _authority,
            decoration: const InputDecoration(
              labelText: 'Authority for collecting from this machine',
              helperText: 'The warrant, ticket or written consent. Required, and kept with '
                  'the endpoint record.',
            ),
          ),
          if (_error != null) ...[
            const SizedBox(height: JockySpace.md),
            Text(_error!, style: const TextStyle(color: JockyColors.danger, fontSize: 12)),
          ],
        ],
      );

  Widget _token(Map<String, dynamic> issued) => Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text(
            'This token is shown once and cannot be recovered. It authorizes one machine '
            'to enroll and expires if unused.',
            style: TextStyle(fontSize: 12, color: JockyColors.textMuted),
          ),
          const SizedBox(height: JockySpace.md),
          MonoValue('${issued['enrollment_token']}', copyable: true, maxLines: 3, fontSize: 11),
          const SizedBox(height: JockySpace.md),
          const Text('Run on the endpoint:', style: TextStyle(fontSize: 12)),
          const SizedBox(height: JockySpace.xs),
          MonoValue(
            'jocky-endpoint --control-plane <url> --name ${issued['endpoint_name']} '
            '--enroll <token>',
            copyable: true,
            maxLines: 3,
            fontSize: 11,
          ),
          const SizedBox(height: JockySpace.md),
          Text('Expires ${formatIsoTimestamp('${issued['expires_at']}')}',
              style: const TextStyle(fontSize: 11, color: JockyColors.textMuted)),
        ],
      );
}

// --- audit trail --------------------------------------------------------------
class _AuditTab extends ConsumerWidget {
  const _AuditTab({this.caseId});

  final String? caseId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final provider = auditTrailProvider(caseId);
    final entries = ref.watch(provider);
    return Padding(
      padding: const EdgeInsets.all(JockySpace.lg),
      child: Panel(
        title: 'Audit trail',
        subtitle: 'What JOCKY and the investigator did. This is a record of the '
            'investigation, not evidence about the examined host.',
        actions: [
          IconButton(
            tooltip: 'Refresh',
            onPressed: () => ref.invalidate(provider),
            icon: const Icon(Icons.refresh, size: 18),
          ),
        ],
        padding: EdgeInsets.zero,
        child: _async(entries, (rows) {
          if (rows.isEmpty) {
            return const EmptyState(
              icon: Icons.fact_check_outlined,
              title: 'Nothing recorded yet',
              description: 'Every case opened, source registered, endpoint authorized and '
                  'collection run appears here.',
            );
          }
          return DataGrid<AuditEntry>(
            rows: rows,
            minWidth: 980,
            columns: [
              GridColumn(
                label: 'When',
                width: 175,
                cell: (row) => MonoValue(formatIsoTimestamp(row.timestamp), fontSize: 11),
                sortValue: (row) => row.timestamp,
              ),
              GridColumn(
                label: 'Action',
                flex: 2,
                cell: (row) => Text(row.action, style: const TextStyle(fontSize: 12)),
                sortValue: (row) => row.action,
              ),
              GridColumn(
                label: 'Object',
                flex: 2,
                cell: (row) => MonoValue(row.objectId ?? row.objectType ?? '—', fontSize: 11),
              ),
              GridColumn(
                label: 'Actor',
                flex: 2,
                cell: (row) => Text(row.actor,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 11, color: JockyColors.textMuted)),
              ),
              GridColumn(
                label: 'Outcome',
                width: 120,
                cell: (row) => StatusChip(
                  label: row.outcome,
                  tone: row.succeeded ? StatusTone.ok : StatusTone.danger,
                ),
              ),
            ],
          );
        }, onRetry: () => ref.invalidate(provider)),
      ),
    );
  }
}
