/// The example JOCKY programs shipped with this build.
///
/// GENERATED FROM `examples/*.x` — do not edit by hand. `tests/test_examples.py`
/// asserts that this file still matches those files, so an example cannot be
/// changed in the repository and left stale in the client.
library;

class JockyExample {
  const JockyExample({required this.name, required this.summary, required this.source});

  final String name;
  final String summary;
  final String source;
}

const List<JockyExample> jockyExamples = [
  JockyExample(
    name: 'basic',
    summary: 'Case, target, window, collection, report',
    source: r'''# Basic endpoint investigation.
#
# The shape every JOCKY program shares: whose case this is, which host, how far
# back to look, what evidence to gather, and what to produce at the end.

CASE "IR-2024-001" {
    TITLE "Suspected credential staging on a finance workstation"
    EXAMINER "R. Saha"
    REFERENCE "TICKET-4471"
}

TARGET "workstation-07" PLATFORM linux

WINDOW LAST 24 HOURS

COLLECT SYSTEM
COLLECT PROCESSES
COLLECT EXECUTION
COLLECT NETWORK

TIMELINE SIGNIFICANT LIMIT 200

REPORT SUMMARY AS "IR-2024-001-summary"
''',
  ),
  JockyExample(
    name: 'filtering',
    summary: 'Bindings, lists and boolean predicates',
    source: '''# Filtered investigation.
#
# A binding names the thing being looked for once, so the program reads as the
# question the investigator actually asked. The predicate is a boolean
# expression, because real questions are compound: "a download tool, not the
# package manager, writing into a staging directory".

CASE "IR-2024-002" {
    TITLE "Unexpected outbound transfer from a build host"
    EXAMINER "R. Saha"
}

TARGET "build-02" PLATFORM linux

WINDOW LAST 72 HOURS

LET download_tools = [
    "/usr/bin/curl",
    "/usr/bin/wget",
    "/usr/bin/scp"
]

LET staging_dir = "/tmp"

COLLECT PROCESSES
COLLECT EXECUTION
COLLECT NETWORK

FILTER PATH ONEOF \$download_tools AND NOT USER EQUALS "root"

FILTER (COMMAND CONTAINS "base64" OR COMMAND MATCHES "tar .*-c") AND PATH STARTS \$staging_dir

TIMELINE FULL

REPORT BOTH AS "IR-2024-002-transfer"
''',
  ),
  JockyExample(
    name: 'correlation',
    summary: 'Several sources, correlated',
    source: '''# Cross-source investigation.
#
# One source rarely answers a question on its own. A process that opened a
# socket, and the download that preceded it, are records in two separate
# collections; CORRELATE is how a program states that the investigation cares
# how they relate, rather than leaving that to whoever reads the output.

CASE "IR-2024-003" {
    TITLE "Browser download followed by an outbound connection"
    EXAMINER "R. Saha"
    NOTES "Raised by the endpoint owner after an unfamiliar archive appeared."
}

TARGET "workstation-07" PLATFORM linux

WINDOW LAST 48 HOURS

COLLECT PROCESSES
COLLECT EXECUTION
COLLECT NETWORK
COLLECT BROWSER
COLLECT FILES "/home" "/tmp"

FILTER URL CONTAINS "storage" OR URL MATCHES "[.](zip|tar[.]gz|7z)\$"

CORRELATE PROCESSES WITH NETWORK
CORRELATE BROWSER WITH ARTIFACTS
CORRELATE EXECUTION WITH NETWORK

TIMELINE SIGNIFICANT LIMIT 300

REPORT BOTH AS "IR-2024-003-correlated"
''',
  ),
  JockyExample(
    name: 'multihost',
    summary: 'One playbook across several endpoints',
    source: '''# Multi-endpoint investigation.
#
# The same investigation, stated once, dispatched to several authorized
# endpoints. Each endpoint receives named forensic source requests -- never a
# command -- and the results are correlated across hosts afterwards, which is
# what turns "this host is odd" into "these three hosts are odd in the same way".

CASE "IR-2024-004" {
    TITLE "Shared indicator across the finance subnet"
    EXAMINER "R. Saha"
    REFERENCE "TICKET-4488"
}

TARGET "workstation-07" PLATFORM linux
TARGET "workstation-11" PLATFORM linux
TARGET "build-02" PLATFORM linux

WINDOW LAST 7 DAYS

# One playbook, run on every target, so the hosts stay comparable. A host
# examined differently from its neighbours cannot be correlated with them.
DEFINE host_triage {
    COLLECT SYSTEM
    COLLECT PROCESSES
    COLLECT EXECUTION
    COLLECT NETWORK
}

RUN host_triage

LET indicator = "198.51.100.42"

FILTER ADDRESS EQUALS \$indicator OR HOST CONTAINS "finance"

CORRELATE PROCESSES WITH NETWORK
CORRELATE EXECUTION WITH NETWORK

TIMELINE SIGNIFICANT LIMIT 500

REPORT BOTH AS "IR-2024-004-fleet"
''',
  ),
  JockyExample(
    name: 'conditional',
    summary: 'One program, a different plan per platform',
    source: r'''# Conditional, reusable investigation.
#
# This is the example that shows why JOCKY is a language rather than a list of
# collector commands. The same program is written once and produces a different
# execution plan on each platform, and every step it leaves out is named in that
# plan with the guard that excluded it. Nothing here is resolved while parsing:
# the conditions travel into the IR and the platform adapter resolves them, so
# the IR stays platform-neutral and the decision stays auditable.

CASE "IR-2024-005" {
    TITLE "Portable triage across a mixed estate"
    EXAMINER "R. Saha"
    NOTES "One program, two platforms, one comparable result."
}

TARGET "workstation-07"
TARGET "laptop-14"

WINDOW LAST 48 HOURS

# The evidence every host must yield for the results to be comparable at all.
DEFINE core_triage {
    COLLECT SYSTEM
    COLLECT PROCESSES
    COLLECT EXECUTION
}

# Evidence worth having wherever this build can actually collect it.
DEFINE host_context {
    WHEN SOURCE BROWSER IS SUPPORTED {
        COLLECT BROWSER
    }
    WHEN SOURCE SERVICES IS SUPPORTED {
        COLLECT SERVICES
    }
}

RUN core_triage
RUN host_context

# Removable media and loaded kernel modules are Linux-only in this build. On
# Windows these become named skips rather than silent omissions.
WHEN PLATFORM IS linux {
    COLLECT USB
    COLLECT DRIVERS
    FILTER PATH CONTAINS "/media" OR PATH CONTAINS "/mnt"
    CORRELATE EXECUTION WITH USB
}

COLLECT NETWORK

FILTER NOT USER EQUALS "root" AND COMMAND MATCHES "(curl|wget|nc)"

CORRELATE PROCESSES WITH NETWORK

TIMELINE SIGNIFICANT LIMIT 250

REPORT BOTH AS "IR-2024-005-portable"
''',
  ),
];
