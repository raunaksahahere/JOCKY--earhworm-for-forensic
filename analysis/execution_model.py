"""
Normalized execution-event model shared by every platform collector.

The point of this module is a single vocabulary for "what do we actually
know". A JOCKY report must never let a reader mistake a current snapshot
for a historical record, or an inference for an observation, so every
event carries its own classification, its source, and an explicit list of
the fields that could not be obtained.

Nothing here reads the host. Collectors in `analysis/execution_linux.py`
and `analysis/execution_windows.py` produce these structures; this module
only defines and validates them.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

# What a record proves, not how interesting it is.
HISTORICAL_EVIDENCE = "HISTORICAL_EVIDENCE"
CURRENT_OBSERVATION = "CURRENT_OBSERVATION"
INFERRED = "INFERRED"
UNAVAILABLE = "UNAVAILABLE"

# Per-field provenance.
OBSERVED = "OBSERVED"
DERIVED = "DERIVED"

# Why a telemetry source did or did not contribute. These are deliberately
# distinct: "the OS does not have this" and "the administrator has not turned
# it on" lead an investigator to different next steps.
AVAILABLE = "AVAILABLE"
NOT_AVAILABLE = "NOT_AVAILABLE"
NOT_ENABLED = "NOT_ENABLED"
PERMISSION_DENIED = "PERMISSION_DENIED"
NOT_COLLECTED = "NOT_COLLECTED"

EVENT_FIELDS = (
    "event_id", "timestamp", "last_seen", "process_name", "executable",
    "parent_process", "parent_pid", "pid", "command_line", "interpreter",
    "user", "source", "source_record_id", "hash", "classification",
    "collection_status", "provenance", "evidence_strength", "raw",
)

# Argument names whose value is commonly a secret. Used only to redact, never
# to collect more: command lines are off by default and redacted when enabled.
_SECRET_ARGUMENT = re.compile(
    r"(?i)(-{0,2}(?:pass(?:word|wd)?|pwd|token|secret|api[-_]?key|auth|bearer|"
    r"credential|private[-_]?key)s?)([=:\s]+)(\S+)"
)
_SECRET_ENVIRONMENT = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:PASSWORD|PASSWD|TOKEN|SECRET|APIKEY|API_KEY|CREDENTIAL)[A-Z0-9_]*)(=)(\S+)"
)
REDACTION = "[redacted]"

INTERPRETERS = {
    "python", "python2", "python3", "python.exe", "python3.exe", "pythonw.exe",
    "bash", "sh", "dash", "zsh", "ksh", "fish", "node", "node.exe", "deno",
    "powershell.exe", "powershell", "pwsh", "pwsh.exe", "cmd.exe", "cscript.exe",
    "wscript.exe", "mshta.exe", "perl", "ruby", "php", "java", "java.exe",
}


class CollectionWindow:
    """An explicit, bounded history window. There is no unbounded mode."""

    MAX_HOURS = 24 * 90
    DEFAULT_HOURS = 24 * 7

    def __init__(self, start: datetime, end: datetime, requested_hours: float):
        self.start, self.end, self.requested_hours = start, end, requested_hours

    @classmethod
    def resolve(cls, hours=None, *, end=None) -> "CollectionWindow":
        end = end or datetime.now(timezone.utc)
        if hours is None:
            hours = cls.DEFAULT_HOURS
        try:
            hours = float(hours)
        except (TypeError, ValueError) as error:
            raise ValueError("window_hours must be a number of hours") from error
        if hours <= 0:
            raise ValueError("window_hours must be greater than zero")
        if hours > cls.MAX_HOURS:
            raise ValueError(f"window_hours must not exceed {cls.MAX_HOURS} (90 days)")
        return cls(end - timedelta(hours=hours), end, hours)

    def contains(self, moment: datetime | None) -> bool:
        return moment is not None and self.start <= moment <= self.end

    def to_dict(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "requested_hours": self.requested_hours,
            "bounded": True,
            "maximum_hours": self.MAX_HOURS,
        }


def redact_command_line(text: str | None) -> tuple[str | None, bool]:
    """Mask values that commonly carry credentials.

    Returns the text and whether anything was masked. This is a mitigation,
    not a guarantee: a command line can carry a secret in a form no pattern
    recognises, which is why collection is opt-in and the result is labelled.
    """
    if not text:
        return None, False
    masked = _SECRET_ARGUMENT.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTION}", text)
    masked = _SECRET_ENVIRONMENT.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTION}", masked)
    return masked, masked != text


def interpreter_for(name: str | None, executable: str | None) -> str | None:
    """Name the runtime when the image is a known interpreter.

    DERIVED, never proof: an interpreter running says nothing about which
    script it ran, and JOCKY must not imply otherwise.
    """
    for candidate in (name, (executable or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]):
        if candidate and candidate.lower() in INTERPRETERS:
            return candidate
    return None


def build_event(
    *,
    source: str,
    source_record_id: str | None,
    timestamp: str | None,
    classification: str = HISTORICAL_EVIDENCE,
    evidence_strength: str,
    provenance: str,
    observed: dict | None = None,
    derived: dict | None = None,
    unavailable: dict | None = None,
    raw: dict | None = None,
    last_seen: str | None = None,
) -> dict:
    """Assemble one normalized event.

    `observed` holds values read directly from the source record, `derived`
    values JOCKY computed from them, and `unavailable` maps each absent field
    to the reason it is absent. Every field in EVENT_FIELDS is present in the
    result so a reader never has to guess whether a missing key means "no" or
    "not looked at".
    """
    observed, derived, unavailable = observed or {}, derived or {}, unavailable or {}
    event = {field: None for field in EVENT_FIELDS}
    event.update(observed)
    event.update(derived)
    event.update(
        source=source,
        source_record_id=source_record_id,
        timestamp=timestamp,
        last_seen=last_seen or timestamp,
        classification=classification,
        evidence_strength=evidence_strength,
        provenance=provenance,
        collection_status=AVAILABLE,
        raw=raw or {},
        field_provenance={
            **{key: OBSERVED for key in observed},
            **{key: DERIVED for key in derived},
            **{key: UNAVAILABLE for key in unavailable},
        },
        unavailable=dict(unavailable),
    )
    event["event_id"] = event["event_id"] or f"{source}:{source_record_id}"
    return event


def source_record(
    name: str,
    status: str,
    *,
    detail: str,
    event_count: int = 0,
    evidence_strength: str | None = None,
    truncated: bool = False,
    location: str | None = None,
) -> dict:
    """One line of the "where did we look, and what did we find" table."""
    return {
        "name": name,
        "status": status,
        "detail": detail,
        "event_count": event_count,
        "evidence_strength": evidence_strength,
        "truncated": truncated,
        "location": location,
    }
