"""
Three-way investigator triage.

These are triage categories, not verdicts. "Potentially harmful" means the
collected evidence gives a concrete reason to look, and "not harmful based on
available evidence" means nothing in what was collected stood out -- which is
not the same as proven safe. Every classification carries the reason it was
reached and the evidence it rests on.

Nothing here decides that something is malware. A single keyword never
classifies anything: `python`, `wget`, `curl`, `sudo`, `nc` and `ssh` are
ordinary tools, and a rule that fires on their name alone would bury an
investigator in noise. Concern requires a combination -- an untrusted fetch
piped straight into an interpreter, an image running from a writable temporary
directory, a download target that is later executed.
"""

from __future__ import annotations

import re

from .execution_model import (
    COMMAND_HISTORY, EXECUTION_EVIDENCE, SESSION_EVENT, STRONG,
)

POTENTIALLY_HARMFUL = "POTENTIALLY_HARMFUL"
NOT_HARMFUL = "NOT_HARMFUL_ON_AVAILABLE_EVIDENCE"
NEEDS_REVIEW = "NEEDS_REVIEW"

LABELS = {
    POTENTIALLY_HARMFUL: "Potentially harmful",
    NOT_HARMFUL: "Not harmful based on available evidence",
    NEEDS_REVIEW: "Not sure / needs review",
}

PRIORITY = {POTENTIALLY_HARMFUL: 0, NEEDS_REVIEW: 1, NOT_HARMFUL: 2}

# Writable or transient locations. Running from one is worth a look; plenty of
# installers and build tools legitimately do.
_TRANSIENT = re.compile(r"(?i)(^|[\s\"'=])(/tmp/|/var/tmp/|/dev/shm/|~/Downloads/|"
                        r"[A-Z]:\\+.*\\(temp|tmp|downloads)\\)")

# A fetch whose output is handed straight to an interpreter, with no chance for
# anyone to read what arrived first.
_FETCH_TO_INTERPRETER = re.compile(
    r"(?i)\b(curl|wget|iwr|invoke-webrequest)\b[^|]*\|\s*(sudo\s+)?"
    r"(bash|sh|zsh|dash|python3?|perl|ruby|node|powershell|pwsh)\b")

# A fetch that writes somewhere transient.
_FETCH_TO_TRANSIENT = re.compile(
    r"(?i)\b(curl|wget)\b.*?(-O|-o|--output|>)\s*[\"']?(/tmp/|/var/tmp/|/dev/shm/|\S*\\temp\\)")

_ENCODED_POWERSHELL = re.compile(r"(?i)\b(powershell|pwsh)\b[^|]*\s-(e|en|enc|encodedcommand)\b")
_REMOTE_SCRIPT_EXEC = re.compile(r"(?i)\b(bash|sh|python3?|node|perl|ruby)\s+<\(\s*(curl|wget)")

# Everyday maintenance. Recognised so routine noise can be set aside, never used
# to declare anything safe.
_ROUTINE = (
    (re.compile(r"(?i)^\s*(sudo\s+)?(apt|apt-get|aptitude|dnf|yum|zypper|pacman|snap|flatpak)\b"),
     "package management"),
    (re.compile(r"(?i)^\s*(sudo\s+)?(pip3?|pipx|npm|yarn|pnpm|cargo|gem|go)\s+(install|add|update|upgrade|ci|build|test)\b"),
     "language package management"),
    (re.compile(r"(?i)^\s*(sudo\s+)?systemctl\s+(status|is-active|list-units|show)\b"), "service inspection"),
    (re.compile(r"(?i)^\s*(ls|ll|cd|pwd|clear|exit|echo|cat|less|more|head|tail|which|whoami|date|df|du|free|uname|man|history)\b"),
     "shell navigation and inspection"),
    (re.compile(r"(?i)^\s*git\s+(clone|pull|fetch|status|log|diff|add|commit|push|checkout|branch)\b"),
     "version control"),
    (re.compile(r"(?i)^\s*(sudo\s+)?(mkdir|cp|mv|touch|chmod|chown)\b"), "routine file management"),
)


