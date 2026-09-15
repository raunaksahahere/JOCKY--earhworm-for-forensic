# Basic endpoint investigation.
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
