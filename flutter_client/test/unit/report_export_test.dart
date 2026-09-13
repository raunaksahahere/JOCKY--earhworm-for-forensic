import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:jocky_client/core/errors/failure.dart';
import 'package:jocky_client/models/executions/execution_record.dart';
import 'package:jocky_client/models/reports/report.dart';
import 'package:jocky_client/services/export/report_export_service.dart';

import '../support/fixtures.dart';

void main() {
  late Directory temp;
  const exporter = FileReportExportService();

  ForensicReport reportFrom(String fixture) =>
      ForensicReport.fromJson(loadFixture(fixture)['report'] as Map<String, dynamic>)!;

  setUp(() async {
    temp = await Directory.systemTemp.createTemp('jocky-export-');
  });

  tearDown(() async {
    if (temp.existsSync()) await temp.delete(recursive: true);
  });

  test('JSON export is the engine report itself, not a re-derived summary', () async {
    final source = loadFixture('hash')['report'] as Map<String, dynamic>;
    final path = '${temp.path}/report.json';

    await exporter.writeJson(path, reportFrom('hash'));

    final written = jsonDecode(File(path).readAsStringSync());
    expect(written, equals(source));
  });

  test('JSON export preserves unicode paths without escaping them away', () async {
    final path = '${temp.path}/unicode.json';
    await exporter.writeJson(path, reportFrom('hash'));

    final text = File(path).readAsStringSync();
    expect(text, contains('नमूना'));
  });

  test('a failed execution exports its errors and code', () async {
    final path = '${temp.path}/failed.json';
    await exporter.writeJson(path, reportFrom('notfound'));

    final written = jsonDecode(File(path).readAsStringSync()) as Map<String, dynamic>;
    expect(written['status'], 'failed');
    expect(written['error_code'], 'not_found');
    expect(written['errors'], isNotEmpty);
  });

  test('the record bundle states its client-side provenance', () async {
    final path = '${temp.path}/bundle.json';
    final execution = ExecutionRecord(
      id: 'EXEC-1',
      submittedAt: DateTime.utc(2026, 9, 12),
      commandText: 'SYSTEM INFO',
      outcome: ExecutionOutcome.completed,
      origin: ExecutionOrigin.commandCenter,
      caseId: null,
      clientElapsedMs: 12,
      report: reportFrom('system'),
    );

    await exporter.writeExecutionBundleJson(path, [execution]);

    final written = jsonDecode(File(path).readAsStringSync()) as Map<String, dynamic>;
    expect(written['execution_count'], 1);
    expect(written['provenance'], contains('Client-side record'));
    expect(written['provenance'], contains('engine response, unmodified'));
  });

  test('PDF rendering produces a real document for a completed report', () async {
    final bytes = await exporter.renderPdf(reportFrom('hash'), caseTitle: 'Seized laptop');

    expect(bytes.length, greaterThan(1000));
    expect(String.fromCharCodes(bytes.take(5)), '%PDF-');
  });

  test('PDF rendering also handles a failed report with no result payload', () async {
    final bytes = await exporter.renderPdf(reportFrom('syntax_error'));

    expect(String.fromCharCodes(bytes.take(5)), '%PDF-');
  });

  group('core-font escaping', () {
    // A path that silently vanished from a printed report would misrepresent
    // what was examined, so unsupported characters must survive as codepoints.
    test('non-Latin-1 characters become explicit codepoint escapes', () {
      expect(needsUnicodeEscaping('/evidence/नमूना.bin'), isTrue);
      expect(needsUnicodeEscaping('/evidence/sample.bin'), isFalse);
      expect(
        escapeForCoreFonts('नमूना'),
        r'\u{0928}\u{092E}\u{0942}\u{0928}\u{093E}',
      );
    });

    test('Latin-1 text is left exactly as it is', () {
      expect(escapeForCoreFonts(r'C:\Case Files\Ößterreich.bin'),
          r'C:\Case Files\Ößterreich.bin');
    });

    test('a report with a unicode path is flagged for the analyst up front', () {
      expect(pdfEscapingRequired(reportFrom('hash')), isTrue);
    });

    test('an ASCII-only report needs no escaping', () {
      expect(pdfEscapingRequired(reportFrom('system')), isFalse);
    });

    test('the escaped PDF still renders', () async {
      final bytes = await exporter.renderPdf(reportFrom('hash'));
      expect(String.fromCharCodes(bytes.take(5)), '%PDF-');
    });
  });

  test('an unwritable destination reports a local storage failure', () async {
    await expectLater(
      exporter.writeJson('${temp.path}/missing-dir/report.json', reportFrom('hash')),
      throwsA(
        isA<JockyFailure>().having((f) => f.kind, 'kind', FailureKind.localStorage),
      ),
    );
  });
}
