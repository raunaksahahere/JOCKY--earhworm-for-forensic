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

# What kind of record this is. The distinction that matters most to an
# investigator is the first two: a source that records execution, versus a
# source that records what someone typed. Shell history is never promoted to
# execution evidence merely because it contains a command.
EXECUTION_EVIDENCE = "EXECUTION_EVIDENCE"
COMMAND_HISTORY = "COMMAND_HISTORY"
SESSION_EVENT = "SESSION_EVENT"
PROCESS_SNAPSHOT = "PROCESS_SNAPSHOT"
ARTIFACT_OBSERVATION = "ARTIFACT_OBSERVATION"
FINDING = "FINDING"

# How complete the recovered command line is.
EXACT = "EXACT"                      # the source recorded the whole command
PARTIAL = "PARTIAL"                  # some arguments recovered, known to be incomplete
EXECUTABLE_ONLY = "EXECUTABLE_ONLY"  # an image name or path, no arguments
COMMAND_NOT_AVAILABLE = "NOT_AVAILABLE"

# How well the source supports the command it reports.
STRONG = "STRONG"
MODERATE = "MODERATE"
WEAK = "WEAK"

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
    # Command reconstruction. `full_command_line` is what an investigator is
    # shown; it is never shortened to the executable. When the source did not
    # record arguments that is stated, never filled in with a guess.
    "evidence_kind", "full_command_line", "command_source",
    "command_reconstruction_status", "command_evidence_strength",
    "normalized_command", "execution_confirmed",
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
    evidence_kind: str = EXECUTION_EVIDENCE,
    execution_confirmed: bool = False,
    command: dict | None = None,
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
    event["evidence_kind"] = evidence_kind
    # Whether this record's own source establishes that something ran. Command
    # history never does, however complete the command text is.
    event["execution_confirmed"] = execution_confirmed
    event.update(command or describe_command(
        command_line=event.get("command_line"), executable=event.get("executable"),
        process_name=event.get("process_name"), source=source))
    reason = command_unavailable_reason(event["command_reconstruction_status"], source)
    if reason:
        # Always stated under its own key. A reader looking for the command
        # should find the reason it is absent in the same place every time,
        # whatever else the source had to say about arguments.
        policy = event["unavailable"].get("command_line")
        event["unavailable"]["full_command_line"] = f"{reason} {policy}" if policy else reason
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


# Shell operators are part of the evidence: a pipe into a shell, or a
# redirection, changes what a command means. They are preserved verbatim in the
# displayed command and only reduced in the separate search form.
_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)
_PATH_SEGMENT = re.compile(r"(?<![\w.-])(?:/[\w.@+-]+){2,}/?")
_REDIRECT = re.compile(r"\d?>>?&?\d?|(?<!\w)<(?!\w)")


def normalize_for_search(command: str | None) -> str | None:
    """A reduced form for matching, never a replacement for the raw command.

    URLs collapse to URL, deep paths to their basename, redirections to the word
    "redirect", and quotes are dropped, so that a search for "script.py" matches
    `python3 "/home/u/proj/script.py" > /tmp/out`. The original string is always
    kept alongside and is what the investigator is shown.

    Passes run in order: URLs first, because a URL contains slashes that the
    path rule would otherwise chew through.
    """
    if not command:
        return None
    reduced = _URL.sub("URL", command)
    reduced = _PATH_SEGMENT.sub(lambda m: m.group(0).rstrip("/").rsplit("/", 1)[-1], reduced)
    reduced = _REDIRECT.sub(" redirect ", reduced)
    reduced = reduced.replace('"', " ").replace("'", " ")
    return " ".join(reduced.split()) or None


def describe_command(
    *,
    command_line: str | None,
    executable: str | None,
    process_name: str | None,
    source: str,
    status: str | None = None,
    strength: str | None = None,
) -> dict:
    """Decide what the strongest available command information is.

    Returns the fields an investigator-facing view needs, and says plainly when
    only an image name was recorded. It never manufactures arguments and never
    writes something like "python3 <unknown arguments>".
    """
    image = executable or process_name
    if command_line and command_line.strip():
        text = command_line.strip()
        return {
            "full_command_line": text,
            "normalized_command": normalize_for_search(text),
            "command_source": source,
            "command_reconstruction_status": status or EXACT,
            "command_evidence_strength": strength or STRONG,
        }
    return {
        "full_command_line": None,
        "normalized_command": normalize_for_search(image),
        "command_source": source if image else None,
        "command_reconstruction_status": EXECUTABLE_ONLY if image else COMMAND_NOT_AVAILABLE,
        "command_evidence_strength": strength or (WEAK if image else None),
    }


def command_unavailable_reason(status: str, source: str) -> str | None:
    """Plain wording for a command line the source did not record."""
    if status == EXECUTABLE_ONLY:
        return (f"{source} records the executable but not its arguments. The full command line is "
                "not available from this evidence.")
    if status == COMMAND_NOT_AVAILABLE:
        return f"{source} records neither a command line nor an executable path."
    return None
