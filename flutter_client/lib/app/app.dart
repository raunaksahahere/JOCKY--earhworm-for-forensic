import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/config/app_config.dart';
import '../core/theme/app_theme.dart';
import '../state/providers.dart';
import 'router.dart';
import 'shortcuts.dart';

class JockyApp extends ConsumerStatefulWidget {
  const JockyApp({super.key, this.initialLocation = '/'});

  final String initialLocation;

  @override
  ConsumerState<JockyApp> createState() => _JockyAppState();
}

class _JockyAppState extends ConsumerState<JockyApp> {
  late final router = buildRouter(initialLocation: widget.initialLocation);

  @override
  void initState() {
    super.initState();
    // Adopt or start the engine once the first frame is scheduled, so the
    // window appears immediately and readiness is reported as it changes.
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final controller = ref.read(backendControllerProvider.notifier);
      if (ref.read(settingsControllerProvider).autoStartBackend) {
        await controller.start();
      } else {
        await controller.refresh();
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final textScale = ref.watch(settingsControllerProvider).textScale;

    return Shortcuts(
      shortcuts: globalShortcuts(),
      child: MaterialApp.router(
        title: ClientBuild.name,
        debugShowCheckedModeBanner: false,
        theme: buildJockyTheme(),
        routerConfig: router,
        shortcuts: {
          ...WidgetsApp.defaultShortcuts,
          // Space must not activate a focused control while typing a path.
          const SingleActivator(LogicalKeyboardKey.space): const DoNothingIntent(),
        },
        builder: (context, child) => MediaQuery.withClampedTextScaling(
          minScaleFactor: textScale,
          maxScaleFactor: textScale * 1.3,
          child: child ?? const SizedBox.shrink(),
        ),
      ),
    );
  }
}
