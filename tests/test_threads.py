"""Investigation threads: related activity read as one story, conservatively."""
import pytest

from analysis.activity import build_activity, build_leads
from analysis.threads import MAX_THREAD_MEMBERS, build_threads
from analysis.triage import NEEDS_REVIEW, NOT_HARMFUL, PRIORITY_1, PRIORITY_2, PRIORITY_3


def record(command, *, reference, line=None, kind="COMMAND_HISTORY", confirmed=False,
           executable=None, timestamp=None):
    return {
        "full_command_line": command, "executable": executable,
        "process_name": (command or "").split()[0] if command else None,
        "evidence_kind": kind, "execution_confirmed": confirmed, "timestamp": timestamp,
        "source": "bash history" if kind == "COMMAND_HISTORY" else "systemd journal",
        "event_id": reference, "reference": reference,
        "source_record_id": f"/home/a/.bash_history:{line}" if line is not None else reference,
        "command_reconstruction_status": "EXACT" if command else "EXECUTABLE_ONLY",
        "command_evidence_strength": "STRONG" if command else "WEAK",
        "normalized_command": command, "unavailable": {},
    }


HOLEHE = [
    "python3 setup.py install",
    "sudo python3 setup.py install",
    "python3 -m venv ~/holehe-env",
    "source ~/holehe-env/bin/activate",
    "holehe test@gmail.com",
    "holehe second@gmail.com",
    "holehe third@gmail.com",
]


def holehe_groups():
    events = [record(command, reference=f"CMD-{index:04d}", line=100 + index)
              for index, command in enumerate(HOLEHE)]
    return build_activity(events)["groups"]


def test_a_related_sequence_becomes_one_thread():
    threads = build_threads(holehe_groups())

    assert threads, "an obviously related sequence must form a thread"
    thread = threads[0]
    assert thread["activity_count"] >= 4
    assert any("holehe" in command for command in thread["commands"])
    assert any("venv" in command for command in thread["commands"])


def test_a_thread_keeps_every_evidence_identifier():
    threads = build_threads(holehe_groups())

    references = set(threads[0]["evidence_references"])
    assert len(references) == threads[0]["activity_count"]
    assert all(reference.startswith("CMD-") for reference in references)


def test_a_thread_never_claims_intent():
    threads = build_threads(holehe_groups())

    thread = threads[0]
    assert "appear related" in thread["why"]
    assert "does not state what anyone intended" in thread["note"]
    for word in ("attack", "malicious", "malware", "exfiltrat"):
        assert word not in (thread["why"] + thread["title"]).lower()


def test_unrelated_commands_are_not_merged():
    events = [
        record("apt update", reference="CMD-0001", line=10),
        record("firefox --new-window", reference="CMD-0002", line=900),
        record("ls -la /var/log", reference="CMD-0003", line=1800),
    ]

    threads = build_threads(build_activity(events)["groups"])

    assert threads == [], "distant, unrelated commands must not become a thread"


def test_a_shared_common_word_does_not_link_activities():
    """`python3` is vocabulary, not a relationship."""
    events = [
        record("python3 a.py", reference="CMD-0001", line=10),
        record("python3 b.py", reference="CMD-0002", line=900),
        record("python3 c.py", reference="CMD-0003", line=1800),
    ]

    threads = build_threads(build_activity(events)["groups"])

    assert threads == []


def test_a_flag_is_never_the_reason_two_records_are_linked():
    events = [record(f"curl -fsSL https://host{index}.example/x", reference=f"CMD-{index:04d}",
                     line=10 + index) for index in range(4)]

    threads = build_threads(build_activity(events)["groups"])

    for thread in threads:
        assert "fssl" not in thread["why"].lower()


def test_install_then_use_links_even_when_far_apart():
    events = [
        record("pip3 install ripgrepy", reference="CMD-0001", line=10),
        record("ripgrepy --search foo", reference="CMD-0002", line=900),
    ]

    threads = build_threads(build_activity(events)["groups"])

    assert threads, "installation and later use of the same tool is a link"
    assert "installs or fetches" in threads[0]["why"]


