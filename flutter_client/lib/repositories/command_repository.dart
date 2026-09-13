import '../core/errors/failure.dart';
import '../models/commands/command_reference.dart';
import '../models/commands/command_response.dart';
import '../services/api/jocky_api_client.dart';

/// Command submission and syntax reference.
///
/// The repository deliberately has no `validate` method: validation lives in
/// the Python parser, and adding a client-side pre-check here would create a
/// second, divergent authority over the command language.
class CommandRepository {
  const CommandRepository(this._api);

  final JockyApiClient _api;

  Future<CommandResponse> execute(
    String commandText, {
    Future<void>? cancellation,
    Duration? timeout,
  }) =>
      _api.executeCommand(commandText, cancellation: cancellation, timeout: timeout);

  Future<CommandReference> reference() => _api.commandReference();

  /// Returns the reference, or an empty one plus the failure, so the Command
  /// Center can still accept input when only the reference call failed.
  Future<(CommandReference, JockyFailure?)> referenceOrFailure() async {
    try {
      return (await _api.commandReference(), null);
    } on JockyFailure catch (failure) {
      return (CommandReference.empty, failure);
    }
  }
}
