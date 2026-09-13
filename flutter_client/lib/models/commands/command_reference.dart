import '../../core/utils/json.dart';

/// One entry of `GET /commands`. The grammar is owned by the backend; this is
/// the only syntax source the client is allowed to show.
class CommandReferenceEntry {
  const CommandReferenceEntry({
    required this.name,
    required this.syntax,
    required this.example,
    required this.description,
    required this.category,
  });

  final String name;
  final String syntax;
  final String example;
  final String description;
  final String category;

  factory CommandReferenceEntry.fromJson(Map<String, dynamic> json) =>
      CommandReferenceEntry(
        name: asString(json['name']),
        syntax: asString(json['syntax']),
        example: asString(json['example']),
        description: asString(json['description']),
        category: asString(json['category'], fallback: 'other'),
      );
}

class CommandReference {
  const CommandReference({required this.schemaVersion, required this.entries});

  final int? schemaVersion;
  final List<CommandReferenceEntry> entries;

  factory CommandReference.fromJson(Map<String, dynamic> json) => CommandReference(
        schemaVersion: asIntOrNull(json['schema_version']),
        entries: asMapList(json['commands'])
            .map(CommandReferenceEntry.fromJson)
            .toList(growable: false),
      );

  static const empty = CommandReference(schemaVersion: null, entries: []);
}
