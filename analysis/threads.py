"""
Investigation threads: related activity read as one story.

An investigator does not want seven separate investigations for what was
obviously one sitting at a keyboard — install a tool, make an environment for
it, run it three times. They want to see that sequence once, as a sequence.

Grouping here is conservative and structural. Two activities are linked only
when they share something distinctive — a tool name, a URL host, a path — *and*
they sit near each other in the record, or one installs what the other runs.
Two commands are never merged because they both happen to contain `python3`.

A thread says "these records appear related". It never says what the person was
trying to do. Intent is not in the evidence, and nothing here invents it.
"""

from __future__ import annotations

import posixpath
import re

from .triage import (
    NEEDS_REVIEW, NOT_HARMFUL, POTENTIALLY_HARMFUL, PRIORITY_1, PRIORITY_2, PRIORITY_3,
    PRIORITY_ORDER,
)

MAX_THREADS = 25
#: A thread is a sitting, not a session log. Capping it stops one shared word
#: from chaining half the history into a single unreadable blob.
MAX_THREAD_MEMBERS = 12
#: A token has to be rare to link anything. One appearing across many distinct
#: activities -- `def`, `exit`, `dev` -- distinguishes nothing, and linking on it
#: merges unrelated work.
MAX_TOKEN_FREQUENCY = 8
MIN_TOKEN_LENGTH = 4
#: How far apart two shell-history lines may sit and still be one sitting.
ADJACENT_LINES = 12
#: How far apart two timestamped records may sit, in seconds.
ADJACENT_SECONDS = 30 * 60

# Words that appear in everything and distinguish nothing. A token has to be
# more specific than this to link two activities.
_COMMON = {
    "sudo", "apt", "apt-get", "install", "update", "upgrade", "remove", "run", "exec",
    "python", "python3", "pip", "pip3", "npm", "node", "git", "bash", "sh", "zsh",
    "curl", "wget", "cd", "ls", "cat", "echo", "make", "cmake", "docker", "sudo",
    "true", "false", "source", "export", "set", "env", "the", "and", "for", "with",
    "usr", "bin", "sbin", "lib", "local", "opt", "var", "etc", "tmp", "home", "src",
    "main", "test", "tests", "build", "dist", "com", "org", "net", "www", "http",
    "https", "file", "files", "dir", "path", "venv", "activate", "setup", "py",
}
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.+-]{2,}")
_URL_HOST = re.compile(r"(?i)\bhttps?://([^/\s:|'\"]+)")
_HISTORY_LINE = re.compile(r":(\d+)$")

_INSTALL_VERB = re.compile(
    r"(?i)\b(install|add|clone|setup\.py|pip3?\s+install|npm\s+i(nstall)?|cargo\s+install|"
    r"go\s+install|gem\s+install|snap\s+install|flatpak\s+install|make\s+install)\b")

# Thread shapes, in the order they are tried. Each is a structural observation
# about the members, never a statement about purpose.
_SHAPES = (
    ("remote_installer",
     "Remote installer commands",
     lambda members, tokens: all(
         any(signal["name"] == "remote_content_to_interpreter"
             for signal in member["classification"]["signals"]) for member in members)),
    ("install_then_use",
     "Tool installation and subsequent use",
     lambda members, tokens: any(_INSTALL_VERB.search(member.get("full_command_line") or "")
                                 for member in members)
     and any(not _INSTALL_VERB.search(member.get("full_command_line") or "")
             and member.get("full_command_line") for member in members)),
    ("unusual_execution",
     "Execution from an unusual location",
     lambda members, tokens: any(
         any(signal["name"] == "execution_from_writable_location"
             for signal in member["classification"]["signals"]) for member in members)),
    ("session",
     "Session activity",
     lambda members, tokens: all(member["evidence_kind"] == "SESSION_EVENT" for member in members)),
    ("system_service",
     "System service activity",
     lambda members, tokens: all(member["evidence_kind"] == "EXECUTION_EVIDENCE"
                                 and member["classification"]["category"] == NOT_HARMFUL
                                 for member in members)),
)


