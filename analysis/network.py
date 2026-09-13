"""
Read-only network metadata.

Interfaces, addresses, routes, resolver configuration, listening sockets and
established connections, with the owning process where the operating system
will say. Nothing here captures traffic: there is no packet interception, no
promiscuous mode and no content. It records what the host itself already knows
about its own networking, which is what correlates a process with an endpoint.
"""

from __future__ import annotations

import os
import socket
from datetime import datetime, timezone
from pathlib import Path

import psutil

MAX_CONNECTIONS = 2000
MAX_ROUTES = 500

_FAMILY = {socket.AF_INET: "ipv4", socket.AF_INET6: "ipv6", getattr(socket, "AF_UNIX", -1): "unix"}
_KIND = {socket.SOCK_STREAM: "tcp", socket.SOCK_DGRAM: "udp"}


def _iso(value):
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat() if value else None


def _interfaces():
    records, unavailable = [], {}
    try:
        addresses = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
    except (psutil.Error, OSError) as error:
        return [], {"interfaces": f"could not be read: {error}"}
    for name, entries in sorted(addresses.items()):
        status = stats.get(name)
        records.append({
            "name": name,
            "is_up": bool(status.isup) if status else None,
            "mtu": status.mtu if status else None,
            "speed_mbps": status.speed if status and status.speed else None,
            "addresses": [
                {"family": _FAMILY.get(entry.family, str(entry.family)), "address": entry.address,
                 "netmask": entry.netmask, "broadcast": entry.broadcast}
                for entry in entries],
        })
    return records, unavailable


def _resolver(path="/etc/resolv.conf"):
    """DNS configuration, which names where this host asks about the world."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return {"status": "NOT_AVAILABLE", "detail": f"{path} does not exist", "nameservers": []}
    except PermissionError:
        return {"status": "PERMISSION_DENIED", "detail": f"{path} is not readable",
                "nameservers": []}
    except OSError as error:
        return {"status": "NOT_AVAILABLE", "detail": str(error), "nameservers": []}
    nameservers, search = [], []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "nameserver":
            nameservers.append(parts[1])
        elif len(parts) >= 2 and parts[0] in ("search", "domain"):
            search.extend(parts[1:])
    return {"status": "AVAILABLE", "path": path, "nameservers": nameservers,
            "search_domains": search}


def _routes(path="/proc/net/route", limit=MAX_ROUTES):
    """IPv4 routing table, read from proc rather than by running a tool."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, PermissionError) as error:
        return {"status": "NOT_AVAILABLE", "detail": str(error), "routes": []}

    def dotted(hex_value):
        value = int(hex_value, 16)
        return ".".join(str((value >> shift) & 0xFF) for shift in (0, 8, 16, 24))

    routes = []
    for line in lines[1:limit + 1]:
        fields = line.split()
        if len(fields) < 8:
            continue
        try:
            routes.append({"interface": fields[0], "destination": dotted(fields[1]),
                           "gateway": dotted(fields[2]), "mask": dotted(fields[7]),
                           "metric": int(fields[6])})
        except (ValueError, IndexError):
            continue
    return {"status": "AVAILABLE", "path": path, "routes": routes}


def _connections(limit=MAX_CONNECTIONS):
    """Sockets, with the owning process where the OS will say who owns it."""
    listening, established, denied = [], [], 0
    try:
        sockets = psutil.net_connections(kind="inet")
    except psutil.AccessDenied:
        return [], [], {"connections": "the collector lacks the privileges to enumerate sockets"}
    except (psutil.Error, OSError) as error:
        return [], [], {"connections": f"could not be read: {error}"}

    names = {}
    for connection in sockets[:limit]:
        owner = None
        if connection.pid:
            if connection.pid not in names:
                try:
                    names[connection.pid] = psutil.Process(connection.pid).name()
                except (psutil.Error, OSError):
                    names[connection.pid] = None
                    denied += 1
            owner = names[connection.pid]
        record = {
            "family": _FAMILY.get(connection.family, str(connection.family)),
            "kind": _KIND.get(connection.type, str(connection.type)),
            "local_address": f"{connection.laddr.ip}:{connection.laddr.port}" if connection.laddr else None,
            "remote_address": (f"{connection.raddr.ip}:{connection.raddr.port}"
                               if connection.raddr else None),
            "status": connection.status,
            "pid": connection.pid,
            "process_name": owner,
            "classification": "CURRENT_OBSERVATION",
        }
        (listening if connection.status == psutil.CONN_LISTEN else established).append(record)
    unavailable = {}
    if denied:
        unavailable["connection_owner"] = f"{denied} sockets had no readable owning process"
    return listening, established, unavailable


def collect_network(cancel=None, *, resolver_path="/etc/resolv.conf",
                    route_path="/proc/net/route", limit=MAX_CONNECTIONS) -> dict:
    """Everything the host will tell us about its own networking, read-only."""
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Collection cancelled before network metadata was read")

    interfaces, unavailable = _interfaces()
    resolver = _resolver(resolver_path)
    routes = _routes(route_path)
    listening, established, socket_gaps = _connections(limit)
    unavailable.update(socket_gaps)

    warnings = [
        "CURRENT OBSERVATION: sockets and connections describe this moment. They do not "
        "establish that a connection existed before collection started.",
        "No traffic was captured. JOCKY records the host's own view of its networking, never "
        "packet contents.",
    ]
    if resolver["status"] != "AVAILABLE":
        warnings.append(f"Resolver configuration unavailable: {resolver.get('detail')}")
    if unavailable:
        warnings.append("Some network details could not be read; each is named in 'unavailable'.")

    return {
        "action": "network_metadata",
        "status": "success",
        "classification": "CURRENT_OBSERVATION",
        "hostname": socket.gethostname(),
        "interfaces": interfaces,
        "resolver": resolver,
        "routing": routes,
        "listening_sockets": listening,
        "connections": established,
        "statistics": {
            "interface_count": len(interfaces),
            "listening_count": len(listening),
            "connection_count": len(established),
            "connections_with_process": sum(1 for record in established if record["process_name"]),
        },
        "limits": {"max_connections": limit, "packet_capture": False},
        "unavailable": unavailable,
        "truncated": len(listening) + len(established) >= limit,
        "complete": not unavailable,
        "warnings": warnings,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }
