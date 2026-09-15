# Multi-endpoint investigation.
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

FILTER ADDRESS EQUALS $indicator OR HOST CONTAINS "finance"

CORRELATE PROCESSES WITH NETWORK
CORRELATE EXECUTION WITH NETWORK

TIMELINE SIGNIFICANT LIMIT 500

REPORT BOTH AS "IR-2024-004-fleet"
