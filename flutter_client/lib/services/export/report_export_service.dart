import '../api/jocky_api_client.dart';
import 'dart:convert';
import 'dart:io';

import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;

import '../../core/config/app_config.dart';
import '../../core/errors/failure.dart';
import '../../core/utils/format.dart';
import '../../models/executions/execution_record.dart';
import '../../models/reports/report.dart';

/// Writes reports to disk.
///
/// JSON export is the engine's own report object, byte-for-byte from the
/// response — nothing is re-derived, reordered or summarised, so an exported
/// file can be re-hashed and compared.
///
/// Production PDF export uses the backend snapshot renderer. The local fallback
/// below remains available for tests and old report-only tooling.
/// Every PDF says so in its footer, so a printed page is never mistaken for a
/// backend-issued document.
///
/// The PDF uses the format's built-in core fonts, which can only draw Latin-1.
/// Evidence paths are routinely not Latin-1, and a forensic document must never
/// silently drop characters, so any character the core fonts cannot render is
/// written as an explicit `\u{XXXX}` escape and the page carries a notice
/// saying so. JSON export remains the verbatim form.
/// True when [value] contains a character the PDF core fonts cannot draw.
bool needsUnicodeEscaping(String value) => value.runes.any((rune) => rune > 0xFF);

/// Rewrites characters outside Latin-1 as `\u{XXXX}` escapes.
///
/// Lossless and unambiguous: the analyst can read the exact codepoint instead
/// of a blank where a filename used to be.
String escapeForCoreFonts(String value) {
  if (!needsUnicodeEscaping(value)) return value;
  final buffer = StringBuffer();
  for (final rune in value.runes) {
    if (rune > 0xFF) {
      buffer.write('\\u{${rune.toRadixString(16).toUpperCase().padLeft(4, '0')}}');
    } else {
      buffer.writeCharCode(rune);
    }
  }
  return buffer.toString();
}

/// Whether rendering [report] to PDF will escape characters the core fonts
/// cannot draw. The UI calls this so the analyst is told before they rely on
/// the printed form.
bool pdfEscapingRequired(ForensicReport report) =>
    needsUnicodeEscaping(jsonEncode(report.toJson()));

abstract class ReportExportService {
  Future<void> writeJson(String path, ForensicReport report);
  Future<void> writeExecutionBundleJson(String path, List<ExecutionRecord> executions);
  Future<void> writePdf(String path, ForensicReport report, {String? caseTitle});
  Future<List<int>> renderPdf(ForensicReport report, {String? caseTitle});
}

class FileReportExportService implements ReportExportService {
  const FileReportExportService({this.api});
  final JockyApiClient? api;

  static const _encoder = JsonEncoder.withIndent('  ');

  @override
  Future<void> writeJson(String path, ForensicReport report) =>
      _write(path, utf8.encode(_encoder.convert(report.toJson())));

  @override
  Future<void> writeExecutionBundleJson(
    String path,
    List<ExecutionRecord> executions,
  ) {
    final bundle = {
      'exported_by': '${ClientBuild.name} ${ClientBuild.version}',
      'exported_at': DateTime.now().toUtc().toIso8601String(),
      'provenance': 'Client-side record of commands submitted by this workstation. '
          'Each embedded report is the engine response, unmodified.',
      'execution_count': executions.length,
      'executions': executions.map((e) => e.toJson()).toList(),
    };
    return _write(path, utf8.encode(_encoder.convert(bundle)));
  }

  @override
  Future<void> writePdf(String path, ForensicReport report, {String? caseTitle}) async =>
      _write(path, await renderPdf(report, caseTitle: caseTitle));

  Future<void> _write(String path, List<int> bytes) async {
    try {
      await File(path).writeAsBytes(bytes, flush: true);
    } on FileSystemException catch (error) {
      throw JockyFailure(
        kind: FailureKind.localStorage,
        message: 'The export could not be written to the selected location.',
        detail: '${error.message} ($path)',
      );
    }
  }