class Classification:
    """One triage decision, with the reason and the evidence behind it."""

    __slots__ = ("category", "reason", "evidence_references", "signals")

    def __init__(self, category, reason, *, evidence_references=(), signals=()):
        self.category = category
        self.reason = reason
        self.evidence_references = list(evidence_references)
        self.signals = list(signals)

    @property
    def label(self):
        return LABELS[self.category]

    @property
    def priority(self):
        return PRIORITY[self.category]

    def to_dict(self):
        return {"category": self.category, "label": self.label, "reason": self.reason,
                "priority": self.priority, "signals": self.signals,
                "evidence_references": self.evidence_references}


def _reference(event):
    return [{"kind": "execution_event", "id": event.get("reference") or event.get("event_id"),
             "source": event.get("source")}]


def classify_event(event, *, artifacts_by_path=None) -> Classification:
    """Classify one activity record.

    `artifacts_by_path` lets a command that names a path be related to what was
    actually found there, which is the difference between "downloads to /tmp"
    and "downloads to /tmp, and something was later executed from that path".
    """
    artifacts_by_path = artifacts_by_path or {}
    command = event.get("full_command_line") or ""
    image = event.get("executable") or ""
    kind = event.get("evidence_kind")
    signals = []

    if kind == SESSION_EVENT:
        return Classification(
            NOT_HARMFUL,
            "A login session record. It carries no command and no executable, so there is nothing "
            "in it to raise a concern.",
            evidence_references=_reference(event))

    if command:
        if _FETCH_TO_INTERPRETER.search(command):
            signals.append("remote content piped directly into an interpreter")
        if _FETCH_TO_TRANSIENT.search(command):
            signals.append("download written to a temporary or writable location")
        if _ENCODED_POWERSHELL.search(command):
            signals.append("PowerShell invoked with an encoded command")
        if _REMOTE_SCRIPT_EXEC.search(command):
            signals.append("interpreter run against remotely fetched content")

    if image and _TRANSIENT.search(image):
        signals.append(f"executable runs from a writable or temporary location ({image})")
        record = artifacts_by_path.get(image)
        if record and record.get("collection_status") == "MISSING":
            signals.append("the image is no longer present at that path")

    if signals:
        confirmed = event.get("execution_confirmed")
        qualifier = ("The source records execution, so this ran."
                     if confirmed else
                     "This is command history: the text was entered, but the collected evidence "
                     "does not establish that it ran.")
        return Classification(
            POTENTIALLY_HARMFUL,
            f"{'; '.join(signals).capitalize()}. {qualifier}",
            evidence_references=_reference(event), signals=signals)

    if command:
        for pattern, description in _ROUTINE:
            if pattern.search(command):
                return Classification(
                    NOT_HARMFUL,
                    f"Recognised as {description}, and no suspicious indicator was identified in "
                    "the collected evidence. This describes what was collected, not a guarantee "
                    "about the command.",
                    evidence_references=_reference(event), signals=[description])
        return Classification(
            NEEDS_REVIEW,
            "The command was recorded in full, but nothing in the collected evidence identifies it "
            "as routine or as concerning. An investigator should read it in context.",
            evidence_references=_reference(event))

    if kind == EXECUTION_EVIDENCE:
        return Classification(
            NEEDS_REVIEW,
            f"{event.get('source')} records that {image or event.get('process_name') or 'a process'} "
            "ran, but not the arguments it ran with. There is not enough context here to judge intent.",
            evidence_references=_reference(event))

    return Classification(
        NEEDS_REVIEW,
        "The record carries neither a command line nor an executable path, so intent cannot be "
        "determined from it.",
        evidence_references=_reference(event))


def classify_events(events, *, artifacts=()) -> list[dict]:
    """Classify every activity record, newest-relevant first."""
    by_path = {record["path"]: record for record in artifacts}
    return [classify_event(event, artifacts_by_path=by_path).to_dict() for event in events]


def summarize(classifications) -> dict:
    counts = {POTENTIALLY_HARMFUL: 0, NEEDS_REVIEW: 0, NOT_HARMFUL: 0}
    for item in classifications:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    return {
        "counts": counts,
        "labels": LABELS,
        "note": ("Triage categories, not verdicts. 'Not harmful based on available evidence' means "
                 "nothing in what was collected stood out; it is not a statement that the activity "
                 "was safe."),
    }
