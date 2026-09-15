# Filtered investigation.
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

FILTER PATH ONEOF $download_tools AND NOT USER EQUALS "root"

FILTER (COMMAND CONTAINS "base64" OR COMMAND MATCHES "tar .*-c") AND PATH STARTS $staging_dir

TIMELINE FULL

REPORT BOTH AS "IR-2024-002-transfer"
