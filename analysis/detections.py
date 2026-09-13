"""
Explainable detections over driver and memory evidence.

Each rule here is a named, versioned statement with three parts kept visible:
what was observed, which rule fired, and how far the evidence goes. A rule never
concludes that a host was compromised. It says what matched, against what
reference, and what an investigator would have to check next.

Two rules deliberately do less than they could:

  * A driver match is reported as *a driver known to be abused is present*,
    never as *the driver was abused here*. Presence is a reason to look at the
    signing, load time and loading process, not a verdict.
  * Memory findings depend entirely on the provenance of the image. A finding
    derived from a fixture is labelled as such and can never be read as evidence
    about a real host.
"""

from __future__ import annotations

from .correlation import (
    HIGH, INFO, LOW, MEDIUM, OBSERVED_DIRECTLY, QUALIFIED, SINGLE_SOURCE, _finding, _reference,
)
from .triage import NEEDS_REVIEW, NOT_HARMFUL, POTENTIALLY_HARMFUL

DETECTION_RULESET_VERSION = 1

#: rule id -> what it looks for. Printed in the report so a finding can be
#: traced back to the rule that produced it.
RULES = {
    "DRV-001": "A loaded driver matches a known-abused driver reference by SHA-256.",
    "DRV-002": "A loaded driver matches a known-abused driver reference by filename only.",
    "DRV-003": "The driver reference could not be loaded, so no driver was checked.",
    "MEM-001": "A process in the memory image has no parent process in the same image.",
    "MEM-002": "Memory analysis was requested but no image could be analysed.",
    "MEM-003": "The memory findings come from a fixture, not from a host image.",
}

# Windows kernel processes whose parent legitimately exits, so an absent parent
# is the normal case and not worth an investigator's time.
EXPECTED_ORPHANS = {"system", "smss.exe", "wininit.exe", "csrss.exe", "explorer.exe", "init",
                    "systemd", "kthreadd"}

MAX_FINDINGS_PER_RULE = 25


def _rule(rule_id):
    return {"kind": "detection_rule", "id": rule_id, "description": RULES[rule_id],
            "ruleset_version": DETECTION_RULESET_VERSION}


def detect_drivers(drivers: dict | None) -> list:
    """Findings from the loaded-driver inventory.

    The reference is a public catalogue of drivers that have been abused. A
    match means this machine has a driver that has been abused elsewhere. It
    does not mean it was abused here, and the explanation says so every time.
    """
    if not drivers or drivers.get("classification") == "UNAVAILABLE":
        return []
    findings = []
    if drivers.get("reference", {}).get("loaded") is False:
        return [_finding(
            "driver_reference_unavailable", INFO,
            "Loaded drivers were not checked against the known-abused reference",
            ("The driver risk reference could not be read, so the drivers on this host were "
             "inventoried but not compared against anything. Absence of driver findings in this "
             "report therefore means nothing was checked, not that nothing matched."),
            triage=NEEDS_REVIEW, confidence=QUALIFIED, classification="UNAVAILABLE",
            action="Reinstall the reference data and re-run the driver collection.",
            unknowns=("Whether any loaded driver appears in the known-abused catalogue.",),
            references=[_rule("DRV-003")])]

    for record in (drivers.get("drivers") or [])[:MAX_FINDINGS_PER_RULE * 2]:
        verdict = record.get("verification", {})
        if verdict.get("result") != "MATCHED":
            continue
        by_hash = verdict.get("confidence") == "high"
        rule = "DRV-001" if by_hash else "DRV-002"
        name = record.get("name") or record.get("path") or "unnamed driver"
        findings.append(_finding(
            "known_abused_driver_present", HIGH if by_hash else MEDIUM,
            f"A driver matching a known-abused driver is loaded: {name}",
            (f"{name} matches an entry in the known-abused driver reference "
             + ("by SHA-256, which identifies the exact file." if by_hash else
                "by filename only. A filename match does not establish that this is the same "
                "file; the bytes were not compared.")
             + " Drivers appear in that reference because they have been abused somewhere, not "
               "because they are malicious in themselves. Several are legitimate, signed vendor "
               "drivers that remain in use for their intended purpose. This finding says the "
               "driver is present, not that it was abused on this host."),
            triage=POTENTIALLY_HARMFUL if by_hash else NEEDS_REVIEW,
            confidence=OBSERVED_DIRECTLY if by_hash else SINGLE_SOURCE,
            classification="CURRENT_OBSERVATION", corroborated=by_hash,
            action=("Check the driver's signature, when it was loaded, and which process loaded "
                    "it. Compare that against the machine's expected software."),
            unknowns=("Whether this driver was loaded for its legitimate purpose or misused.",
                      "When and by what the driver was loaded; the inventory records presence, "
                      "not load history."),
            why=(f"{name} matches the known-abused driver reference "
                 + ("by exact hash." if by_hash else "by name alone.")),
            references=[_rule(rule),
                        _reference("driver", record.get("reference") or name,
                                   path=record.get("path"), sha256=record.get("sha256"))]))
        if len(findings) >= MAX_FINDINGS_PER_RULE:
            break
    return findings


