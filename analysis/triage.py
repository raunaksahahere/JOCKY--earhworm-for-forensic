"""
Investigator triage: what the evidence says, and what to look at first.

Two separate judgements, kept apart on purpose.

*Classification* is what the collected evidence supports — potentially harmful,
not harmful on available evidence, or not sure. It never softens because a
record is common.

*Priority* is where an investigator's attention is worth spending. A record can
be honestly "not sure" and still be the nine-hundredth uninteresting system
daemon of the morning. Collapsing the two is what buried real leads under
ordinary OS activity: every confirmed execution whose arguments the source did
not capture landed in "needs review", and there are hundreds of those on any
desktop.

Priority comes from a deterministic score over named signals, and every record
carries the signals that produced it, so "priority 1" is always answerable with
"because of these three things" rather than a number nobody can argue with.

Three rules govern the whole module:

  Unknown is not suspicious.  Missing arguments are a gap in the evidence, not a
  reason for concern. They are recorded as a limitation on the record and they
  never raise priority.

  Context dominates the name.  `curl`, `python3`, `sudo`, `nc` and `ssh` are
  ordinary tools. Concern requires a combination — a remote fetch piped into an
  interpreter, an image running from a writable directory — never a keyword.

  Corroboration raises priority.  One weak signal from one source rarely
  deserves an investigator's morning. The same activity seen by two independent
  sources, or matched to an artifact on disk, usually does.
"""

from __future__ import annotations

import posixpath
import re

from .execution_model import COMMAND_HISTORY, EXECUTION_EVIDENCE, SESSION_EVENT

# What the evidence supports.
POTENTIALLY_HARMFUL = "POTENTIALLY_HARMFUL"
NOT_HARMFUL = "NOT_HARMFUL_ON_AVAILABLE_EVIDENCE"
NEEDS_REVIEW = "NEEDS_REVIEW"

LABELS = {
    POTENTIALLY_HARMFUL: "Potentially harmful",
    NOT_HARMFUL: "Not harmful based on available evidence",
    NEEDS_REVIEW: "Not sure / needs review",
}

# Where attention is worth spending. Distinct from classification.
PRIORITY_1 = "PRIORITY_1"
PRIORITY_2 = "PRIORITY_2"
PRIORITY_3 = "PRIORITY_3"

PRIORITY_LABELS = {
    PRIORITY_1: "Priority 1 — investigate first",
    PRIORITY_2: "Priority 2 — review",
    PRIORITY_3: "Priority 3 — informational",
}
PRIORITY_ORDER = {PRIORITY_1: 0, PRIORITY_2: 1, PRIORITY_3: 2}

# Kept for callers that rank by classification alone.
PRIORITY = {POTENTIALLY_HARMFUL: 0, NEEDS_REVIEW: 1, NOT_HARMFUL: 2}

# Score thresholds. Deliberately coarse: the point is a defensible ordering, not
# a false precision an investigator cannot argue with.
#: How a record is *presented*, which is a different question from what the
#: evidence supports. An investigator opening a collection of two thousand
#: records needs the ones the machine can account for to fall away, but the
#: triage category behind each one is untouched: nothing here changes what
#: JOCKY concluded, only how much of the investigator's attention it asks for.
ROUTINE_RECOGNIZED = "ROUTINE_RECOGNIZED"
NEEDS_ATTENTION = "NEEDS_ATTENTION"
FOR_REVIEW = "FOR_REVIEW"

PRESENTATION_LABELS = {
    ROUTINE_RECOGNIZED: "Routine / recognized",
    FOR_REVIEW: "For review",
    NEEDS_ATTENTION: "Needs attention",
}

ROUTINE_DISCLAIMER = (
    "Routine / recognized means the machine's own records account for this activity and nothing "
    "in the collected evidence raised a concern. It is not a guarantee of safety.")

INVESTIGATE_FIRST_AT = 4
REVIEW_AT = 1

