"""Cross-source and cross-host correlation.

A link is only ever a link. These tests check that the code says so, and that
it does not manufacture links that the evidence does not support.
"""
from analysis.cross_source import correlate_downloads, correlate_removable_media, correlate_sources
from analysis.fleet_correlation import MIN_ENDPOINTS, correlate_fleet


def event(path, *, reference="EXEC-0001", timestamp="2026-03-14T09:05:00+00:00", confirmed=True):
    return {"reference": reference, "timestamp": timestamp, "executable": path,
            "full_command_line": path, "execution_confirmed": confirmed,
            "source": "kernel audit log"}


def artifact(path, *, digest="a" * 64):
    return {"path": path, "filename": path.rsplit("/", 1)[-1], "hash": digest,
            "reference": "ART-0001"}


# --- downloads ----------------------------------------------------------------
def test_a_downloaded_file_that_ran_is_linked():
    path = "/home/a/Downloads/tool.sh"
    findings = correlate_downloads(
        execution={"events": [event(path)]}, artifacts={"artifacts": [artifact(path)]},
        browser={"downloads": [{"url": "http://example.invalid/tool.sh", "target_path": path,
                                "started_at": "2026-03-14T09:00:00+00:00"}]})
    assert len(findings) == 1
    assert findings[0]["category"] == "download_executed"
    kinds = {ref["kind"] for ref in findings[0]["evidence_references"]}
    assert {"browser_download", "artifact", "execution_event"} <= kinds


def test_the_link_does_not_claim_the_download_was_malicious():
    path = "/home/a/Downloads/tool.sh"
    finding = correlate_downloads(
        execution={"events": [event(path)]}, artifacts={"artifacts": [artifact(path)]},
        browser={"downloads": [{"url": "http://example.invalid/tool.sh", "target_path": path,
                                "started_at": "2026-03-14T09:00:00+00:00"}]})[0]
    assert "ordinary on a workstation" in finding["explanation"]
    assert finding["unknowns"]


def test_a_download_far_from_an_execution_is_not_linked():
    """A day-old download and a run today are not one sequence."""
    path = "/home/a/Downloads/tool.sh"
    findings = correlate_downloads(
        execution={"events": [event(path, timestamp="2026-04-01T09:00:00+00:00")]},
        artifacts={"artifacts": []},
        browser={"downloads": [{"url": "u", "target_path": path,
                                "started_at": "2026-03-14T09:00:00+00:00"}]})
    assert findings == []


def test_a_download_with_no_matching_evidence_produces_nothing():
    findings = correlate_downloads(
        execution={"events": []}, artifacts={"artifacts": []},
        browser={"downloads": [{"url": "u", "target_path": "/tmp/never-seen",
                                "started_at": "2026-03-14T09:00:00+00:00"}]})
    assert findings == []


def test_a_present_but_unexecuted_download_is_reported_more_weakly():
    path = "/home/a/Downloads/tool.sh"
    finding = correlate_downloads(
        execution={"events": []}, artifacts={"artifacts": [artifact(path)]},
        browser={"downloads": [{"url": "u", "target_path": path,
                                "started_at": "2026-03-14T09:00:00+00:00"}]})[0]
    assert finding["category"] == "download_present"
    assert finding["severity"] == "low"


# --- removable media ----------------------------------------------------------
def test_a_copy_onto_removable_media_is_reported():
    mount = "/media/a/STICK"
    findings = correlate_removable_media(
        execution={"events": [event(f"{mount}/records.tar.gz")]},
        artifacts={"artifacts": [artifact(f"{mount}/records.tar.gz"),
                                 artifact("/tmp/records.tar.gz")]},
        usb={"mounts": [{"device": "/dev/sdb1", "mount_point": mount}],
             "events": [{"action": "connected", "timestamp": "2026-03-14T09:00:00+00:00"}],
             "devices": [{"serial": "AA77"}]})
    assert len(findings) == 1
    assert "share a hash" in findings[0]["explanation"]
    assert findings[0]["severity"] == "high"


def test_media_activity_does_not_assume_the_copy_was_unauthorized():
    mount = "/media/a/STICK"
    finding = correlate_removable_media(
        execution={"events": [event(f"{mount}/x")]},
        artifacts={"artifacts": [artifact(f"{mount}/x")]},
        usb={"mounts": [{"device": "/dev/sdb1", "mount_point": mount}], "events": [],
             "devices": []})[0]
    assert "normal part of most jobs" in finding["explanation"]


