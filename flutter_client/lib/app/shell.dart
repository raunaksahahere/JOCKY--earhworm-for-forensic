import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/theme/tokens.dart';
import '../models/cases/investigation.dart';
import '../state/providers.dart';
import '../widgets/status_chip.dart';
import 'command_palette.dart';
import 'navigation.dart';
import 'sidebar.dart';
import 'shortcuts.dart';

/// Application frame: persistent sidebar, context bar, and the routed view.
class JockyShell extends ConsumerStatefulWidget {
  const JockyShell({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<JockyShell> createState() => _JockyShellState();
}

class _JockyShellState extends ConsumerState<JockyShell> {
  bool _collapsed = false;

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    // Narrow windows collapse the rail automatically; the operator can still
    // override it, and their choice wins once the window is wide enough again.
    final collapsed = _collapsed || width < 1000;

    return Actions(
      actions: {
        OpenPaletteIntent: CallbackAction<OpenPaletteIntent>(
          onInvoke: (_) {
            showCommandPalette(context, ref);
            return null;
          },
        ),
        GoToDestinationIntent: CallbackAction<GoToDestinationIntent>(
          onInvoke: (intent) {
            final destinations = JockyDestination.values;
            if (intent.index >= 0 && intent.index < destinations.length) {
              context.go(destinations[intent.index].path);
            }
            return null;
          },
        ),
      },
      child: Scaffold(
        backgroundColor: JockyColors.canvas,
        body: Row(
          children: [
            JockySidebar(
              collapsed: collapsed,
              onToggle: () => setState(() => _collapsed = !_collapsed),
            ),
            Expanded(
              child: Column(
                children: [
                  const _ContextBar(),
                  const Divider(height: 1),
                  Expanded(child: widget.child),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ContextBar extends ConsumerWidget {
  const _ContextBar();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final destination = JockyDestination.forLocation(JockyDestination.locationOf(context));
    final recordsState = ref.watch(recordsControllerProvider);
    final cases = recordsState.records.investigations;
    final activeCase = recordsState.records.activeCase;

    return Container(
      height: 52,
      color: JockyColors.sidebar,
      padding: const EdgeInsets.symmetric(horizontal: JockySpace.lg),
      child: Row(
        children: [
          Icon(destination.icon, size: 15, color: JockyColors.textMuted),
          const SizedBox(width: JockySpace.sm),
          Text(destination.label, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(width: JockySpace.md),
          Flexible(
            child: Text(
              destination.description,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 11.5, color: JockyColors.textFaint),
            ),
          ),
          const Spacer(),
          if (!recordsState.isDurable)
            Padding(
              padding: const EdgeInsets.only(right: JockySpace.md),
              child: StatusChip(
                label: 'Session not recorded',
                tone: StatusTone.warn,
                dense: true,
                tooltip: recordsState.storeFailure?.message,
              ),
            ),
          _CaseSelector(cases: cases, active: activeCase),
          const SizedBox(width: JockySpace.md),
          Tooltip(
            message: 'Command palette',
            child: OutlinedButton.icon(
              onPressed: () => showCommandPalette(context, ref),
              icon: const Icon(Icons.search, size: 14),
              label: const Row(
                mainAxisSize: MainAxisSize.min,
                children: [Text('Search'), SizedBox(width: 6), KeyHint(['Ctrl', 'K'])],
              ),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _CaseSelector extends ConsumerWidget {
  const _CaseSelector({required this.cases, required this.active});

  final List<Investigation> cases;
  final Investigation? active;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Tooltip(
      message: 'Commands are attributed to the active case',
      child: PopupMenuButton<String?>(
        tooltip: '',
        position: PopupMenuPosition.under,
        color: JockyColors.surfaceOverlay,
        onSelected: (value) {
          if (value == '__new__') {
            context.go('${JockyDestination.investigations.path}?new=1');
            return;
          }
          ref.read(recordsControllerProvider.notifier).setActiveCase(value);
        },
        itemBuilder: (context) => [
          const PopupMenuItem<String?>(
            value: null,
            height: 34,
            child: Text('No case (unattributed)', style: TextStyle(fontSize: 12)),
          ),
          for (final investigation in cases)
            PopupMenuItem<String?>(
              value: investigation.id,
              height: 34,
              child: Row(
                children: [
                  Icon(
                    investigation.isOpen ? Icons.folder_open : Icons.folder_off_outlined,
                    size: 13,
                    color: JockyColors.textMuted,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      investigation.title,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 12),
                    ),
                  ),
                ],
              ),
            ),
          const PopupMenuDivider(),
          const PopupMenuItem<String?>(
            value: '__new__',
            height: 34,
            child: Row(
              children: [
                Icon(Icons.add, size: 13, color: JockyColors.accent),
                SizedBox(width: 8),
                Text('Open a new investigation', style: TextStyle(fontSize: 12)),
              ],
            ),
          ),
        ],
        child: Container(
          height: 32,
          constraints: const BoxConstraints(maxWidth: 260),
          padding: const EdgeInsets.symmetric(horizontal: JockySpace.md),
          decoration: BoxDecoration(
            color: JockyColors.surfaceRaised,
            border: Border.all(color: JockyColors.border),
            borderRadius: BorderRadius.circular(JockyRadius.md),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                active == null ? Icons.folder_off_outlined : Icons.folder_open,
                size: 13,
                color: active == null ? JockyColors.textFaint : JockyColors.accent,
              ),
              const SizedBox(width: JockySpace.sm),
              Flexible(
                child: Text(
                  active?.title ?? 'No active case',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 12,
                    color: active == null ? JockyColors.textFaint : JockyColors.text,
                  ),
                ),
              ),
              const SizedBox(width: 4),
              const Icon(Icons.expand_more, size: 14, color: JockyColors.textFaint),
            ],
          ),
        ),
      ),
    );
  }
}
