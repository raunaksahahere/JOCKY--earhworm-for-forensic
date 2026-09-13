"""
Read-only host system information for forensic context.

Reports static/observational system facts (OS, hardware, runtime). Does
not change any system setting, service, or security control.
"""

from __future__ import annotations

import os
import platform
import socket
from datetime import datetime, timezone

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is a declared dependency
    psutil = None


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _bytes_to_gb(value: int) -> float:
    return round(value / (1024 ** 3), 2)


def get_system_info() -> dict:
    info: dict = {
        "action": "system_info",
        "hostname": socket.gethostname(),
        "os": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_logical_cores": os.cpu_count(),
        "python_runtime": platform.python_version(),
        "platform_string": platform.platform(),
        "collected_at": datetime.now(tz=timezone.utc).isoformat(),
        "status": "success",
        "message": "System information collected",
    }

    if psutil is not None:
        try:
            vm = psutil.virtual_memory()
            disk = psutil.disk_usage(os.path.abspath(os.sep))
            boot_time = psutil.boot_time()
            uptime_seconds = int(datetime.now(tz=timezone.utc).timestamp() - boot_time)
            info.update(
                {
                    "cpu_physical_cores": psutil.cpu_count(logical=False),
                    "cpu_percent": psutil.cpu_percent(interval=0.1),
                    "memory_total_gb": _bytes_to_gb(vm.total),
                    "memory_available_gb": _bytes_to_gb(vm.available),
                    "memory_used_percent": vm.percent,
                    "disk_total_gb": _bytes_to_gb(disk.total),
                    "disk_used_percent": disk.percent,
                    "boot_time": _iso(boot_time),
                    "uptime_seconds": uptime_seconds,
                }
            )
        except (OSError, psutil.Error, NotImplementedError) as error:
            info["monitoring_note"] = f"Extended metrics unavailable on this host ({type(error).__name__})."
            info["warnings"] = [info["monitoring_note"]]
    else:
        info["monitoring_note"] = "psutil unavailable; extended metrics were not collected."
        info["warnings"] = [info["monitoring_note"]]

    return info
