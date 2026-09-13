import 'dart:convert';
import 'dart:io';

/// Loads a captured response from the real JOCKY backend.
///
/// Every fixture in `test/fixtures/` was recorded from a live Flask server
/// (`communication/server.py`) — they are not hand-written approximations, so a
/// contract drift in the backend shows up here as a failing test.
Map<String, dynamic> loadFixture(String name) {
  final file = File('test/fixtures/$name.json');
  if (!file.existsSync()) {
    throw StateError('Missing fixture test/fixtures/$name.json');
  }
  return jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
}

String loadFixtureRaw(String name) => File('test/fixtures/$name.json').readAsStringSync();