def _tokens(group) -> set[str]:
    """Distinctive words that could genuinely tie two activities together.

    Flags are skipped entirely. `-fsSL` is not a tool, and linking two commands
    because both pass it would produce a thread whose stated reason is nonsense
    even when the grouping happens to look reasonable.
    """
    command = group.get("full_command_line") or ""
    image = group.get("executable") or group.get("process_name") or ""
    found = set()
    for host in _URL_HOST.findall(command):
        found.add(host.lower())
    words = [word for word in command.split() if not word.startswith("-")]
    words.append(posixpath.basename(image))
    for word in words:
        for candidate in _TOKEN.findall(word):
            lowered = candidate.lower().strip(".-_")
            if (len(lowered) >= MIN_TOKEN_LENGTH and lowered not in _COMMON
                    and not lowered.isdigit()):
                found.add(lowered)
                # A tool and the directory named after it are the same subject:
                # `holehe-env` has to match `holehe` or the environment setup
                # and the tool's use read as unrelated activity.
                for part in re.split(r"[-_.]", lowered):
                    if len(part) >= MIN_TOKEN_LENGTH and part not in _COMMON and not part.isdigit():
                        found.add(part)
    return found


def _positions(group) -> list[int]:
    """Shell-history line numbers, which give order when timestamps do not."""
    lines = []
    for record in group.get("records", []):
        match = _HISTORY_LINE.search(str(record.get("source_record_id") or ""))
        if match:
            lines.append(int(match.group(1)))
    return sorted(lines)


def _moments(group) -> list[str]:
    return sorted(record["timestamp"] for record in group.get("records", [])
                  if record.get("timestamp"))


def _near(left_cache, right_cache) -> bool:
    """Whether two activities sit close enough to be one sitting."""
    left_lines, left_times = left_cache
    right_lines, right_times = right_cache
    if left_lines and right_lines:
        if min(abs(a - b) for a in left_lines for b in right_lines) <= ADJACENT_LINES:
            return True
    if left_times and right_times:
        from datetime import datetime

        def parsed(value):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None

        for a in (parsed(value) for value in (left_times[0], left_times[-1])):
            for b in (parsed(value) for value in (right_times[0], right_times[-1])):
                if a and b and abs((a - b).total_seconds()) <= ADJACENT_SECONDS:
                    return True
    return False


def _installs(group, token) -> bool:
    command = group.get("full_command_line") or ""
    return bool(_INSTALL_VERB.search(command)) and token in command.lower()


def _linked(left, right, left_tokens, right_tokens, left_cache, right_cache) -> str | None:
    """Why two activities belong together, or None when they do not."""
    shared = left_tokens & right_tokens
    if not shared:
        return None
    token = sorted(shared)[0]
    # Installation of a tool and later use of the same tool is a link even when
    # the two are far apart in the record.
    if _installs(left, token) or _installs(right, token):
        return f"one installs or fetches '{token}' and another uses it"
    if _near(left_cache, right_cache):
        return f"recorded close together and both reference '{token}'"
    return None


