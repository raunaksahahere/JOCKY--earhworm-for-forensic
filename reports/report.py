from copy import deepcopy
from datetime import datetime, timezone
import uuid


def create_report(
    command,
    action,
    target=None,
    status="completed",
    result=None,
    execution_time_ms=None,
    warnings=None,
    errors=None,
):
    return {
        "report_id": f"JCK-{uuid.uuid4().hex[:8].upper()}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "schema_version": 1,
        "command": command,
        "action": action,
        "target": target,
        "status": status,
        "execution_time_ms": execution_time_ms,
        "result": deepcopy(result) if result is not None else {},
        "warnings": list(dict.fromkeys((warnings or []) + (
            result.get("warnings", []) if isinstance(result, dict) else []))),
        "errors": list(errors or []),
    }
