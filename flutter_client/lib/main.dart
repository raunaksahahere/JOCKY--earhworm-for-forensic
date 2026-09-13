import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app/app.dart';
import 'services/storage/settings_store.dart';
import 'state/providers.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  final settingsStore = FileSettingsStore();
  final settings = await settingsStore.load();
  runApp(
    ProviderScope(
      overrides: [
        settingsStoreProvider.overrideWithValue(settingsStore),

        initialSettingsProvider.overrideWithValue(settings),

      ],
      child: const JockyApp(),
    ),
  );
}
