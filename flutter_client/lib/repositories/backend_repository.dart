import '../core/errors/failure.dart';
import '../models/health/backend_health.dart';
import '../services/api/jocky_api_client.dart';
import '../services/backend/backend_supervisor.dart';

/// Engine readiness and lifecycle.
class BackendRepository {
  const BackendRepository({required this._api, required this._supervisor});

  final JockyApiClient _api;
  final BackendSupervisor _supervisor;

  BackendSupervisor get supervisor => _supervisor;

  Stream<BackendStatus> get statusStream => _supervisor.statusStream;

  BackendStatus get status => _supervisor.status;

  Future<BackendStatus> start() => _supervisor.start();

  Future<BackendStatus> probe() => _supervisor.probe();

  Future<BackendStatus> restart() => _supervisor.restart();

  Future<void> stop() => _supervisor.stop();

  Future<(BackendHealth?, JockyFailure?)> health() async {
    try {
      return (await _api.health(), null);
    } on JockyFailure catch (failure) {
      return (null, failure);
    }
  }
}
