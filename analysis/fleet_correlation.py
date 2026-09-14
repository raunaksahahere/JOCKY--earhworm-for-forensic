"""
Correlation across hosts.

One machine's evidence answers "what happened here". Several machines' evidence
can answer "did the same thing happen in more than one place", which is the
question that separates an isolated event from an incident.

What this module does is narrow on purpose. It reports *the same observable
appearing on more than one endpoint* -- an identical file hash, a shared remote
address, the same driver, the same downloaded file. It does not infer a cause,
an actor or a direction of movement. Two machines contacting the same address
is a fact; deciding whether that is an update server or a command channel is
the investigator's judgement, and the report says so rather than guessing.

A correlation drawn from one endpoint's evidence alone is not a correlation, so
anything appearing on a single host is left out entirely.
"""

from __future__ import annotations

from collections import defaultdict

MIN_ENDPOINTS = 2
MAX_OBSERVATIONS_PER_KIND = 50
#: Addresses every machine talks to. Present on many hosts for ordinary
#: reasons, so reporting them as a cross-host link would bury the real ones.
UNINTERESTING_ADDRESSES = {"127.0.0.1", "::1", "0.0.0.0", "::", "localhost"}
UNINTERESTING_PREFIXES = ("169.254.", "224.", "239.", "255.")
#: Serial numbers that identify nothing. USB root hubs report their PCI address
#: here, and cheap peripherals ship whole production runs with the same string,
#: so matching on these would pair unrelated devices across hosts.
PLACEHOLDER_SERIALS = {"0001", "000000000", "0000", "1", "0123456789", "00000000",
                       "123456789", "serial", "none", "n/a"}
MIN_SERIAL_LENGTH = 6

KIND_EXPLANATIONS = {
    "file_hash": ("The same file, by SHA-256, is present on more than one endpoint. Identical "
                  "bytes on several machines is a fact about distribution, not about intent: "
                  "shared software looks exactly like this."),
    "remote_address": ("More than one endpoint has a connection to the same remote address. This "
                       "is normal for update, telemetry and cloud services, and it is also what "
                       "several machines talking to one controller looks like."),
    "driver": ("The same driver is loaded on more than one endpoint. Common for fleet-standard "
               "software; notable when the driver is one known to be abused."),
    "download": ("The same file was downloaded on more than one endpoint, by name and host."),
    "usb_device": ("The same removable device, by serial, was seen on more than one endpoint."),
}


def _endpoint_names(endpoints):
    return {endpoint["id"]: endpoint.get("name") or endpoint["id"]
            for endpoint in (endpoints or [])}


def _observations(result, source):
    """Observables one collector result contributes, as (kind, key, detail)."""
    if not isinstance(result, dict):
        return
    if source == "NETWORK":
        for connection in result.get("connections") or []:
            address = (connection.get("remote_address") or "").split(":")[0]
            if (not address or address in UNINTERESTING_ADDRESSES
                    or address.startswith(UNINTERESTING_PREFIXES)):
                continue
            yield ("remote_address", address,
                   {"port": connection.get("remote_port"),
                    "process": connection.get("process_name"),
                    "status": connection.get("status")})
    elif source == "DRIVERS":
        for driver in result.get("drivers") or []:
            name = driver.get("name")
            if not name:
                continue
            verification = (driver.get("verification") or {}).get("risk_status")
            yield ("driver", name, {"known_abused": verification == "MATCHED",
                                    "sha256": driver.get("sha256")})
    elif source == "BROWSER":
        for download in result.get("downloads") or []:
            target = download.get("target_path") or download.get("url")
            if not target:
                continue
            # Keyed on the origin as well as the filename. "report.pdf" is the
            # name of a thousand unrelated files, and pairing two hosts on that
            # alone would manufacture a link that is not there.
            url = download.get("url") or ""
            origin = url.split("//", 1)[-1].split("/", 1)[0] if "//" in url else "unknown origin"
            yield ("download", f"{target.rsplit('/', 1)[-1]} from {origin}",
                   {"url": url, "profile": download.get("profile")})
    elif source == "USB":
        for device in result.get("devices") or []:
            serial = (device.get("serial") or "").strip()
            # A root hub's "serial" is its PCI address and a placeholder serial
            # is shared by every unit of a model. Neither identifies a device
            # that moved between machines, which is the only reason to correlate
            # removable media at all.
            if (len(serial) < MIN_SERIAL_LENGTH or serial.lower() in PLACEHOLDER_SERIALS
                    or ":" in serial or set(serial) <= {"0"}
                    or device.get("removable") != "removable"):
                continue
            yield ("usb_device",
                   f"{device.get('vendor') or '?'} {device.get('product') or '?'} [{serial}]",
                   {"vendor": device.get("vendor"), "product": device.get("product"),
                    "serial": serial})
    for artifact in result.get("artifacts") or []:
        digest = artifact.get("sha256") or artifact.get("hash")
        if digest:
            yield ("file_hash", digest, {"path": artifact.get("path")})


