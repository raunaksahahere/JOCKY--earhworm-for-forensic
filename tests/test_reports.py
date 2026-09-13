from datetime import datetime, timezone
import json

from reports.report import create_report


def test_report_identity_timestamp_payload():
    before = datetime.now(timezone.utc)
    result = {"action": "hash", "hash": "abc", "filename": "नमूना.bin"}
    report = create_report('HASH FILE "नमूना.bin"', "hash", "नमूना.bin", result=result, execution_time_ms=1.25)
    assert report["command"] == 'HASH FILE "नमूना.bin"'
    assert report["target"] == "नमूना.bin" and report["result"] == result
    assert report["status"] == "completed" and report["schema_version"] == 1
    assert before <= datetime.fromisoformat(report["timestamp"]) <= datetime.now(timezone.utc)
    assert report["execution_time_ms"] == 1.25
    assert report["report_id"] != create_report("x", None)["report_id"]
    assert json.loads(json.dumps(report, ensure_ascii=False, allow_nan=False)) == report


def test_failure():
    report = create_report("bad", None, status="failed", errors=["invalid syntax"])
    assert report["status"] == "failed" and report["errors"] == ["invalid syntax"]
    assert report["result"] == {}


def test_skipped_truncated_information_and_snapshot():
    result = {"truncated": True, "skipped_count": 2, "warnings": ["incomplete"], "entries": [{"name": "a"}]}
    report = create_report("LIST FILES .", "list", result=result, warnings=["incomplete"])
    assert report["warnings"] == ["incomplete"]
    assert report["result"]["skipped_count"] == 2 and report["result"]["truncated"]
    result["entries"][0]["name"] = "changed"
    assert report["result"]["entries"][0]["name"] == "a"