# Directories the operating system owns. An image here was placed by the
# packaging system rather than by whoever was at the keyboard. /usr/local and
# /opt are deliberately absent: they are where locally installed software goes,
# which is exactly the context worth keeping visible.
SYSTEM_DIRECTORIES = (
    "/usr/bin/", "/usr/sbin/", "/usr/lib/", "/usr/libexec/", "/lib/", "/lib64/",
    "/bin/", "/sbin/", "/usr/share/",
)
WINDOWS_SYSTEM_DIRECTORIES = (
    "c:\\windows\\", "c:\\program files\\", "c:\\program files (x86)\\",
)

# Writable or transient locations. Running from one is worth a look; plenty of
# installers and build tools legitimately do.
TRANSIENT_DIRECTORIES = (
    "/tmp/", "/var/tmp/", "/dev/shm/", "/run/shm/", "/downloads/",
    "\\temp\\", "\\tmp\\", "\\appdata\\local\\temp\\", "\\downloads\\",
    "\\users\\public\\", "\\$recycle.bin\\",
)

_FETCH_TO_INTERPRETER = re.compile(
    r"(?i)\b(curl|wget|iwr|invoke-webrequest)\b[^|]*\|\s*(sudo\s+)?"
    r"(bash|sh|zsh|dash|python3?|perl|ruby|node|powershell|pwsh)\b")
_FETCH_TO_TRANSIENT = re.compile(
    r"(?i)\b(curl|wget)\b.*?(-O|-o|--output|>)\s*[\"']?(/tmp/|/var/tmp/|/dev/shm/|\S*\\temp\\)")
_ENCODED_POWERSHELL = re.compile(r"(?i)\b(powershell|pwsh)\b[^|]*\s-(e|en|enc|encodedcommand)\b")
_REMOTE_SCRIPT_EXEC = re.compile(r"(?i)\b(bash|sh|python3?|node|perl|ruby)\s+<\(\s*(curl|wget)")

# A fetch-and-run whose URL is shaped like a vendor install script. This is a
# structural observation about the URL, not a list of trusted vendors: the
# pattern is still reported, it simply does not outrank a genuine lead.
_INSTALLER_URL = re.compile(
    r"(?i)https://[^\s|'\"]*/(install|setup|get)(\.sh|\.ps1|)(\?[^\s|'\"]*)?(?=[\s|'\"]|$)")

_INTERPRETERS = re.compile(
    r"(?i)(^|/|\\)(python[\d.]*|perl|ruby|node|deno|php|bash|sh|zsh|dash|"
    r"powershell(\.exe)?|pwsh(\.exe)?|cscript\.exe|wscript\.exe|mshta\.exe)$")

_ROUTINE = (
    (re.compile(r"(?i)^\s*(sudo\s+)?(apt|apt-get|aptitude|dnf|yum|zypper|pacman|snap|flatpak)\b"),
     "package management"),
    (re.compile(r"(?i)^\s*(sudo\s+)?(pip3?|pipx|npm|yarn|pnpm|cargo|gem|go)\s+(install|add|update|upgrade|ci|build|test|run)\b"),
     "language package management"),
    (re.compile(r"(?i)^\s*(sudo\s+)?systemctl\s+(status|is-active|list-units|show|enable|disable|start|stop|restart)\b"),
     "service management"),
    (re.compile(r"(?i)^\s*(ls|ll|cd|pwd|clear|exit|echo|cat|less|more|head|tail|which|whoami|date|df|du|free|uname|man|history|grep|find|ps|top|htop|nano|vim|vi|code)\b"),
     "shell navigation and inspection"),
    (re.compile(r"(?i)^\s*git\s+(clone|pull|fetch|status|log|diff|add|commit|push|checkout|branch|remote|init|stash|merge|rebase)\b"),
     "version control"),
    (re.compile(r"(?i)^\s*(sudo\s+)?(mkdir|cp|mv|rm|touch|chmod|chown|ln|tar|unzip|zip)\b"),
     "routine file management"),
    (re.compile(r"(?i)^\s*(sudo\s+)?(docker|podman|kubectl|make|cmake|gradle|mvn|flutter|dart)\b"),
     "development tooling"),
)