def detect_memory(memory: dict | None) -> list:
    """Findings from a memory image, always qualified by its provenance."""
    if not memory:
        return []
    provenance = memory.get("provenance")

    if provenance == "UNAVAILABLE" or memory.get("classification") == "UNAVAILABLE":
        return [_finding(
            "memory_not_analysed", INFO, "No memory image was analysed",
            ("Memory analysis was requested but produced nothing: either no image was supplied or "
             "no analysis tool was available. Nothing in this report is based on memory, and no "
             "conclusion should be drawn from the absence of memory findings."),
            triage=NEEDS_REVIEW, confidence=QUALIFIED, classification="UNAVAILABLE",
            action="Supply a memory image and install a supported analysis tool, then re-run.",
            unknowns=("Everything memory would have shown.",),
            references=[_rule("MEM-002")])]

    findings = []
    if provenance == "FIXTURE":
        findings.append(_finding(
            "memory_findings_from_fixture", INFO,
            "Memory findings in this report come from a fixture, not a host",
            ("The memory analysis in this investigation was performed on a test fixture. It "
             "demonstrates the analysis path and must not be read as evidence about any real "
             "machine."),
            triage=NOT_HARMFUL, confidence=OBSERVED_DIRECTLY, classification="INFERRED",
            action="Disregard memory findings when assessing this host.",
            references=[_rule("MEM-003")]))

    processes = memory.get("processes") or []
    known = {process.get("pid") for process in processes}
    for process in processes[:MAX_FINDINGS_PER_RULE * 4]:
        parent, name = process.get("ppid"), (process.get("name") or "").lower()
        if parent is None or parent in known or parent == 0 or name in EXPECTED_ORPHANS:
            continue
        findings.append(_finding(
            "memory_orphan_process", LOW,
            f"A process in the memory image has no parent in the image: {process.get('name')}",
            (f"{process.get('name')} (pid {process.get('pid')}) records parent pid {parent}, and "
             f"no process with that pid appears in the same image. That happens routinely when the "
             "parent exited before the image was taken, and it is also what a process whose parent "
             "was terminated looks like. The image alone does not separate the two."
             + (" These findings come from a fixture." if provenance == "FIXTURE" else "")),
            triage=NEEDS_REVIEW, confidence=SINGLE_SOURCE,
            classification="INFERRED" if provenance == "FIXTURE" else "HISTORICAL_EVIDENCE",
            action="Compare against execution evidence from the same period to see what the parent "
                   "was and when it exited.",
            unknowns=("Why the parent is absent from the image.",),
            why=f"Parent pid {parent} of {process.get('name')} is not present in the image.",
            references=[_rule("MEM-001"),
                        _reference("memory_process", f"pid-{process.get('pid')}",
                                   name=process.get("name"), pid=process.get("pid"))]))
        if len(findings) >= MAX_FINDINGS_PER_RULE:
            break
    return findings


def detect(*, drivers=None, memory=None) -> list:
    """Every detection this build can make from supplementary evidence."""
    return detect_drivers(drivers) + detect_memory(memory)
