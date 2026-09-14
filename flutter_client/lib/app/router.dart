import '../features/device/device_screen.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../core/theme/tokens.dart';

import '../features/casefile/case_file_screen.dart';
import '../features/command_center/command_center_screen.dart';
import '../features/history/history_screen.dart';
import '../features/investigations/investigation_detail_screen.dart';
import '../features/investigations/investigations_screen.dart';
import '../features/overview/overview_screen.dart';
import '../features/reports/report_detail_screen.dart';
import '../features/reports/reports_screen.dart';
import '../features/settings/settings_screen.dart';
import '../features/system_status/system_status_screen.dart';
import '../features/tools/tools_screen.dart';
import 'navigation.dart';
import 'shell.dart';

GoRouter buildRouter({String initialLocation = '/'}) {
  return GoRouter(
    initialLocation: initialLocation,
    routes: [
      ShellRoute(
        builder: (context, state, child) => JockyShell(child: child),
        routes: [
          GoRoute(path: '/device', pageBuilder: (context, state) => _page(state, const DeviceScreen()), routes: [
            GoRoute(path: ':caseId', pageBuilder: (context, state) => _page(state, DeviceScreen(key: ValueKey(state.pathParameters['caseId']), caseId: state.pathParameters['caseId']))),
          ]),
          GoRoute(
            path: JockyDestination.overview.path,
            pageBuilder: (context, state) => _page(state, const OverviewScreen()),
          ),
          GoRoute(
            path: JockyDestination.commandCenter.path,
            pageBuilder: (context, state) => _page(state, const CommandCenterScreen()),
          ),
          GoRoute(
            path: JockyDestination.investigations.path,
            pageBuilder: (context, state) => _page(
              state,
              InvestigationsScreen(
                openCreateDialog: state.uri.queryParameters['new'] == '1',
              ),
            ),
            routes: [
              GoRoute(
                path: ':caseId',
                pageBuilder: (context, state) => _page(
                  state,
                  InvestigationDetailScreen(caseId: state.pathParameters['caseId']!),
                ),
              ),
            ],
          ),
          GoRoute(
            path: JockyDestination.caseFile.path,
            pageBuilder: (context, state) => _page(
              state,
              CaseFileScreen(
                initialTab: int.tryParse(state.uri.queryParameters['tab'] ?? '') ?? 0,
              ),
            ),
          ),
          GoRoute(
            path: JockyDestination.reports.path,
            pageBuilder: (context, state) => _page(state, const ReportsScreen()),
            routes: [
              GoRoute(
                path: ':executionId',
                pageBuilder: (context, state) => _page(
                  state,
                  ReportDetailScreen(executionId: state.pathParameters['executionId']!),
                ),
              ),
            ],
          ),
          GoRoute(
            path: JockyDestination.history.path,
            pageBuilder: (context, state) => _page(state, const HistoryScreen()),
          ),
          GoRoute(
            path: JockyDestination.tools.path,
            pageBuilder: (context, state) => _page(state, const ToolsScreen()),
          ),
          GoRoute(
            path: JockyDestination.systemStatus.path,
            pageBuilder: (context, state) => _page(state, const SystemStatusScreen()),
          ),
          GoRoute(
            path: JockyDestination.settings.path,
            pageBuilder: (context, state) => _page(state, const SettingsScreen()),
          ),
        ],
      ),
    ],
    // Rendered outside the shell on purpose: the shell reads route state, and
    // an unmatched URI has none. A dead link must not take the window with it.
    errorBuilder: (context, state) => Scaffold(
      backgroundColor: JockyColors.canvas,
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.wrong_location_outlined, size: 28, color: JockyColors.textMuted),
              const SizedBox(height: JockySpace.md),
              Text(
                'No screen is registered for ${state.uri}',
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 13.5, color: JockyColors.text),
              ),
              const SizedBox(height: JockySpace.sm),
              const Text(
                'This build of the workstation has no view at that path.',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 12, color: JockyColors.textFaint),
              ),
              const SizedBox(height: JockySpace.lg),
              FilledButton(
                onPressed: () => context.go(JockyDestination.overview.path),
                child: const Text('Back to Overview'),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

/// Desktop navigation has no page transition: instant view swaps keep dense
/// tables from sliding around under the cursor.
Page<void> _page(GoRouterState state, Widget child) =>
    NoTransitionPage<void>(key: state.pageKey, child: child);
