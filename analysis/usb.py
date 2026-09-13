"""
Read-only removable-media evidence.

Device identity from sysfs, connection events from the kernel journal, and
current mount points. No file contents are read: a removable device's files
become evidence only when an investigator selects them explicitly, through the
ordinary artifact collector.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .execution_linux import run_command
from .execution_model import AVAILABLE, NOT_AVAILABLE, PERMISSION_DENIED, source_record

MAX_DEVICES = 200
MAX_EVENTS = 1000

USB_ROOT = "/sys/bus/usb/devices"
MOUNTS = "/proc/mounts"

#: Kernel messages that mark a removable device arriving or leaving. Matching
#: the kernel's own wording is what gives a connection a timestamp.
_CONNECT = re.compile(r"(?i)\bnew (?:high|full|low|super)[- ]speed USB device number (\d+) using")
_IDENTITY = re.compile(r"(?i)New USB device found, idVendor=([0-9a-f]{4}), idProduct=([0-9a-f]{4})")
_STRINGS = re.compile(r"(?i)Product: (.+?)(?:,|$)|Manufacturer: (.+?)(?:,|$)|SerialNumber: (.+?)(?:,|$)")
_DISCONNECT = re.compile(r"(?i)\bUSB disconnect, device number (\d+)")


def _read(path: Path):
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip() or None
    except (OSError, PermissionError):
        return None


def _devices(root=USB_ROOT, limit=MAX_DEVICES):
    """Device identity as the kernel currently reports it."""
    base = Path(root)
    if not base.is_dir():
        return [], source_record("USB device inventory", NOT_AVAILABLE, location=root,
                                 detail="This host exposes no USB device tree under sysfs.")
    records = []
    try:
        entries = sorted(base.iterdir())
    except PermissionError:
        return [], source_record("USB device inventory", PERMISSION_DENIED, location=root,
                                 detail="The USB device tree is not readable.")
    for entry in entries[:limit]:
        vendor, product = _read(entry / "idVendor"), _read(entry / "idProduct")
        if not vendor or not product:
            continue  # An interface, not a device.
        records.append({
            "device": entry.name,
            "vendor_id": vendor,
            "product_id": product,
            "vendor": _read(entry / "manufacturer"),
            "product": _read(entry / "product"),
            "serial": _read(entry / "serial"),
            "removable": _read(entry / "removable"),
            "usb_version": _read(entry / "version"),
            "max_power": _read(entry / "bMaxPower"),
            "classification": "CURRENT_OBSERVATION",
            "source": f"{root}/{entry.name}",
            "evidence_strength": ("The device is attached now. This says nothing about earlier "
                                  "connections, which the journal records separately."),
        })
    return records, source_record("USB device inventory", AVAILABLE, location=root,
                                  detail=f"{len(records)} USB devices attached.",
                                  event_count=len(records))


def _events(window, runner=run_command, limit=MAX_EVENTS):
    """Connection and disconnection events, from the kernel's own log."""
    argv = ["journalctl", "--utc", "--no-pager", "-o", "json", "-k",
            "--since", f"@{int(window.start.timestamp())}",
            "--until", f"@{int(window.end.timestamp())}",
            "-n", str(limit), "--output-fields=MESSAGE"]
    status, output = runner(argv)
    if status != AVAILABLE:
        return [], source_record(
            "USB connection events", status, location="kernel journal",
            detail=("The kernel journal could not be read, so earlier connections cannot be "
                    "dated. Devices attached now are still listed."))

    events, pending = [], {}
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        message = record.get("MESSAGE")
        if not isinstance(message, str):
            continue
        try:
            moment = datetime.fromtimestamp(
                int(record["__REALTIME_TIMESTAMP"]) / 1_000_000, timezone.utc).isoformat()
        except (KeyError, TypeError, ValueError):
            continue

        connect = _CONNECT.search(message)
        identity = _IDENTITY.search(message)
        disconnect = _DISCONNECT.search(message)
        if connect:
            pending[connect.group(1)] = moment
        elif identity:
            events.append({
                "kind": "connected", "timestamp": moment,
                "vendor_id": identity.group(1), "product_id": identity.group(2),
                "classification": "HISTORICAL_EVIDENCE", "source": "kernel journal",
                "evidence_strength": ("The kernel recorded a USB device being enumerated at this "
                                      "time."),
                "raw": message[:300],
            })
        elif disconnect:
            events.append({
                "kind": "disconnected", "timestamp": moment,
                "device_number": disconnect.group(1),
                "classification": "HISTORICAL_EVIDENCE", "source": "kernel journal",
                "evidence_strength": "The kernel recorded a USB device being removed at this time.",
                "raw": message[:300],
            })
        elif "Product:" in message or "SerialNumber:" in message:
            if events and events[-1]["kind"] == "connected":
                for match in _STRINGS.finditer(message):
                    product, manufacturer, serial = match.groups()
                    if product:
                        events[-1]["product"] = product.strip()
                    if manufacturer:
                        events[-1]["vendor"] = manufacturer.strip()
                    if serial:
                        events[-1]["serial"] = serial.strip()
    return events, source_record(
        "USB connection events", AVAILABLE, location="kernel journal",
        detail=f"{len(events)} connection and disconnection records.", event_count=len(events))


