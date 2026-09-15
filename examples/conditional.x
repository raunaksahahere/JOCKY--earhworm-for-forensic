# Conditional, reusable investigation.
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