def correlate_fleet(tasks, *, endpoints=None) -> dict:
    """Observables shared by two or more endpoints.

    `tasks` are completed endpoint tasks carrying their collector results.
    """
    names = _endpoint_names(endpoints)
    seen = defaultdict(lambda: defaultdict(list))
    contributing, sources = set(), set()

    for task in tasks or []:
        if task.get("status") != "succeeded" or not isinstance(task.get("result"), dict):
            continue
        endpoint_id = task["endpoint_id"]
        contributing.add(endpoint_id)
        sources.add(task["source"])
        for kind, key, detail in _observations(task["result"], task["source"]):
            seen[kind][key].append({"endpoint_id": endpoint_id,
                                    "endpoint": names.get(endpoint_id, endpoint_id),
                                    "detail": detail})

    correlations, suppressed = [], defaultdict(int)
    total = max(len(contributing), 1)
    for kind, observed in seen.items():
        matches = []
        for key, records in observed.items():
            hosts = {record["endpoint_id"] for record in records}
            if len(hosts) < MIN_ENDPOINTS:
                continue
            known_abused = any(record["detail"].get("known_abused") for record in records)
            ubiquitous = len(hosts) == total
            # Something on every machine in the fleet is the fleet's standard
            # build. Listing all of it would bury the handful of observables
            # that are shared by some hosts and not others, which is where a
            # cross-host investigation actually starts. Drivers are the worst
            # offender -- every Linux host loads the same hundred modules -- so
            # a ubiquitous driver is counted and dropped unless it is one the
            # reference flags as abused.
            if kind == "driver" and ubiquitous and not known_abused:
                suppressed[kind] += 1
                continue
            matches.append({
                "kind": kind, "value": key, "endpoint_count": len(hosts),
                "prevalence": round(len(hosts) / total, 3), "ubiquitous": ubiquitous,
                "endpoints": sorted({record["endpoint"] for record in records}),
                "observations": records[:MAX_OBSERVATIONS_PER_KIND],
                "explanation": KIND_EXPLANATIONS[kind]
                + (" It is present on every endpoint that reported, which is what a standard "
                   "build looks like." if ubiquitous else
                   " It is present on some endpoints and not others, which is the pattern worth "
                   "explaining."),
                "notable": known_abused,
            })
        # Rare first: an observable on a minority of hosts is the one that needs
        # an explanation, and a flagged driver outranks everything.
        matches.sort(key=lambda match: (not match["notable"], match["prevalence"], match["value"]))
        correlations.extend(matches[:MAX_OBSERVATIONS_PER_KIND])

    return {
        "endpoints_contributing": sorted(contributing),
        "endpoint_count": len(contributing),
        "sources_compared": sorted(sources),
        "correlations": correlations,
        "correlation_count": len(correlations),
        "suppressed": dict(suppressed),
        "limitations": [
            ("Only endpoints that returned results are compared. An endpoint that was offline, "
             "unenrolled or failed its tasks contributes nothing, and its absence is not evidence "
             "that it is clean."),
            ("A shared observable says the same thing was seen in two places. It does not "
             "establish that one host caused it on the other, nor in which direction."),
            ("Observables present on every reporting endpoint are counted but not listed for "
             "drivers, because a fleet-wide driver is the standard build rather than a lead. "
             f"Suppressed on that basis: {sum(suppressed.values())}."),
            ("Comparison is limited to the sources actually collected on each host: "
             + (", ".join(sorted(sources)) if sources else "none")),
        ] + ([] if len(contributing) >= MIN_ENDPOINTS else [
            (f"Fewer than {MIN_ENDPOINTS} endpoints returned evidence, so no cross-host "
             "correlation was possible.")]),
    }
