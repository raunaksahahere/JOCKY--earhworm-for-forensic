import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../services/backend/backend_supervisor.dart';
import 'providers.dart';

/// Application-wide engine state.
///
/// Combines two sources of truth: the supervisor's process lifecycle, and a
/// periodic `/health` probe. The probe matters even for an engine this client
/// started, because a live process is not the same as a responding engine.
class BackendController extends Notifier<BackendStatus> {
  Timer? _poll;
  StreamSubscription<BackendStatus>? _subscription;

  @override
  BackendStatus build() {
    final repository = ref.watch(backendRepositoryProvider);
    final interval = ref.watch(appConfigProvider).healthPollInterval;

    _subscription = repository.statusStream.listen((status) => state = status);
    _poll = Timer.periodic(interval, (_) => repository.probe());

    ref.onDispose(() {
      _poll?.cancel();
      _subscription?.cancel();
    });

    // Initial probe: adopts an engine that is already running.
    scheduleMicrotask(repository.probe);
    return repository.status;
  }

  /// Starts the packaged engine, or adopts one already listening.
  Future<void> start() async {
    await ref.read(backendRepositoryProvider).start();
  }

  Future<void> refresh() async {
    await ref.read(backendRepositoryProvider).probe();
  }

  Future<void> restart() async {
    await ref.read(backendRepositoryProvider).restart();
  }

  Future<void> stop() async {
    await ref.read(backendRepositoryProvider).stop();
  }

  /// Captured engine stdout/stderr. Diagnostics only — never parsed as a
  /// readiness or result protocol.
  List<String> get diagnosticLog =>
      ref.read(backendRepositoryProvider).supervisor.diagnosticLog;
}

final backendControllerProvider =
    NotifierProvider<BackendController, BackendStatus>(BackendController.new);

/// Convenience: is the engine ready to accept commands right now?
final backendReadyProvider = Provider<bool>(
  (ref) => ref.watch(backendControllerProvider).isReady,
);
