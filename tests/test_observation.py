from types import SimpleNamespace

import psutil
import pytest

from analysis import processes, system


@pytest.fixture
def host_metrics(monkeypatch):
    monkeypatch.setattr(system.socket, "gethostname", lambda: "fixture-host")
    monkeypatch.setattr(system.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(total=8 * 1024**3, available=4 * 1024**3, percent=50.0))
    monkeypatch.setattr(psutil, "disk_usage", lambda _: SimpleNamespace(total=100 * 1024**3, percent=25.0))
    monkeypatch.setattr(psutil, "boot_time", lambda: 1700000000)
    monkeypatch.setattr(psutil, "cpu_count", lambda **kwargs: 2)
    monkeypatch.setattr(psutil, "cpu_percent", lambda **kwargs: 12.5)


@pytest.mark.parametrize("os_name", ["Windows", "Linux"])
def test_system_collection(host_metrics, monkeypatch, os_name):
    monkeypatch.setattr(system.platform, "system", lambda: os_name)
    result = system.get_system_info()
    assert result["hostname"] == "fixture-host" and result["os"] == os_name
    assert result["memory_total_gb"] == 8 and result["cpu_percent"] == 12.5
    assert result["cpu_logical_cores"] == 4 and result["disk_used_percent"] == 25
    assert result["collected_at"].endswith("+00:00")


def test_unavailable_cores_and_processor(host_metrics, monkeypatch):
    monkeypatch.setattr(system.os, "cpu_count", lambda: None)
    monkeypatch.setattr(psutil, "cpu_count", lambda **kwargs: None)
    monkeypatch.setattr(system.platform, "processor", lambda: "")
    result = system.get_system_info()
    assert result["cpu_logical_cores"] is None and result["cpu_physical_cores"] is None
    assert result["processor"] == "unknown"


@pytest.mark.parametrize("error", [PermissionError("fixture"), psutil.AccessDenied(), NotImplementedError()])
def test_system_collection_failure_is_visible(host_metrics, monkeypatch, error):
    def denied(*args):
        raise error
    monkeypatch.setattr(psutil, "disk_usage", denied)
    result = system.get_system_info()
    assert result["warnings"] and result["monitoring_note"]
    assert "memory_used_percent" not in result and "cpu_percent" not in result


def test_missing_psutil_system(monkeypatch):
    monkeypatch.setattr(system, "psutil", None)
    result = system.get_system_info()
    assert result["warnings"] and "memory_total_gb" not in result


def test_unexpected_collector_bug_not_swallowed(host_metrics, monkeypatch):
    def broken(*args):
        raise ValueError("collector bug")
    monkeypatch.setattr(psutil, "disk_usage", broken)
    with pytest.raises(ValueError, match="collector bug"):
        system.get_system_info()


def process(pid, memory):
    return SimpleNamespace(info={"pid": pid, "name": "fixture", "username": "user", "status": "running",
                                 "memory_percent": memory, "cpu_percent": 0.0, "create_time": 1700000000})


def test_processes_sorted_and_bounded(monkeypatch):
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: iter([process(1, 1.0), process(2, 5.0), process(3, 3.0)]))
    monkeypatch.setattr(processes, "MAX_PROCESSES_RETURNED", 2)
    result = processes.list_processes()
    assert [p["pid"] for p in result["processes"]] == [2, 3]
    assert result["process_count"] == 3 and result["returned_count"] == 2
    assert result["truncated"] and result["warnings"]
    assert all(p["cpu_percent"] is None for p in result["processes"])


def test_unknown_memory_is_not_zero(monkeypatch):
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: iter([process(1, None), process(2, 0.0)]))
    result = processes.list_processes()
    assert [p["pid"] for p in result["processes"]] == [2, 1]
    assert result["processes"][1]["memory_percent"] is None
    assert result["processes"][0]["memory_percent"] == 0
    assert result["warnings"] and not result["complete"]


@pytest.mark.parametrize("error", [psutil.AccessDenied(1), psutil.NoSuchProcess(1), psutil.ZombieProcess(1)])
def test_process_permission_and_race(monkeypatch, error):
    class Unreadable:
        @property
        def info(self):
            raise error
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: iter([Unreadable(), process(2, 0.0)]))
    result = processes.list_processes()
    assert result["process_count"] == 2 and result["skipped_count"] == 1
    assert result["returned_count"] == 1 and not result["complete"]


def test_process_enumeration_denied(monkeypatch):
    def denied(attrs):
        raise psutil.AccessDenied()
    monkeypatch.setattr(psutil, "process_iter", denied)
    with pytest.raises(psutil.AccessDenied):
        processes.list_processes()


def test_missing_psutil_processes(monkeypatch):
    monkeypatch.setattr(processes, "psutil", None)
    with pytest.raises(RuntimeError, match="psutil"):
        processes.list_processes()


def test_no_processes(monkeypatch):
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: iter([]))
    result = processes.list_processes()
    assert result["process_count"] == result["returned_count"] == 0
    assert result["processes"] == []
