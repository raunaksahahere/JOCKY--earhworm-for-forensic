import '../services/api/jocky_api_client.dart';

/// A compiled JOCKY program: the IR, the plan for one platform, and the
/// engine's own rendering of both.
///
/// The client does not parse, validate or explain a program itself. Everything
/// here comes from the same compiler the engine runs a collection through, so
/// what the editor shows and what a collection executes cannot drift apart.
class CompiledProgram {
  const CompiledProgram({
    required this.ir,
    required this.plan,
    required this.explanation,
    required this.planExplanation,
  });

  factory CompiledProgram.fromJson(Map<String, dynamic> payload) => CompiledProgram(
        ir: (payload['ir'] as Map?)?.cast<String, dynamic>() ?? const {},
        plan: (payload['plan'] as Map?)?.cast<String, dynamic>() ?? const {},
        explanation: '${payload['explanation'] ?? ''}',
        planExplanation: '${payload['plan_explanation'] ?? ''}',
      );

  final Map<String, dynamic> ir;
  final Map<String, dynamic> plan;
  final String explanation;
  final String planExplanation;

  int get irVersion => (ir['ir_version'] as num?)?.toInt() ?? 0;
  int get planVersion => (plan['plan_version'] as num?)?.toInt() ?? 0;
  String get platform => '${plan['platform'] ?? 'unknown'}';
  bool get platformValidated => plan['platform_validated'] == true;
  int get readyTaskCount => (plan['ready_task_count'] as num?)?.toInt() ?? 0;

  List<Map<String, dynamic>> _rows(Map<String, dynamic> source, String key) =>
      (source[key] as List? ?? const [])
          .whereType<Map>()
          .map((row) => row.cast<String, dynamic>())
          .toList(growable: false);

  List<Map<String, dynamic>> get collections => _rows(ir, 'collections');
  List<Map<String, dynamic>> get tasks => _rows(plan, 'tasks');

  /// Sources this platform has no collector for.
  List<Map<String, dynamic>> get unsupported => _rows(plan, 'unsupported');

  /// Sources the program itself guarded away on this platform. Distinct from
  /// [unsupported]: the build could collect these, and the program chose not to.
  List<Map<String, dynamic>> get conditionalSkips => _rows(plan, 'conditional_skips');

  List<String> get playbooks =>
      (ir['playbooks'] as List? ?? const []).map((name) => '$name').toList(growable: false);
}

/// Compiles JOCKY programs through the engine's compiler.
class LanguageRepository {
  const LanguageRepository(this._client);

  final JockyApiClient _client;

  /// Compile and plan without collecting anything.
  Future<CompiledProgram> compile(String program, {String? platform}) async =>
      CompiledProgram.fromJson(await _client.jsonRequest('/api/v1/programs/compile', body: {
        'program': program,
        'platform': ?platform,
      }));

  /// Start a collection driven by the program itself.
  Future<String> run({
    required String program,
    required String title,
    String? caseId,
    int windowHours = 24,
  }) async {
    final investigation = await _client.jsonRequest('/api/v1/investigations', body: {
      'title': title,
      'case_id': ?caseId,
    });
    final id = '${investigation['id']}';
    await _client.jsonRequest('/api/v1/investigations/$id/collect', body: {
      'paths': const <String>[],
      'window_hours': windowHours,
      'program': program,
    });
    return id;
  }

  /// What this investigation's own FILTER statements selected.
  Future<Map<String, dynamic>> selection(String investigationId) async =>
      _client.jsonRequest('/api/v1/investigations/$investigationId/selection');
}
