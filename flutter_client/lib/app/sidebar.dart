import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/config/app_config.dart';
import '../core/theme/tokens.dart';
import '../services/backend/backend_supervisor.dart';
import '../state/providers.dart';
import '../widgets/status_chip.dart';
import 'navigation.dart';

/// Persistent desktop navigation rail. Collapses to icons on narrow windows
/// but never disappears — the analyst always knows where they are.
class JockySidebar extends ConsumerWidget {
  const JockySidebar({super.key, required this.collapsed, required this.onToggle});

  final bool collapsed;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final location = JockyDestination.locationOf(context);
    final active = JockyDestination.forLocation(location);
    final activeCase = ref.watch(activeCaseProvider);
    final status = ref.watch(backendControllerProvider);

    return Container(
      width: collapsed ? 62 : 232,
      decoration: const BoxDecoration(
        color: JockyColors.sidebar,
        border: Border(right: BorderSide(color: JockyColors.border)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _brand(context),
          const Divider(height: 1),
          if (!collapsed) _caseStrip(context, activeCase?.title, activeCase?.reference),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.symmetric(vertical: JockySpace.sm),
              children: [
                for (var i = 0; i < JockyDestination.values.length; i++)
                  _NavItem(
                    destination: JockyDestination.values[i],
                    active: JockyDestination.values[i] == active,
                    collapsed: collapsed,
                    shortcutIndex: i + 1,
                    onTap: () => context.go(JockyDestination.values[i].path),
                  ),
              ],
            ),
          ),
          const Divider(height: 1),
          _engineStrip(context, status),
          _footer(context),
        ],
      ),
    );
  }

  Widget _brand(BuildContext context) {
    return Container(
      height: 52,
      padding: EdgeInsets.symmetric(horizontal: collapsed ? 10 : JockySpace.lg),
      child: Row(
        children: [
          // The application mark. Falls back to the lettered badge if the
          // asset cannot be loaded, so the rail is never left with a gap.
          ClipRRect(
            borderRadius: BorderRadius.circular(JockyRadius.sm),
            child: Image.asset(
              'assets/app_icon.png',
              width: 26,
              height: 26,
              filterQuality: FilterQuality.medium,
              errorBuilder: (context, error, stack) => Container(
                width: 26,
                height: 26,
                decoration: BoxDecoration(
                  border: Border.all(color: JockyColors.accent, width: 1.4),
                  borderRadius: BorderRadius.circular(JockyRadius.sm),
                ),
                alignment: Alignment.center,
                child: const Text(
                  'J',
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w800,
                    color: JockyColors.accent,
                  ),
                ),
              ),
            ),
          ),
          if (!collapsed) ...[
            const SizedBox(width: JockySpace.md),
            const Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    'JOCKY',
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 2.2,
                      color: JockyColors.text,
                    ),
                  ),
                  Text(
                    'Forensic workstation',
                    style: TextStyle(fontSize: 9.5, color: JockyColors.textFaint),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _caseStrip(BuildContext context, String? title, String? reference) {
    return InkWell(
      onTap: () => context.go(JockyDestination.investigations.path),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: JockySpace.lg, vertical: JockySpace.md),
        decoration: const BoxDecoration(
          border: Border(bottom: BorderSide(color: JockyColors.border)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('ACTIVE CASE', style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 4),
            Text(
              title ?? 'No case selected',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: 12.5,
                fontWeight: FontWeight.w600,
                color: title == null ? JockyColors.textFaint : JockyColors.text,
              ),
            ),
            if (reference != null)
              Text(
                reference,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 10.5,
                  fontFamily: JockyType.mono,
                  color: JockyColors.textMuted,
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _engineStrip(BuildContext context, BackendStatus status) {
    final (tone, label) = switch (status.phase) {
      BackendPhase.ready => (StatusTone.ok, 'Engine ready'),
      BackendPhase.starting || BackendPhase.resolving => (StatusTone.info, 'Engine starting'),
      BackendPhase.degraded => (StatusTone.warn, 'Engine degraded'),
      BackendPhase.stopping => (StatusTone.warn, 'Engine stopping'),
      BackendPhase.stopped => (StatusTone.danger, 'Engine stopped'),
      BackendPhase.unavailable => (StatusTone.danger, 'Engine offline'),
      BackendPhase.idle => (StatusTone.neutral, 'Engine unknown'),
    };

    return InkWell(
      onTap: () => context.go(JockyDestination.systemStatus.path),
      child: Padding(
        padding: EdgeInsets.symmetric(
          horizontal: collapsed ? 10 : JockySpace.lg,
          vertical: JockySpace.md,
        ),
        child: collapsed
            ? Tooltip(
                message: label,
                child: Icon(statusIcon(tone), size: 16, color: statusColor(tone)),
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  StatusChip(label: label, tone: tone, dense: true),
                  const SizedBox(height: 4),
                  Text(
                    status.origin ?? 'no endpoint',
                    style: const TextStyle(
                      fontSize: 10,
                      fontFamily: JockyType.mono,
                      color: JockyColors.textFaint,
                    ),
                  ),
                ],
              ),
      ),
    );
  }

  Widget _footer(BuildContext context) {
    return Padding(
      padding: EdgeInsets.symmetric(horizontal: collapsed ? 6 : JockySpace.sm, vertical: 4),
      child: Row(
        mainAxisAlignment:
            collapsed ? MainAxisAlignment.center : MainAxisAlignment.spaceBetween,
        children: [
          if (!collapsed)
            Padding(
              padding: const EdgeInsets.only(left: JockySpace.sm),
              child: Text(
                'v${ClientBuild.version}',
                style: const TextStyle(fontSize: 10, color: JockyColors.textFaint),
              ),
            ),
          IconButton(
            tooltip: collapsed ? 'Expand navigation' : 'Collapse navigation',
            onPressed: onToggle,
            iconSize: 15,
            color: JockyColors.textFaint,
            icon: Icon(collapsed ? Icons.chevron_right : Icons.chevron_left),
          ),
        ],
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({
    required this.destination,
    required this.active,
    required this.collapsed,
    required this.shortcutIndex,
    required this.onTap,
  });

  final JockyDestination destination;
  final bool active;
  final bool collapsed;
  final int shortcutIndex;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final content = Container(
      height: 36,
      margin: const EdgeInsets.symmetric(horizontal: JockySpace.sm, vertical: 1),
      padding: EdgeInsets.symmetric(horizontal: collapsed ? 0 : JockySpace.md),
      decoration: BoxDecoration(
        color: active ? JockyColors.accentWash : Colors.transparent,
        borderRadius: BorderRadius.circular(JockyRadius.md),
        border: Border.all(
          color: active ? JockyColors.accent.withValues(alpha: 0.35) : Colors.transparent,
        ),
      ),
      child: Row(
        mainAxisAlignment:
            collapsed ? MainAxisAlignment.center : MainAxisAlignment.start,
        children: [
          Icon(
            destination.icon,
            size: 16,
            color: active ? JockyColors.accent : JockyColors.textMuted,
          ),
          if (!collapsed) ...[
            const SizedBox(width: JockySpace.md),
            Expanded(
              child: Text(
                destination.label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 12.5,
                  fontWeight: active ? FontWeight.w600 : FontWeight.w500,
                  color: active ? JockyColors.text : JockyColors.textMuted,
                ),
              ),
            ),
            Text(
              '$shortcutIndex',
              style: const TextStyle(fontSize: 9.5, color: JockyColors.textFaint),
            ),
          ],
        ],
      ),
    );

    return Semantics(
      button: true,
      selected: active,
      label: '${destination.label}. ${destination.description}',
      child: Tooltip(
        message: collapsed ? '${destination.label}  (Ctrl+$shortcutIndex)' : '',
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(JockyRadius.md),
          child: content,
        ),
      ),
    );
  }
}