HIGH_CONFIDENCE = "HIGH"

#: Plain-language names for how something was recognized, so the reason an
#: investigator reads is a sentence rather than an identifier.
_BASIS_PHRASES = {
    "package_manager_ownership": "the package manager's record of which package owns this path",
    "snap_metadata": "the installed snap's own metadata",
    "vendor_layout": "the vendor's installation layout and its marker file",
    "trusted_system_location": "its location in an OS-managed directory",
}


def _basis_phrase(recognition):
    codes = recognition.get("basis_codes") or []
    phrases = [_BASIS_PHRASES.get(code, code) for code in codes]
    return " and ".join(phrases) if phrases else "recognition"


def _lower(path):
    return (path or "").replace("\\", "/").lower() if "/" in (path or "") else (path or "").lower()


def in_system_location(path: str | None) -> bool:
    """True when an image sits in a directory the OS packaging owns."""
    if not path:
        return False
    lowered = (path or "").lower()
    forward = lowered.replace("\\", "/")
    return (any(forward.startswith(prefix) for prefix in SYSTEM_DIRECTORIES)
            or any(lowered.startswith(prefix) for prefix in WINDOWS_SYSTEM_DIRECTORIES))


def transient_location(path: str | None) -> str | None:
    """Name the writable or transient directory an image sits in, if any."""
    if not path:
        return None
    lowered = (path or "").lower()
    forward = lowered.replace("\\", "/")
    best = None
    for prefix in TRANSIENT_DIRECTORIES:
        needle = prefix.replace("\\", "/").lower()
        if needle in forward and (best is None or len(needle) > len(best)):
            best = needle
    return best.strip("/") if best else None


def is_interpreter(path: str | None, name: str | None) -> bool:
    for candidate in (name, posixpath.basename(_lower(path))):
        if candidate and _INTERPRETERS.search(candidate):
            return True
    return False


class Signal:
    """One named reason, with the weight it contributes to priority."""

    __slots__ = ("name", "weight", "detail")

    def __init__(self, name, weight, detail):
        self.name, self.weight, self.detail = name, weight, detail

    def to_dict(self):
        return {"name": self.name, "weight": self.weight, "detail": self.detail}


class Classification:
    """One triage decision: what the evidence says, and what to look at first."""

    __slots__ = ("category", "reason", "evidence_references", "signals", "limitations",
                 "score", "priority", "recommended_action", "unknowns", "presentation",
                 "presentation_reason")

    def __init__(self, category, reason, *, evidence_references=(), signals=(),
                 limitations=(), score=0, priority=PRIORITY_3, recommended_action=None,
                 unknowns=(), presentation=None, presentation_reason=None):
        self.category = category
        self.reason = reason
        self.evidence_references = list(evidence_references)
        self.signals = list(signals)
        self.limitations = list(limitations)
        self.score = score
        self.priority = priority
        self.recommended_action = recommended_action
        self.unknowns = list(unknowns)
        self.presentation = presentation or (
            ROUTINE_RECOGNIZED if category == NOT_HARMFUL
            else NEEDS_ATTENTION if category == POTENTIALLY_HARMFUL else FOR_REVIEW)
        self.presentation_reason = presentation_reason or reason

    @property
    def presentation_label(self):
        return PRESENTATION_LABELS[self.presentation]

    @property
    def label(self):
        return LABELS[self.category]

    @property
    def priority_label(self):
        return PRIORITY_LABELS[self.priority]

    @property
    def priority_rank(self):
        return PRIORITY_ORDER[self.priority]

    def to_dict(self):
        return {
            "category": self.category,
            "label": self.label,
            "reason": self.reason,
            # Retained so existing callers that sort by classification keep working.
            "priority": PRIORITY[self.category],
            "investigator_priority": self.priority,
            "priority_label": self.priority_label,
            "priority_rank": self.priority_rank,
            "score": self.score,
            "presentation": self.presentation,
            "presentation_label": self.presentation_label,
            "presentation_reason": self.presentation_reason,
            "signals": [signal.to_dict() if isinstance(signal, Signal) else signal
                        for signal in self.signals],
            "why": [signal.detail if isinstance(signal, Signal) else str(signal)
                    for signal in self.signals],
            "limitations": self.limitations,
            "unknowns": self.unknowns,
            "recommended_action": self.recommended_action,
            "evidence_references": self.evidence_references,
        }


