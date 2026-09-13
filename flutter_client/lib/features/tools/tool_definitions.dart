/// Guided forms for the engine's existing actions.
///
/// A tool is only a form that produces command text. Submitting it goes through
/// the same execution controller, the same repository and the same
/// `POST /command` call as the Command Center — there is no second execution
/// path in this client.
///
/// Tools are matched to the engine's published reference by [referenceName], so
/// a command this backend build does not publish is never offered.
class ToolField {
  const ToolField({
    required this.key,
    required this.label,
    required this.hint,
    this.kind = ToolFieldKind.text,
    this.required = true,
  });

  final String key;
  final String label;
  final String hint;
  final ToolFieldKind kind;
  final bool required;
}

enum ToolFieldKind { text, filePath, directoryPath }

class ToolDefinition {
  const ToolDefinition({
    required this.referenceName,
    required this.title,
    required this.summary,
    required this.fields,
    required this.build,
    this.destructive = false,
    this.destructiveWarning,
  });

  /// Must match the `name` of an entry in `GET /commands`.
  final String referenceName;
  final String title;
  final String summary;
  final List<ToolField> fields;

  /// Builds the command line from field values.
  final String Function(Map<String, String> values) build;

  final bool destructive;
  final String? destructiveWarning;
}

/// Quotes a path only when it contains whitespace.
///
/// The command language has no escape sequences and treats backslashes as
/// literal, so a quote added anywhere else would change which file is named.
/// A path containing both quote characters is not representable in schema v1;
/// [quoteArgument] returns it unquoted so the engine's parser rejects it
/// explicitly instead of this client guessing.
String quoteArgument(String value) {
  if (!value.contains(' ') && !value.contains('\t')) return value;
  if (!value.contains('"')) return '"$value"';
  if (!value.contains("'")) return "'$value'";
  return value;
}

const toolDefinitions = <ToolDefinition>[
  ToolDefinition(
    referenceName: 'HASH',
    title: 'Hash a file',
    summary:
        'Computes a SHA-256 digest, runs a structural check, and compares the result against '
        'the engine\'s own prior observation of that exact path.',
    fields: [
      ToolField(
        key: 'path',
        label: 'Evidence file',
        hint: 'Select or type the full path',
        kind: ToolFieldKind.filePath,
      ),
    ],
    build: _buildHash,
  ),
  ToolDefinition(
    referenceName: 'LIST FILES',
    title: 'List a directory',
    summary:
        'Reads names, sizes and modification times for one directory level. Contents are never '
        'opened. Scanning stops at 20,000 entries and returns at most 500.',
    fields: [
      ToolField(
        key: 'path',
        label: 'Directory',
        hint: 'Select or type the directory path',
        kind: ToolFieldKind.directoryPath,
      ),
    ],
    build: _buildList,
  ),
  ToolDefinition(
    referenceName: 'SEARCH FILE',
    title: 'Search for a filename',
    summary:
        'Recursive, case-insensitive filename substring match. Scans at most 20,000 files and '
        'returns at most 200 matches.',
    fields: [
      ToolField(
        key: 'name',
        label: 'Name contains',
        hint: 'Substring to match, e.g. invoice',
      ),
      ToolField(
        key: 'directory',
        label: 'Search under',
        hint: 'Directory to search recursively',
        kind: ToolFieldKind.directoryPath,
      ),
    ],
    build: _buildSearch,
  ),
  ToolDefinition(
    referenceName: 'SYSTEM INFO',
    title: 'Observe the host',
    summary:
        'Collects read-only host facts: OS, processor, memory, volume usage, boot time and the '
        'engine\'s Python runtime.',
    fields: [],
    build: _buildSystemInfo,
  ),
  ToolDefinition(
    referenceName: 'PROCESSES',
    title: 'Observe running processes',
    summary:
        'A single read-only snapshot of the process table. Per-process CPU is always reported as '
        'unavailable: no sampling interval is taken.',
    fields: [],
    build: _buildProcesses,
  ),

];

String _buildHash(Map<String, String> values) =>
    'HASH FILE ${quoteArgument(values['path'] ?? '')}';

String _buildList(Map<String, String> values) =>
    'LIST FILES ${quoteArgument(values['path'] ?? '')}';

String _buildSearch(Map<String, String> values) =>
    'SEARCH FILE ${quoteArgument(values['name'] ?? '')} '
    'IN ${quoteArgument(values['directory'] ?? '')}';

String _buildSystemInfo(Map<String, String> values) => 'SYSTEM INFO';

String _buildProcesses(Map<String, String> values) => 'PROCESSES';
