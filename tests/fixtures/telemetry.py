"""
Deterministic telemetry fixtures.

These are hand-built records in the exact shape each real source produces, so
collector parsing, correlation and finding generation can be exercised without
a live host. They are fixtures, not recordings of real Windows telemetry, and
nothing here should be read as evidence that the Windows collectors have been
run against a real Windows machine.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

BASE = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def at(minutes: int) -> datetime:
    return BASE + timedelta(minutes=minutes)


def micros(moment: datetime) -> str:
    return str(int(moment.timestamp() * 1_000_000))


# --- Linux: systemd journal -------------------------------------------------

def journal_record(*, executable, comm, pid, minutes, cursor, boot="boot-1", unit=None, cmdline=None, uid="1000"):
    record = {
        "__CURSOR": cursor,
        "__REALTIME_TIMESTAMP": micros(at(minutes)),
        "_BOOT_ID": boot,
        "_PID": str(pid),
        "_UID": uid,
        "_COMM": comm,
        "_EXE": executable,
    }
    if unit:
        record["_SYSTEMD_UNIT"] = unit
    if cmdline:
        record["_CMDLINE"] = cmdline
    return json.dumps(record)


def journal_output(records) -> str:
    return "\n".join(records) + "\n"


#: A realistic journal: one ordinary daemon, one interpreter, one image that no
#: longer exists on disk, a duplicate record for an existing process instance,
#: a malformed line, and a record with no _EXE at all.
JOURNAL_LINES = [
    journal_record(executable="/usr/sbin/sshd", comm="sshd", pid=900, minutes=0, cursor="c1", unit="ssh.service", uid="0"),
    journal_record(executable="/usr/sbin/sshd", comm="sshd", pid=900, minutes=5, cursor="c2", unit="ssh.service", uid="0"),
    journal_record(executable="/usr/bin/python3", comm="python3", pid=1200, minutes=10, cursor="c3",
                   cmdline="python3 deploy.py --token s3cr3tvalue"),
    journal_record(executable="/tmp/staged-installer", comm="staged-installer", pid=1300, minutes=15, cursor="c4"),
    journal_record(executable="/usr/bin/removed-tool", comm="removed-tool", pid=1400, minutes=20, cursor="c5"),
    '{"__CURSOR":"c6","__REALTIME_TIMESTAMP":"not-a-number","_EXE":"/usr/bin/broken"}',
    "{ this is not json",
    '{"__CURSOR":"c7","__REALTIME_TIMESTAMP":"' + micros(at(25)) + '","_COMM":"kernel"}',
]


def journal_runner(lines=None, *, status="AVAILABLE"):
    """A `run_command` stand-in that answers journalctl and nothing else."""
    payload = journal_output(lines if lines is not None else JOURNAL_LINES)

    def runner(argv, timeout=None):
        if argv and argv[0] == "journalctl":
            return status, payload if status == "AVAILABLE" else ""
        return "NOT_AVAILABLE", ""
    return runner


# --- Linux: shell history ---------------------------------------------------

BASH_HISTORY_TIMESTAMPED = (
    f"#{int(at(1).timestamp())}\n"
    "ls -la /var/log\n"
    f"#{int(at(2).timestamp())}\n"
    "mysql -u root --password=hunter2 -h db\n"
)

BASH_HISTORY_PLAIN = "cd /tmp\n./staged-installer\nwhoami\n"

ZSH_HISTORY = (
    f": {int(at(3).timestamp())}:0;curl -s https://example.invalid/setup.sh\n"
    f": {int(at(4).timestamp())}:0;export API_KEY=abcdef123456\n"
)


# --- Linux: audit log -------------------------------------------------------

def audit_line(*, seconds, serial, executable, comm, pid, ppid, uid=1000):
    return (f'type=SYSCALL msg=audit({seconds}.123:{serial}): arch=c000003e syscall=59 success=yes '
            f'exit=0 ppid={ppid} pid={pid} auid=1000 uid={uid} gid=1000 comm="{comm}" exe="{executable}" '
            f'key="exec"')


AUDIT_LINES = "\n".join([
    audit_line(seconds=int(at(6).timestamp()), serial=101, executable="/usr/bin/curl", comm="curl", pid=2100, ppid=900),
    audit_line(seconds=int(at(7).timestamp()), serial=102, executable="/tmp/staged-installer",
               comm="staged-installer", pid=2200, ppid=2100),
    'type=SYSCALL msg=audit(bad-timestamp): exe="/usr/bin/broken"',
    'type=USER_LOGIN msg=audit(1.2:3): something else entirely',
]) + "\n"


# --- Windows: event log XML -------------------------------------------------

EVENT_NS = "http://schemas.microsoft.com/win/2004/08/events/event"


def _event(event_id, record_id, moment, data):
    fields = "".join(f'<Data Name="{key}">{value}</Data>' for key, value in data.items())
    return (
        f'<Event xmlns="{EVENT_NS}"><System><EventID>{event_id}</EventID>'
        f'<EventRecordID>{record_id}</EventRecordID>'
        f'<TimeCreated SystemTime="{moment.isoformat().replace("+00:00", "Z")}"/>'
        f'</System><EventData>{fields}</EventData></Event>'
    )


SECURITY_4688 = "".join([
    _event(4688, 5001, at(2), {
        "NewProcessId": "0x4d2", "NewProcessName": r"C:\Windows\System32\cmd.exe",
        "ProcessId": "0x1a4", "ParentProcessName": r"C:\Windows\explorer.exe",
        "SubjectUserName": "analyst", "SubjectDomainName": "WORKSTATION",
        "TokenElevationType": "%%1936",
    }),
    _event(4688, 5002, at(8), {
        "NewProcessId": "0x4d3", "NewProcessName": r"C:\Users\analyst\AppData\Local\Temp\stage.exe",
        "ProcessId": "0x4d2", "ParentProcessName": r"C:\Windows\System32\cmd.exe",
        "SubjectUserName": "analyst", "SubjectDomainName": "WORKSTATION",
        "CommandLine": r"stage.exe --password Hunter2 --target C:\data",
    }),
])

SYSMON_1 = _event(1, 7001, at(9), {
    "UtcTime": at(9).strftime("%Y-%m-%d %H:%M:%S.000"),
    "ProcessGuid": "{11111111-2222-3333-4444-555555555555}",
    "ProcessId": "4242", "Image": r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
    "CommandLine": "powershell.exe -enc ZQBjAGgAbwA=",
    "User": "WORKSTATION\\analyst", "ParentProcessId": "1234",
    "ParentImage": r"C:\Windows\System32\cmd.exe",
    "Hashes": "SHA256=ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789,MD5=00112233445566778899AABBCCDDEEFF",
})

POWERSHELL_4104 = _event(4104, 9001, at(11), {
    "ScriptBlockText": "Invoke-WebRequest -Uri https://example.invalid -Headers @{ Token = 'abc123secret' }",
    "ScriptBlockId": "{99999999-8888-7777-6666-555555555555}", "MessageNumber": "1",
    "Path": r"C:\scripts\collect.ps1",
})


def channel_runner(responses):
    """A `run_command` stand-in mapping event log channel name to XML output."""
    def runner(argv, timeout=None):
        if not argv or argv[0] != "wevtutil":
            return "NOT_AVAILABLE", ""
        channel = argv[2]
        if channel not in responses:
            return "NOT_AVAILABLE", ""
        value = responses[channel]
        if isinstance(value, tuple):
            return value
        return "AVAILABLE", value
    return runner


# --- Windows: UserAssist registry -------------------------------------------

import struct

FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


def userassist_value(run_count: int, moment: datetime) -> bytes:
    filetime = int((moment - FILETIME_EPOCH).total_seconds() * 10_000_000)
    blob = bytearray(72)
    struct.pack_into("<I", blob, 4, run_count)
    struct.pack_into("<Q", blob, 60, filetime)
    return bytes(blob)


class FakeRegistry:
    """Minimal winreg stand-in driven by a nested dict."""

    HKEY_CURRENT_USER = "HKCU"

    def __init__(self, tree):
        self.tree = tree

    class _Key:
        def __init__(self, node):
            self.node = node

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def OpenKey(self, root, path):
        # winreg accepts either a predefined root handle or an already-open key,
        # and the collector uses both.
        node = self.tree if root == self.HKEY_CURRENT_USER else root.node
        for part in path.replace("/", "\\").split("\\"):
            if part not in node:
                raise OSError(f"missing key {path}")
            node = node[part]
        return self._Key(node)

    def EnumKey(self, key, index):
        subkeys = [name for name, value in key.node.items() if isinstance(value, dict)]
        if index >= len(subkeys):
            raise OSError("no more keys")
        return subkeys[index]

    def EnumValue(self, key, index):
        values = [(name, value) for name, value in key.node.items() if not isinstance(value, dict)]
        if index >= len(values):
            raise OSError("no more values")
        name, value = values[index]
        return name, value, 3


def userassist_tree():
    # "P:\Znyjner\fgntr.rkr" is ROT13 for "C:\Malware\stage.exe"; UserAssist
    # stores value names ROT13-encoded.
    return {
        "Software": {"Microsoft": {"Windows": {"CurrentVersion": {"Explorer": {"UserAssist": {
            "{GUID-A}": {"Count": {
                "P:\\Hfref\\nanylfg\\Qbjaybnqf\\ercbeg.rkr": userassist_value(3, at(12)),
                "too-short": b"\x00\x01",
            }},
        }}}}}},
    }


# --- Realistic command fixtures ---------------------------------------------
#
# Test data for classification and reporting. Nothing here is malicious: these
# are ordinary developer and administrator commands, and the point of several of
# them is that JOCKY must NOT flag them merely because they contain `curl`,
# `sudo`, `python3` or `ssh`.

COMMANDS = [
    "git clone https://github.com/example/project.git",
    "python3 script.py --target example.com --output results.json",
    "wget https://example.com/file.zip -O /tmp/file.zip",
    "curl -fsSL https://example.com/install.sh | sudo bash",
    "sudo apt update",
    "apt update",
    "npm install --save-dev eslint",
    "holehe example@gmail.com --only-used",
    "ssh -i ~/.ssh/id_ed25519 deploy@example.com",
    'sudo python3 "/home/user/test.py" --url "https://example.com/a" > /tmp/out.txt 2>&1',
    "ls -la /var/log",
]

BASH_HISTORY_COMMANDS = "\n".join(COMMANDS) + "\n"


def bash_history_with_times(commands=None, *, start=1):
    """Timestamped bash history, one `#epoch` line before each command."""
    commands = commands or COMMANDS
    lines = []
    for offset, command in enumerate(commands, start=start):
        lines.append(f"#{int(at(offset).timestamp())}")
        lines.append(command)
    return "\n".join(lines) + "\n"


#: Repetition, for the grouping rules: the same command many times, and two
#: `wget` calls that differ only by URL and must stay distinguishable.
REPEATED_HISTORY = "\n".join(
    ["apt update"] * 5
    + ["wget https://example.com/A.zip -O /tmp/A.zip",
       "wget https://example.com/B.zip -O /tmp/B.zip"]
) + "\n"