def test_a_mount_with_no_activity_produces_nothing():
    findings = correlate_removable_media(
        execution={"events": []}, artifacts={"artifacts": []},
        usb={"mounts": [{"device": "/dev/sdb1", "mount_point": "/media/a/STICK"}]})
    assert findings == []


def test_correlate_sources_runs_with_nothing_collected():
    assert correlate_sources() == []


# --- cross-host ---------------------------------------------------------------
def _task(endpoint, source, result):
    return {"endpoint_id": endpoint, "source": source, "status": "succeeded", "result": result}


def test_an_observable_on_one_host_is_not_a_correlation():
    fleet = correlate_fleet(
        [_task("EP-1", "NETWORK", {"connections": [{"remote_address": "198.51.100.7"}]})],
        endpoints=[{"id": "EP-1", "name": "a"}])
    assert fleet["correlations"] == []
    assert any(str(MIN_ENDPOINTS) in limit for limit in fleet["limitations"])


def test_a_shared_address_across_hosts_is_reported():
    tasks = [_task(f"EP-{index}", "NETWORK",
                   {"connections": [{"remote_address": "198.51.100.7", "remote_port": 443}]})
             for index in (1, 2)]
    fleet = correlate_fleet(tasks, endpoints=[{"id": "EP-1", "name": "a"},
                                              {"id": "EP-2", "name": "b"}])
    assert fleet["correlation_count"] == 1
    assert fleet["correlations"][0]["value"] == "198.51.100.7"


def test_loopback_and_link_local_addresses_are_not_correlated():
    tasks = [_task(f"EP-{index}", "NETWORK", {"connections": [
        {"remote_address": "127.0.0.1"}, {"remote_address": "169.254.1.1"},
        {"remote_address": "0.0.0.0"}]}) for index in (1, 2)]
    assert correlate_fleet(tasks)["correlations"] == []


def test_a_fleet_wide_driver_is_counted_not_listed():
    tasks = [_task(f"EP-{index}", "DRIVERS", {"drivers": [
        {"name": "ext4", "verification": {"risk_status": "UNKNOWN"}}]}) for index in (1, 2)]
    fleet = correlate_fleet(tasks)
    assert fleet["correlations"] == []
    assert fleet["suppressed"]["driver"] == 1


def test_a_fleet_wide_driver_is_still_listed_when_it_is_known_abused():
    tasks = [_task(f"EP-{index}", "DRIVERS", {"drivers": [
        {"name": "bad.sys", "verification": {"risk_status": "MATCHED"}}]}) for index in (1, 2)]
    fleet = correlate_fleet(tasks)
    assert fleet["correlation_count"] == 1
    assert fleet["correlations"][0]["notable"] is True


def test_a_usb_root_hub_is_not_treated_as_a_shared_device():
    """Root hubs report their PCI address as a serial; that is not a device."""
    tasks = [_task(f"EP-{index}", "USB", {"devices": [
        {"serial": "0000:08:00.3", "vendor": "v", "product": "xHCI Host Controller",
         "removable": "unknown"},
        {"serial": "000000000", "vendor": "v", "product": "p", "removable": "removable"}]})
        for index in (1, 2)]
    assert correlate_fleet(tasks)["correlations"] == []


def test_a_real_removable_device_seen_on_two_hosts_is_reported():
    tasks = [_task(f"EP-{index}", "USB", {"devices": [
        {"serial": "AA7712FF0931", "vendor": "Kingston", "product": "DataTraveler",
         "removable": "removable"}]}) for index in (1, 2)]
    fleet = correlate_fleet(tasks)
    assert fleet["correlation_count"] == 1
    assert "AA7712FF0931" in fleet["correlations"][0]["value"]


def test_downloads_are_keyed_on_origin_as_well_as_filename():
    """Two unrelated files both named report.pdf are not one observable."""
    tasks = [
        _task("EP-1", "BROWSER", {"downloads": [{"target_path": "/a/report.pdf",
                                                 "url": "http://one.invalid/report.pdf"}]}),
        _task("EP-2", "BROWSER", {"downloads": [{"target_path": "/b/report.pdf",
                                                 "url": "http://two.invalid/report.pdf"}]}),
    ]
    assert correlate_fleet(tasks)["correlations"] == []


def test_a_failed_task_contributes_nothing():
    tasks = [_task("EP-1", "NETWORK", {"connections": [{"remote_address": "198.51.100.7"}]}),
             {"endpoint_id": "EP-2", "source": "NETWORK", "status": "abandoned", "result": None}]
    fleet = correlate_fleet(tasks)
    assert fleet["endpoint_count"] == 1
    assert any("is not evidence that it is clean" in limit for limit in fleet["limitations"])
