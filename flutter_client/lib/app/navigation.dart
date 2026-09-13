import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

/// Primary navigation destinations. Order is the analyst's workflow order:
/// see the state of things, run something, work the case, then the record.
enum JockyDestination {
  overview('/', 'Overview', Icons.dashboard_outlined, 'Engine, case and recent activity'),
  commandCenter('/command-center', 'Command Center', Icons.terminal_outlined,
      'Submit commands to the engine'),
  investigations('/investigations', 'Investigations', Icons.folder_open_outlined,
      'Cases, evidence sources and timelines'),
  reports('/reports', 'Reports', Icons.description_outlined, 'Engine-issued report archive'),
  history('/history', 'History', Icons.history, 'Every command this workstation submitted'),
  tools('/tools', 'Tools', Icons.construction_outlined, 'Guided forensic actions'),
  systemStatus('/system', 'System Status', Icons.monitor_heart_outlined,
      'Engine readiness, client state and host observations'),
  settings('/settings', 'Settings', Icons.tune, 'Connection, display and storage');

  const JockyDestination(this.path, this.label, this.icon, this.description);

  final String path;
  final String label;
  final IconData icon;
  final String description;

  /// The current path. Reads the route state so the shell rebuilds on
  /// navigation; only valid beneath a matched route, which is why the
  /// not-found page is rendered outside the shell.
  static String locationOf(BuildContext context) =>
      GoRouterState.of(context).uri.path;

  static JockyDestination forLocation(String location) {
    // Longest match first so nested detail routes keep their section active.
    final matches = JockyDestination.values
        .where((d) => d.path == '/' ? location == '/' : location.startsWith(d.path))
        .toList()
      ..sort((a, b) => b.path.length.compareTo(a.path.length));
    return matches.isEmpty ? JockyDestination.overview : matches.first;
  }
}
