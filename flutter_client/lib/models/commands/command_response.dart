import '../../core/utils/json.dart';
import '../reports/report.dart';
import '../results/analysis_result.dart';
import 'normalized_command.dart';

/// A successful `POST /command` response body.
class CommandResponse {
  const CommandResponse({
    required this.status,
    required this.command,
    required this.result,
    required this.report,
    required this.normalizedCommand,
    required this.raw,
  });

  final String status;
  final String command;
  final AnalysisResult? result;
  final ForensicReport? report;
  final NormalizedCommand? normalizedCommand;
  final Map<String, dynamic> raw;

  factory CommandResponse.fromJson(Map<String, dynamic> json) => CommandResponse(
        status: asString(json['status'], fallback: 'unknown'),
        command: asString(json['command']),
        result: AnalysisResult.fromJson(asMapOrNull(json['result'])),
        report: ForensicReport.fromJson(asMapOrNull(json['report'])),
        normalizedCommand:
            NormalizedCommand.fromJson(asMapOrNull(json['normalized_command'])),
        raw: json,
      );
}
