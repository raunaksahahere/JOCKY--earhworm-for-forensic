import 'package:file_selector/file_selector.dart';

/// Native desktop file and directory selection.
///
/// Paths are passed to the engine exactly as the platform returned them:
/// no normalisation, no separator rewriting, no case folding. The command
/// contract states backslashes are literal and paths are not resolved during
/// parsing, so any client-side "tidying" would change the evidence identity.
abstract class FileSelectionService {
  Future<String?> pickFile({String? confirmButtonText});
  Future<String?> pickDirectory({String? confirmButtonText});
  Future<String?> pickSaveLocation({
    required String suggestedName,
    required String extension,
  });
}

class NativeFileSelectionService implements FileSelectionService {
  const NativeFileSelectionService();

  @override
  Future<String?> pickFile({String? confirmButtonText}) async {
    final file = await openFile(confirmButtonText: confirmButtonText ?? 'Select evidence');
    return file?.path;
  }

  @override
  Future<String?> pickDirectory({String? confirmButtonText}) =>
      getDirectoryPath(confirmButtonText: confirmButtonText ?? 'Select location');

  @override
  Future<String?> pickSaveLocation({
    required String suggestedName,
    required String extension,
  }) async {
    final location = await getSaveLocation(
      suggestedName: suggestedName,
      acceptedTypeGroups: [
        XTypeGroup(label: extension.toUpperCase(), extensions: [extension]),
      ],
    );
    if (location == null) return null;
    final path = location.path;
    return path.toLowerCase().endsWith('.$extension') ? path : '$path.$extension';
  }
}