def _mounts(path=MOUNTS):
    """Where removable filesystems are mounted right now."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, PermissionError) as error:
        return [], source_record("Removable mounts", NOT_AVAILABLE, location=path,
                                 detail=str(error))
    records = []
    for line in lines:
        fields = line.split()
        if len(fields) < 4:
            continue
        device, mount_point, filesystem, options = fields[0], fields[1], fields[2], fields[3]
        # Media mounted for a user, which is what removable storage looks like.
        if not (mount_point.startswith(("/media/", "/run/media/", "/mnt/"))
                or device.startswith("/dev/sd") and mount_point not in ("/", "/boot")):
            continue
        records.append({
            "device": device, "mount_point": mount_point, "filesystem": filesystem,
            "options": options, "classification": "CURRENT_OBSERVATION",
            "source": path,
            "evidence_strength": ("The filesystem is mounted now. No file on it was read: media "
                                  "contents become evidence only when selected explicitly."),
        })
    return records, source_record("Removable mounts", AVAILABLE, location=path,
                                  detail=f"{len(records)} removable filesystems mounted.",
                                  event_count=len(records))


def collect_removable_media(cancel=None, *, window=None, runner=run_command,
                            usb_root=USB_ROOT, mounts_path=MOUNTS) -> dict:
    """Removable-media identity, connection history and current mounts."""
    from .execution_model import CollectionWindow
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Collection cancelled before removable media were read")
    window = window or CollectionWindow.resolve()

    devices, device_source = _devices(usb_root)
    events, event_source = _events(window, runner=runner)
    mounts, mount_source = _mounts(mounts_path)
    sources = [device_source, event_source, mount_source]

    warnings = [
        "No file on removable media was read. Media contents become evidence only when an "
        "investigator selects a path explicitly.",
        "A device attached now is a CURRENT OBSERVATION; a journal connection record is "
        "HISTORICAL EVIDENCE. They are listed separately for that reason.",
    ]
    for source in sources:
        if source["status"] != AVAILABLE:
            warnings.append(f"{source['name']}: {source['detail']}")

    return {
        "action": "removable_media",
        "status": "success",
        "classification": "HISTORICAL_EVIDENCE" if events else "CURRENT_OBSERVATION",
        "window": window.to_dict(),
        "devices": devices,
        "events": events,
        "mounts": mounts,
        "sources": sources,
        "statistics": {"devices_attached": len(devices), "connection_events": len(events),
                       "removable_mounts": len(mounts),
                       "sources_available": len([s for s in sources if s["status"] == AVAILABLE])},
        "limits": {"max_devices": MAX_DEVICES, "max_events": MAX_EVENTS,
                   "media_contents_read": False},
        "truncated": len(events) >= MAX_EVENTS,
        "complete": all(source["status"] == AVAILABLE for source in sources),
        "warnings": warnings,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }
