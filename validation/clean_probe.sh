#!/usr/bin/env bash
#
# Run inside the clean container: drive the installed engine the way the desktop
# client does, then do the things an investigator does with the result.
#
# The engine announces its port, token and instance id as one NDJSON line on
# stdout, and holds stdin open for as long as its owner is alive. That is the
# whole bootstrap protocol, and this reproduces it.
set -uo pipefail

fail() { echo "   PROBLEM: $1"; exit 1; }

ENGINE=/opt/jocky-workstation/backend/jocky-backend
WS=/tmp/ws-$$
BOOT=/tmp/boot.ndjson

mkfifo /tmp/hold 2>/dev/null || true
sleep 600 > /tmp/hold &
HOLDER=$!
"$ENGINE" --workspace "$WS" < /tmp/hold > "$BOOT" 2>/tmp/boot.err &
PID=$!
trap 'kill $PID $HOLDER 2>/dev/null || true' EXIT

for _ in $(seq 1 90); do
    grep -q '"event": "ready"' "$BOOT" 2>/dev/null && break
    sleep 1
done
READY=$(grep '"event": "ready"' "$BOOT" | head -1 || true)
if [ -z "$READY" ]; then
    echo "   the installed engine never became ready"
    tail -5 /tmp/boot.err
    exit 1
fi

# Exact-key extraction. A substring match picks "port" out of "report_schema"
# and out of "portable", which is how this quietly produced a three-line port
# number the first time it was written.
field() {
    echo "$READY" | grep -o "\"$1\": *\"\?[^\",}]*" | head -1 | sed "s/^\"$1\": *\"\?//"
}
PORT=$(field port)
TOKEN=$(field token)
INSTANCE=$(field instance_id)
API="http://127.0.0.1:$PORT"
AUTH=(-H "Authorization: Bearer $TOKEN" -H "X-Jocky-Instance: $INSTANCE")
JSON=(-H "Content-Type: application/json")

if [ -z "$PORT" ] || [ -z "$TOKEN" ]; then fail "could not read the bootstrap line: $READY"; fi
echo "   engine ready on port $PORT with a per-process token"

get()  { curl -s "${AUTH[@]}" "$API$1"; }
post() { curl -s -X POST "${AUTH[@]}" "${JSON[@]}" -d "$2" "$API$1"; }
download() { curl -s -X POST "${AUTH[@]}" "${JSON[@]}" -d "$3" "$API$1" -o "$2"; }
value() {
    grep -o "\"$1\": *\"\?[^\",}]*" | head -1 | sed "s/^\"$1\": *\"\?//"
}

HEALTH=$(get /api/v1/health)
echo "$HEALTH" | grep -q '"ready": *true' || fail "/health did not report ready"
echo "   /health reports ready, version $(echo "$HEALTH" | value application)"

CODE=$(curl -s -o /dev/null -w '%{http_code}' "$API/api/v1/health")
[ "$CODE" = "401" ] || fail "unauthenticated request returned $CODE"
echo "   an unauthenticated request is refused (401)"

get /api/v1/collection-sources | grep -q DRIVERS || fail "no collectors advertised"
echo "   the installed engine advertises its collectors"

CASE=$(post /api/v1/investigations '{"title":"Clean install validation"}' | value id)
[ -n "$CASE" ] || fail "could not create an investigation"
echo "   investigation $CASE created"

post "/api/v1/investigations/$CASE/collect" \
     '{"paths":["/bin/sh"],"window_hours":6,"sources":["NETWORK","DRIVERS","SERVICES"]}' >/dev/null
# Read the status from the transition log rather than from the investigation
# object. The investigation carries a nested `device` whose own "status" comes
# first in the JSON, so a flat text match on the object reports the device's
# collection status -- which is "success" from the first second and never
# changes, making the poll loop wait forever for a state it already had.
state() { get "/api/v1/investigations/$1/transitions" | grep -o '"state": *"[^"]*' | tail -1 | sed 's/.*"//'; }
for _ in $(seq 1 300); do
    STATUS=$(state "$CASE")
    case "$STATUS" in completed|partially_completed|failed|cancelled) break;; esac
    sleep 1
done
echo "   collection finished: $STATUS"
if [ "$STATUS" = "failed" ] || [ -z "$STATUS" ]; then
    fail "collection did not complete (status: ${STATUS:-none})"
fi

EVIDENCE=$(get "/api/v1/investigations/$CASE/evidence")
for source in NETWORK DRIVERS SERVICES; do
    echo "$EVIDENCE" | grep -q "\"$source\"" || fail "no $source evidence record"
done
echo "   every selected source produced an evidence record"

ROUTINE=$(get "/api/v1/investigations/$CASE/routine")
echo "$ROUTINE" | grep -q 'not a guarantee' || fail "the routine report omits its qualification"
echo "   routine activity grouped into $(echo "$ROUTINE" | value group_count) group(s)"

SUMMARY=$(get "/api/v1/investigations/$CASE/summary")
echo "$SUMMARY" | grep -q 'not a verdict' || fail "the case summary omits its qualification"
echo "   case summary generated with its closing qualification"

download "/api/v1/investigations/$CASE/report/export" /tmp/report.pdf '{"format":"pdf"}'
head -c 4 /tmp/report.pdf | grep -q '%PDF' || fail "the report is not a PDF"
echo "   investigator report: $(stat -c%s /tmp/report.pdf) bytes"

download "/api/v1/investigations/$CASE/routine/export" /tmp/routine.pdf '{}'
head -c 4 /tmp/routine.pdf | grep -q '%PDF' || fail "the routine report is not a PDF"
echo "   routine activity report: $(stat -c%s /tmp/routine.pdf) bytes"

REF=$(get "/api/v1/investigations/$CASE/artifacts" | tr ',' '\n' | grep -o 'ART-[0-9]*' | head -1)
if [ -n "$REF" ]; then
    BRIEF=$(post "/api/v1/investigations/$CASE/briefs" \
                 "{\"subject_type\":\"artifact\",\"subject_id\":\"$REF\"}")
    echo "$BRIEF" | grep -q 'not a malware verdict' || fail "the brief omits its qualification"
    echo "$BRIEF" | grep -q '"recognition"' || fail "the brief carries no recognition"
    download "/api/v1/investigations/$CASE/briefs/export" /tmp/brief.pdf \
             "{\"subject_type\":\"artifact\",\"subject_id\":\"$REF\"}"
    head -c 4 /tmp/brief.pdf | grep -q '%PDF' || fail "the brief is not a PDF"
    echo "   review brief for $REF: $(stat -c%s /tmp/brief.pdf) bytes"
fi

RECOGNIZED=$(get "/api/v1/investigations/$CASE/reports" | grep -o '"artifacts_recognized": *[0-9]*' \
             | head -1 | sed 's/.*: *//')
echo "   recognition accounted for ${RECOGNIZED:-0} artifact(s)"

download "/api/v1/investigations/$CASE/package" /tmp/package.zip '{}'
head -c 2 /tmp/package.zip | grep -q 'PK' || fail "the evidence package is not a zip"
echo "   evidence package: $(stat -c%s /tmp/package.zip) bytes"

post /api/v1/shutdown '{}' >/dev/null || true
echo "   engine shut down cleanly"