def build_threads(groups) -> list[dict]:
    """Connect related activity into threads, most urgent first."""
    considered = [group for group in groups
                  if group.get("full_command_line") or group.get("executable")][:600]
    raw_tokens = [_tokens(group) for group in considered]

    # Keep only tokens rare enough to mean something. A word shared by dozens of
    # activities is vocabulary, not a relationship.
    frequency = {}
    for token_set in raw_tokens:
        for token in token_set:
            frequency[token] = frequency.get(token, 0) + 1
    tokens = [{token for token in token_set if 2 <= frequency[token] <= MAX_TOKEN_FREQUENCY}
              for token_set in raw_tokens]

    parent = list(range(len(considered)))
    size = [1] * len(considered)

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    # Only activities that share a rare token can possibly be linked, so pair
    # them through an inverted index rather than comparing everything with
    # everything. A rare token appears in at most MAX_TOKEN_FREQUENCY groups,
    # which bounds the work regardless of how large the collection is.
    by_token = {}
    for index, token_set in enumerate(tokens):
        for token in token_set:
            by_token.setdefault(token, []).append(index)

    # Positions and timestamps are read once per activity, not once per pair.
    cache = {index: (_positions(group), _moments(group))
             for index, group in enumerate(considered)}

    reasons = {}
    for candidates in by_token.values():
        for position, i in enumerate(candidates):
            for j in candidates[position + 1:]:
                left, right = find(i), find(j)
                if left == right:
                    continue
                # Refuse the merge rather than grow a thread nobody can read.
                if size[left] + size[right] > MAX_THREAD_MEMBERS:
                    continue
                reason = _linked(considered[i], considered[j], tokens[i], tokens[j],
                                 cache[i], cache[j])
                if reason:
                    parent[right] = left
                    size[left] += size[right]
                    reasons.setdefault(left, reason)

    clusters = {}
    for index, group in enumerate(considered):
        clusters.setdefault(find(index), []).append(group)

    threads = []
    for root, members in clusters.items():
        # A single activity is not a thread; it is already shown on its own.
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda group: (
            group["classification"]["priority_rank"], group.get("first_seen") or "9999"))
        threads.append(_describe(members[:MAX_THREAD_MEMBERS], reasons.get(root, "")))

    threads.sort(key=lambda thread: (thread["priority_rank"], -thread["record_count"]))
    for index, thread in enumerate(threads[:MAX_THREADS], start=1):
        thread["thread_id"] = f"THREAD-{index:03d}"
    return threads[:MAX_THREADS]


def _describe(members, link_reason) -> dict:
    """Name a thread, and say only what its members actually support."""
    shared = set.intersection(*[_tokens(member) for member in members]) if members else set()
    shape, title = "related_activity", "Related activity"
    for key, label, matches in _SHAPES:
        try:
            if matches(members, shared):
                shape, title = key, label
                break
        except (KeyError, TypeError):
            continue

    priority = min((member["classification"]["investigator_priority"] for member in members),
                   key=lambda value: PRIORITY_ORDER[value])
    categories = {member["classification"]["category"] for member in members}
    category = (POTENTIALLY_HARMFUL if POTENTIALLY_HARMFUL in categories
                else NEEDS_REVIEW if NEEDS_REVIEW in categories else NOT_HARMFUL)

    confirmed = [member for member in members if member["execution_confirmed"]]
    references, commands, sources = [], [], []
    timestamps = []
    for member in members:
        for record in member["records"]:
            if record.get("reference"):
                references.append(record["reference"])
            if record.get("timestamp"):
                timestamps.append(record["timestamp"])
        command = member.get("full_command_line") or member.get("executable") or member.get("process_name")
        if command and command not in commands:
            commands.append(command)
        for source in member.get("sources") or ():
            if source not in sources:
                sources.append(source)

    if confirmed and len(confirmed) == len(members):
        execution = "Confirmed for every activity in this thread."
    elif confirmed:
        execution = (f"Confirmed for {len(confirmed)} of {len(members)} activities; the rest are "
                     "command history, which does not establish execution.")
    else:
        execution = "Not established. Every activity here is command history."

    unknowns = sorted({unknown for member in members
                       for unknown in member["classification"].get("unknowns", [])})
    limitations = sorted({note for member in members
                          for note in member["classification"].get("limitations", [])})
    action = next((member["classification"].get("recommended_action") for member in members
                   if member["classification"].get("recommended_action")), None)

    return {
        "thread_id": None,
        "shape": shape,
        "title": title,
        "why": (f"These records appear related: {link_reason}." if link_reason
                else "These records appear related."),
        "shared_terms": sorted(shared)[:6],
        "activity_count": len(members),
        "record_count": sum(member["occurrences"] for member in members),
        "commands": commands[:MAX_THREAD_MEMBERS],
        "execution": execution,
        "execution_confirmed": bool(confirmed),
        "classification": category,
        "priority": priority,
        "priority_rank": PRIORITY_ORDER[priority],
        "sources": sources,
        "first_seen": min(timestamps) if timestamps else None,
        "last_seen": max(timestamps) if timestamps else None,
        "evidence_references": references[:120],
        "unknowns": unknowns,
        "limitations": limitations,
        "recommended_action": action,
        "note": ("A thread states that records appear related. It does not state what anyone "
                 "intended by them."),
    }