def _reference(event):
    references = [{"kind": "execution_event",
                   "id": event.get("reference") or event.get("event_id"),
                   "source": event.get("source")}]
    return references


def _limitations_for(event) -> list[str]:
    """Gaps in the record. These never raise priority; they are stated instead.

    A source that records execution but not arguments leaves an investigator
    less to work with. That is a limitation of the telemetry, not a property of
    the activity, and treating it as a reason for review is what produced
    hundreds of uninteresting "needs review" rows.
    """
    notes = []
    status = event.get("command_reconstruction_status")
    if status in {"EXECUTABLE_ONLY", "NOT_AVAILABLE"}:
        notes.append(f"Execution arguments were not captured by {event.get('source')}.")
    if status == "PARTIAL":
        notes.append(f"{event.get('source')} recorded only part of the command line.")
    if not event.get("timestamp"):
        notes.append("This source does not record a per-entry timestamp.")
    unavailable = event.get("unavailable") or {}
    if "command_line_secrets" in unavailable:
        notes.append("Values resembling credentials were masked before storage.")
    return notes


def classify_event(event, *, artifacts_by_path=None, source_count=1, correlated_artifact=None):
    """Classify one activity record and decide how urgently it deserves attention.

    `source_count` is how many independent sources named this executable, and
    `correlated_artifact` the artifact record matching its path, if any. Both
    come from the surrounding collection; neither is invented here.
    """
    artifacts_by_path = artifacts_by_path or {}
    command = event.get("full_command_line") or ""
    image = event.get("executable") or ""
    name = event.get("process_name")
    kind = event.get("evidence_kind")
    confirmed = bool(event.get("execution_confirmed"))
    record = correlated_artifact or artifacts_by_path.get(image)
    limitations = _limitations_for(event)
    signals: list[Signal] = []
    unknowns: list[str] = []

    if kind == SESSION_EVENT:
        return Classification(
            NOT_HARMFUL,
            "A login session record. It carries no command and no executable, so there is nothing "
            "in it to raise a concern.",
            evidence_references=_reference(event), limitations=limitations,
            priority=PRIORITY_3, score=0)

    # --- concern signals, all of which require structure rather than a name ---
    installer_like = False
    if command:
        if _FETCH_TO_INTERPRETER.search(command) or _REMOTE_SCRIPT_EXEC.search(command):
            installer_like = bool(_INSTALLER_URL.search(command))
            signals.append(Signal(
                "remote_content_to_interpreter", 3,
                "Remote content is piped directly into an interpreter, so nothing inspects what "
                "arrived before it runs."))
        if _FETCH_TO_TRANSIENT.search(command):
            signals.append(Signal(
                "download_to_writable_location", 2,
                "A download is written to a temporary or writable location."))
        if _ENCODED_POWERSHELL.search(command):
            signals.append(Signal(
                "encoded_powershell", 3,
                "PowerShell was invoked with an encoded command, which hides the script text."))

    transient = transient_location(image)
    if transient:
        signals.append(Signal(
            "execution_from_writable_location", 3,
            f"The image runs from '{transient}', a location any unprivileged user can write to."))
        if record and record.get("collection_status") == "MISSING":
            signals.append(Signal(
                "image_absent_after_execution", 1,
                "The image named by the evidence is no longer present at that path."))

    if signals:
        # Corroboration only matters once there is something to corroborate.
        if confirmed:
            signals.append(Signal(
                "execution_confirmed", 1,
                f"{event.get('source')} records this as having run, not merely as entered."))
        if source_count > 1:
            signals.append(Signal(
                "corroborated_across_sources", 2,
                f"{source_count} independent sources name this executable."))
        if record and record.get("collection_status") == "COLLECTED" and record.get("hash"):
            signals.append(Signal(
                "artifact_correlated", 2,
                f"An artifact was observed and hashed at the same path ({record.get('reference') or record['path']})."))
        if installer_like:
            # Enough to keep an install script out of the investigate-first
            # queue, not enough to bury it: the pattern is still reported and
            # still reviewed, and any corroborating signal lifts it straight
            # back up.
            signals.append(Signal(
                "installer_shaped_source", -1,
                "The URL is shaped like a vendor install script, which is how much ordinary "
                "software is distributed. The pattern is still reported."))

    # --- context that lowers priority, never the classification -------------
    routine_description = None
    for pattern, description in _ROUTINE:
        if command and pattern.search(command):
            routine_description = description
            signals.append(Signal("routine_command", -3,
                                  f"Recognised as {description}."))
            break

    # Recognition is context, never a verdict. It lowers priority the way a
    # system location does, and for the same reason: the machine's own records
    # account for the file. It cannot cancel a concern signal, because weighing
    # them against each other is the whole point of scoring rather than
    # short-circuiting -- a recognized interpreter fetching a remote script is
    # still a recognized interpreter fetching a remote script.
    recognition = event.get("recognition") or {}
    if recognition.get("recognized") and recognition.get("confidence") in {"HIGH", "MODERATE"}:
        named = recognition.get("recognized_name") or "known software"
        weight = -2 if recognition.get("confidence") == "HIGH" else -1
        if is_interpreter(image, name):
            # Recognizing the interpreter says nothing about what it was asked
            # to run, which is the only question that matters about one.
            weight = -1
        signals.append(Signal(
            "recognized_software", weight,
            f"The image is accounted for as {named}"
            + (f" {recognition['version']}" if recognition.get("version") else "")
            + f" ({', '.join(recognition.get('basis_codes') or ['recognition'])})."))
    elif recognition.get("basis_codes") == ["trusted_system_location"]:
        unknowns.append(
            "What this file is: it sits in a system directory that no package claims.")

    system_image = in_system_location(image)
    interpreter = is_interpreter(image, name)
    if system_image and not transient:
        # An interpreter in a system directory is still an interpreter: what it
        # ran is the question, and the answer is usually not in the record.
        weight = -1 if interpreter else -3
        signals.append(Signal(
            "system_location", weight,
            f"The image is in a system directory ({posixpath.dirname(_lower(image))}), "
            "placed there by the operating system's packaging."))
    if event.get("systemd_unit"):
        signals.append(Signal(
            "managed_system_service", -2,
            f"Run as the managed service {event['systemd_unit']}."))

    if kind == COMMAND_HISTORY:
        signals.append(Signal(
            "command_history_only", -1,
            "This is command history: the text was entered, which does not establish that it ran."))
        unknowns.append("Whether the command actually ran, succeeded, or ran at this time.")

    if interpreter and not command:
        unknowns.append("Which script or arguments the interpreter was given.")
    if not command and event.get("command_reconstruction_status") in {"EXECUTABLE_ONLY", "NOT_AVAILABLE"}:
        unknowns.append("The command line, which this source does not record.")

    score = sum(signal.weight for signal in signals)
    concerning = [signal for signal in signals if signal.weight > 0
                  and signal.name not in {"execution_confirmed", "corroborated_across_sources",
                                          "artifact_correlated"}]

    # --- classification: what the evidence supports --------------------------
    if concerning:
        category = POTENTIALLY_HARMFUL
        reason = ("; ".join(signal.detail for signal in concerning)
                  + (" The source records execution, so this ran."
                     if confirmed else
                     " This is command history: the text was entered, but the collected evidence "
                     "does not establish that it ran."))
        action = ("Read the full command, then check whether the referenced path exists, what was "
                  "written there, and what ran afterwards in the surrounding execution records.")
    elif routine_description:
        category = NOT_HARMFUL
        reason = (f"Recognised as {routine_description}, and no suspicious indicator was identified "
                  "in the collected evidence. This describes what was collected, not a guarantee "
                  "about the command.")
        action = None
    elif system_image and not interpreter:
        category = NOT_HARMFUL
        reason = ("An operating-system image running from a system directory, with no suspicious "
                  "indicator in the collected evidence. This describes what was collected, not a "
                  "guarantee about the process.")
        action = None
    elif command:
        category = NEEDS_REVIEW
        reason = ("The command was recorded in full, but nothing in the collected evidence "
                  "identifies it as routine or as concerning. An investigator should read it in "
                  "context.")
        action = "Read the command and decide whether it fits the expected use of this machine."
    elif kind == EXECUTION_EVIDENCE:
        category = NEEDS_REVIEW
        reason = (f"{event.get('source')} records that {image or name or 'a process'} ran, but not "
                  "the arguments it ran with. What it did is unknown rather than suspicious.")
        action = "Compare against the software expected on this machine, if it needs resolving."
    else:
        category = NEEDS_REVIEW
        reason = ("The record carries neither a command line nor an executable path, so intent "
                  "cannot be determined from it.")
        action = None

    # --- presentation: how much of the investigator's attention to ask for ---
    presentation, presentation_reason = None, None
    if concerning:
        presentation = NEEDS_ATTENTION
    elif category == NOT_HARMFUL:
        presentation = ROUTINE_RECOGNIZED
        presentation_reason = reason
    elif recognition.get("recognized") and recognition.get("confidence") == HIGH_CONFIDENCE:
        # An interpreter whose arguments were never recorded stays for review:
        # recognizing `python3` says nothing about the script it was handed, and
        # that script is the only thing about it worth knowing.
        if interpreter and not command:
            presentation = FOR_REVIEW
            presentation_reason = (
                f"The image is accounted for as {recognition.get('recognized_name')}, but it is an "
                "interpreter and this source did not record what it was asked to run.")
        else:
            presentation = ROUTINE_RECOGNIZED
            presentation_reason = (
                f"{recognition.get('recognized_name')}"
                + (f" {recognition['version']}" if recognition.get("version") else "")
                + ", accounted for by "
                + _basis_phrase(recognition)
                + ", in its expected location, with no concern signal in the collected evidence.")

    # --- priority: where attention is worth spending -------------------------
    if score >= INVESTIGATE_FIRST_AT:
        priority = PRIORITY_1
    elif score >= REVIEW_AT:
        priority = PRIORITY_2
    else:
        priority = PRIORITY_3

    return Classification(
        category, reason,
        evidence_references=_reference(event), signals=signals, limitations=limitations,
        score=score, priority=priority, presentation=presentation,
        presentation_reason=presentation_reason,
        recommended_action=action if priority in {PRIORITY_1, PRIORITY_2} else None,
        unknowns=unknowns)


def classify_events(events, *, artifacts=()) -> list[dict]:
    by_path = {record["path"]: record for record in artifacts}
    return [classify_event(event, artifacts_by_path=by_path).to_dict() for event in events]


def summarize(classifications) -> dict:
    counts = {POTENTIALLY_HARMFUL: 0, NEEDS_REVIEW: 0, NOT_HARMFUL: 0}
    priorities = {PRIORITY_1: 0, PRIORITY_2: 0, PRIORITY_3: 0}
    for item in classifications:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
        key = item.get("investigator_priority", PRIORITY_3)
        priorities[key] = priorities.get(key, 0) + 1
    return {
        "counts": counts,
        "priorities": priorities,
        "labels": LABELS,
        "priority_labels": PRIORITY_LABELS,
        "note": ("Triage categories, not verdicts. 'Not harmful based on available evidence' means "
                 "nothing in what was collected stood out; it is not a statement that the activity "
                 "was safe. Priority is where attention is worth spending, and is separate from "
                 "what the evidence supports."),
    }
