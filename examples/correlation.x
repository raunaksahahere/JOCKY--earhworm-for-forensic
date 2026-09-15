# Cross-source investigation.
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

FILTER URL CONTAINS "storage" OR URL MATCHES "[.](zip|tar[.]gz|7z)$"

CORRELATE PROCESSES WITH NETWORK
CORRELATE BROWSER WITH ARTIFACTS
CORRELATE EXECUTION WITH NETWORK

TIMELINE SIGNIFICANT LIMIT 300

REPORT BOTH AS "IR-2024-003-correlated"