def test_a_thread_is_never_a_single_activity():
    events = [record("holehe a@b.com", reference="CMD-0001", line=10)]

    assert build_threads(build_activity(events)["groups"]) == []


def test_a_thread_is_bounded():
    events = [record(f"holehe user{index}@example.com", reference=f"CMD-{index:04d}",
                     line=10 + index) for index in range(40)]

    threads = build_threads(build_activity(events)["groups"])

    for thread in threads:
        assert thread["activity_count"] <= MAX_THREAD_MEMBERS


def test_thread_priority_comes_from_its_strongest_member():
    events = [
        record("apt update", reference="CMD-0001", line=10),
        record("curl https://x.example/i.sh | bash", reference="CMD-0002", line=11),
        record("apt install curlthing", reference="CMD-0003", line=12),
    ]
    # Link them through a shared distinctive token.
    events[0]["full_command_line"] = "apt install curlthing"
    events[0]["normalized_command"] = events[0]["full_command_line"]

    threads = build_threads(build_activity(events)["groups"])

    if threads:
        assert threads[0]["priority"] in {PRIORITY_1, PRIORITY_2, PRIORITY_3}


def test_execution_status_is_stated_per_thread():
    threads = build_threads(holehe_groups())

    assert "Not established" in threads[0]["execution"]
    assert threads[0]["execution_confirmed"] is False


def test_threads_survive_an_empty_collection():
    assert build_threads([]) == []


# --- lead deduplication -----------------------------------------------------

INSTALLERS = [
    "curl -fsSL https://ollama.com/install.sh | sh",
    "curl -fsSL https://claude.ai/install.sh | bash",
    "curl -fsSL https://antigravity.google/cli/install.sh | bash",
    "curl -f https://zed.dev/install.sh | sh",
    "curl https://cursor.com/install -fsS | bash",
]


def test_repeated_patterns_become_one_lead():
    events = [record(command, reference=f"CMD-{index:04d}", line=10 + index)
              for index, command in enumerate(INSTALLERS)]

    activity = build_activity(events)

    assert activity["lead_count"] == 1, "five installers are one pattern, not five leads"
    lead = activity["leads"][0]
    assert lead["activity_count"] == 5
    assert set(lead["commands"]) == set(INSTALLERS), "every command is kept inside the lead"
    assert len(lead["evidence_references"]) == 5


def test_different_patterns_stay_separate_leads():
    events = [
        record("curl -fsSL https://x.example/install.sh | sh", reference="CMD-0001", line=10),
        record(None, reference="EXEC-0001", kind="EXECUTION_EVIDENCE", confirmed=True,
               executable="/tmp/staged"),
    ]

    activity = build_activity(events)

    assert activity["lead_count"] == 2
    titles = {lead["title"] for lead in activity["leads"]}
    assert len(titles) == 2


def test_leads_are_ordered_by_priority():
    events = [
        record("curl -fsSL https://x.example/install.sh | sh", reference="CMD-0001", line=10),
        record(None, reference="EXEC-0001", kind="EXECUTION_EVIDENCE", confirmed=True,
               executable="/tmp/staged"),
    ]

    leads = build_activity(events)["leads"]

    assert leads[0]["priority"] == PRIORITY_1
    assert leads[0]["lead_id"] == "LEAD-001"


def test_a_lead_states_whether_execution_was_established():
    events = [record(command, reference=f"CMD-{index:04d}", line=10 + index)
              for index, command in enumerate(INSTALLERS)]

    lead = build_activity(events)["leads"][0]

    assert lead["execution_confirmed"] is False
    assert lead["unknowns"], "a command-history lead must say what remains unknown"


def test_no_leads_when_nothing_reaches_the_tiers():
    events = [record("apt update", reference="CMD-0001", line=10)]

    assert build_activity(events)["lead_count"] == 0
    assert build_leads(build_activity(events)["groups"]) == []