  @override
  Future<List<int>> renderPdf(ForensicReport report, {String? caseTitle}) async {
    if (api != null) {
      return (await api!.request('/api/v1/reports/${report.reportId}/export', body: {})).bodyBytes;
    }
    final document = pw.Document(title: 'JOCKY report ${report.reportId}');
    final mono = pw.TextStyle(font: pw.Font.courier(), fontSize: 8.5);
    final label = pw.TextStyle(
      fontSize: 7.5,
      color: PdfColors.grey700,
      letterSpacing: 0.6,
      fontWeight: pw.FontWeight.bold,
    );

    // Everything written into the document goes through the escaper.
    var escaped = false;
    String safe(String value) {
      if (needsUnicodeEscaping(value)) escaped = true;
      return escapeForCoreFonts(value);
    }

    pw.Widget field(String name, String value) => pw.Padding(
          padding: const pw.EdgeInsets.only(bottom: 6),
          child: pw.Column(
            crossAxisAlignment: pw.CrossAxisAlignment.start,
            children: [
              pw.Text(name.toUpperCase(), style: label),
              pw.SizedBox(height: 1.5),
              pw.Text(value.isEmpty ? 'not available' : safe(value), style: mono),
            ],
          ),
        );

    pw.Widget section(String title, List<pw.Widget> children) => pw.Column(
          crossAxisAlignment: pw.CrossAxisAlignment.start,
          children: [
            pw.SizedBox(height: 10),
            pw.Text(title.toUpperCase(),
                style: pw.TextStyle(fontSize: 9, fontWeight: pw.FontWeight.bold)),
            pw.Divider(thickness: 0.6, color: PdfColors.grey500, height: 8),
            ...children,
          ],
        );

    final result = report.result;

    document.addPage(
      pw.MultiPage(
        pageFormat: PdfPageFormat.a4,
        margin: const pw.EdgeInsets.fromLTRB(36, 36, 36, 44),
        header: (context) => context.pageNumber > 1
            ? pw.Container(
                margin: const pw.EdgeInsets.only(bottom: 10),
                child: pw.Text('JOCKY ${report.reportId}',
                    style: const pw.TextStyle(fontSize: 8, color: PdfColors.grey600)),
              )
            : pw.SizedBox(),
        footer: (context) => pw.Column(children: [
          pw.Divider(thickness: 0.5, color: PdfColors.grey400, height: 8),
          pw.Row(
            mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
            children: [
              pw.Text(
                'Rendered by ${ClientBuild.name} ${ClientBuild.version}. '
                'Report content produced by the JOCKY engine; this PDF is a client rendering.',
                style: const pw.TextStyle(fontSize: 6.5, color: PdfColors.grey600),
              ),
              pw.Text('${context.pageNumber}/${context.pagesCount}',
                  style: const pw.TextStyle(fontSize: 6.5, color: PdfColors.grey600)),
            ],
          ),
        ]),
        build: (context) => [
          pw.Row(
            crossAxisAlignment: pw.CrossAxisAlignment.start,
            mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
            children: [
              pw.Column(crossAxisAlignment: pw.CrossAxisAlignment.start, children: [
                pw.Text('FORENSIC OBSERVATION REPORT',
                    style: pw.TextStyle(fontSize: 13, fontWeight: pw.FontWeight.bold)),
                pw.SizedBox(height: 2),
                pw.Text(safe(report.reportId), style: mono),
              ]),
              pw.Column(crossAxisAlignment: pw.CrossAxisAlignment.end, children: [
                pw.Text(report.status.toUpperCase(),
                    style: pw.TextStyle(fontSize: 10, fontWeight: pw.FontWeight.bold)),
                pw.Text('schema v${report.schemaVersion ?? 'not reported'}',
                    style: const pw.TextStyle(fontSize: 7.5, color: PdfColors.grey700)),
              ]),
            ],
          ),
          section('Execution', [
            if (caseTitle != null) field('Case', caseTitle),
            field('Command', report.command),
            field('Action', report.action ?? unavailableMarker),
            field('Target', report.target ?? unavailableMarker),
            field('Recorded at', report.timestamp),
            field('Engine duration', formatDurationMs(report.executionTimeMs)),
            if (report.normalizedCommand != null)
              field('Parsed command', _encoder.convert(report.normalizedCommand!.raw)),
          ]),
          if (report.errors.isNotEmpty)
            section('Errors', [
              for (final error in report.errors) field(report.errorCode ?? 'error', error),
            ]),
          if (report.warnings.isNotEmpty)
            section('Collector warnings', [
              for (final warning in report.warnings)
                pw.Bullet(text: safe(warning), style: const pw.TextStyle(fontSize: 8.5)),
            ]),
          if (result != null)
            section('Observation completeness', [
              field('Complete', result.complete?.toString() ?? 'not reported'),
              field('Truncated', result.truncated.toString()),
              field('Skipped entries', result.skippedCount?.toString() ?? 'not reported'),
            ]),
          section('Result payload', [
            pw.Text(
              safe(_encoder.convert(report.raw['result'] ?? const <String, dynamic>{})),
              style: mono,
            ),
          ]),
          pw.Builder(
            builder: (context) => escaped
                ? pw.Container(
                    margin: const pw.EdgeInsets.only(top: 12),
                    padding: const pw.EdgeInsets.all(6),
                    decoration: pw.BoxDecoration(
                      border: pw.Border.all(color: PdfColors.grey600, width: 0.6),
                    ),
                    child: pw.Text(
                      'Character encoding notice: this PDF uses the format\'s core fonts, '
                      'which cannot draw characters outside Latin-1. Such characters appear '
                      'above as \\u{XXXX} escapes showing their exact Unicode codepoint. '
                      'The JSON export of this report carries the original characters verbatim.',
                      style: const pw.TextStyle(fontSize: 7.5, color: PdfColors.grey800),
                    ),
                  )
                : pw.SizedBox(),
          ),
        ],
      ),
    );

    return document.save();
  }
}
