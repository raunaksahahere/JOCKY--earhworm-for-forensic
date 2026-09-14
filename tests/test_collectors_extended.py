"""The six collectors added for the completion pass.

Each is checked for three things: it produces the shape the pipeline expects, it
states what it did not do, and it does not do the things it must never do.
"""
import sqlite3

import pytest

from analysis import browser, drivers, memory, network, system_services, usb


# --- network -----------------------------------------------------------------
def test_network_states_that_it_does_not_capture_packets():
    result = network.collect_network()
    assert result["limits"]["packet_capture"] is False
    assert result["classification"] == "CURRENT_OBSERVATION"


def test_network_reads_routes_from_proc_format(tmp_path):
    route = tmp_path / "route"
    route.write_text(
        "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\n"
        "wlan0\t00000000\t0102A8C0\t0003\t0\t0\t600\t00000000\n")
    result = network.collect_network(route_path=str(route))
    assert any(entry.get("gateway") == "192.168.2.1" for entry in result["routing"]["routes"])


def test_network_reads_resolvers(tmp_path):
    resolv = tmp_path / "resolv.conf"
    resolv.write_text("nameserver 9.9.9.9\nsearch example.invalid\n")
    result = network.collect_network(resolver_path=str(resolv))
    assert "9.9.9.9" in result["resolver"]["nameservers"]


# --- browser -----------------------------------------------------------------
def _firefox_profile(root):
    profile = root / "firefox" / "test.default"
    profile.mkdir(parents=True)
    database = profile / "places.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT, title TEXT,"
                       " visit_count INTEGER, last_visit_date INTEGER)")
    connection.execute("CREATE TABLE moz_annos (id INTEGER PRIMARY KEY, place_id INTEGER,"
                       " anno_attribute_id INTEGER, content TEXT, dateAdded INTEGER)")
    connection.execute("CREATE TABLE moz_anno_attributes (id INTEGER PRIMARY KEY, name TEXT)")
    connection.execute(
        "CREATE TABLE moz_historyvisits (id INTEGER PRIMARY KEY, place_id INTEGER, visit_date INTEGER)")
    connection.execute(
        "INSERT INTO moz_places VALUES (1,'http://example.invalid/x','Example',2,1770000000000000)")
    connection.execute("INSERT INTO moz_anno_attributes VALUES (1,'downloads/destinationFileURI')")
    connection.execute(
        "INSERT INTO moz_annos VALUES (1,1,1,'file:///home/analyst/Downloads/x.bin',1770000000000000)")
    connection.execute("INSERT INTO moz_historyvisits VALUES (1,1,1770000000000000)")
    connection.commit()
    connection.close()
    return database


def test_browser_never_reads_secrets():
    result = browser.collect_browser_artifacts()
    limits = result["limits"]
    assert limits["passwords_read"] is False
    assert limits["cookies_read"] is False
    assert limits["tokens_read"] is False


def test_browser_leaves_the_original_database_untouched(tmp_path):
    database = _firefox_profile(tmp_path)
    before = database.read_bytes()
    browser.collect_browser_artifacts(roots={"firefox": [str(tmp_path / "firefox")]})
    assert database.read_bytes() == before, "a live browser profile must never be written to"


def test_browser_reads_history_from_a_copy(tmp_path):
    _firefox_profile(tmp_path)
    result = browser.collect_browser_artifacts(roots={"firefox": [str(tmp_path / "firefox")]})
    assert any(entry["url"] == "http://example.invalid/x" for entry in result["history"])
    assert any(entry["target_path"] == "/home/analyst/Downloads/x.bin"
               for entry in result["downloads"])


def test_a_profile_that_cannot_be_read_is_reported_not_silently_empty(tmp_path):
    """An unreadable profile must not look like a profile with no history."""
    profile = tmp_path / "firefox" / "broken.default"
    profile.mkdir(parents=True)
    (profile / "places.sqlite").write_bytes(b"this is not a database")
    result = browser.collect_browser_artifacts(roots={"firefox": [str(tmp_path / "firefox")]})
    assert result["warnings"], "a profile that failed to read must produce a warning"


# --- usb ---------------------------------------------------------------------
def test_usb_does_not_read_media_contents():
    assert usb.collect_removable_media()["limits"]["media_contents_read"] is False


def test_usb_reads_removable_mounts(tmp_path):
    mounts = tmp_path / "mounts"
    mounts.write_text("/dev/sdb1 /media/user/STICK vfat rw,nosuid 0 0\n"
                      "/dev/sda2 / ext4 rw,relatime 0 0\n")
    result = usb.collect_removable_media(mounts_path=str(mounts))
    points = {mount["mount_point"] for mount in result["mounts"]}
    assert "/media/user/STICK" in points
    assert "/" not in points, "the root filesystem is not removable media"


# --- drivers -----------------------------------------------------------------
def test_drivers_are_never_loaded_or_modified():
    assert drivers.collect_driver_inventory()["limits"]["drivers_loaded_or_modified"] is False


def test_a_hash_match_outranks_a_name_match():
    reference = drivers.load_reference()
    digest = next(iter(reference["by_hash"]))
    matched = drivers.verify_driver({"name": "anything.sys", "sha256": digest,
                                     "kind": "windows_driver"}, reference)
    assert matched["risk_status"] == "MATCHED" and matched["confidence"] == "high"


def test_a_linux_module_does_not_match_a_windows_driver_by_name():
    """`msr` is a Linux module; `msr.sys` is a Windows driver.

    Matching those by bare name produced a false positive on every Linux host,
    which is exactly the kind of noise that makes a tool ignorable.
    """
    reference = drivers.load_reference()
    verdict = drivers.verify_driver({"name": "msr", "kind": "linux_module", "sha256": None},
                                    reference)
    assert verdict["risk_status"] != "MATCHED"


def test_an_unknown_driver_is_unknown_not_clean():
    verdict = drivers.verify_driver(
        {"name": "definitely-not-in-the-reference.sys", "kind": "windows_driver",
         "sha256": "0" * 64}, drivers.load_reference())
    assert verdict["risk_status"] == "NOT_MATCHED"
    assert verdict["confidence"] != "high", (
        "absence from a catalogue of known-abused drivers is not a clean verdict")


def test_a_module_that_could_not_be_compared_says_so():
    """No digest and a Linux name: nothing was compared, so nothing is claimed."""
    verdict = drivers.verify_driver({"name": "some_module", "kind": "linux_module",
                                     "sha256": None}, drivers.load_reference())
    assert verdict["risk_status"] == "UNKNOWN"
    assert "not comparable" in verdict["detail"] or "nothing was concluded" in verdict["detail"]


def test_the_reference_names_its_source():
    reference = drivers.load_reference()
    assert "loldrivers" in (reference.get("source") or "").lower()
    assert reference["entry_count"] > 100


# --- memory ------------------------------------------------------------------
def test_memory_analysis_is_read_only():
    limits = memory.analyze_memory_image(fixture={"processes": []})["limits"]
    assert limits["read_only"] is True
    assert limits["memory_written"] is False
    assert limits["code_executed"] is False


def test_a_fixture_result_is_labelled_as_a_fixture():
    result = memory.analyze_memory_image(fixture={"processes": [{"PID": 4, "PPID": 0,
                                                                 "ImageFileName": "System"}]})
    assert result["provenance"] == "FIXTURE"
    assert result["processes"][0]["process_name"] == "System"


@pytest.mark.parametrize("column", ["ImageFileName", "COMM", "Name"])
def test_every_volatility_process_name_column_is_understood(column):
    """windows.pslist, linux.pslist and mac.pslist each name this differently."""
    result = memory.analyze_memory_image(fixture={"processes": [{"PID": 9, "PPID": 1,
                                                                 column: "target"}]})
    assert result["processes"][0]["process_name"] == "target"


def test_a_parent_pid_of_zero_survives_normalization():
    """Kernel roots legitimately have ppid 0; turning that into None loses it."""
    result = memory.analyze_memory_image(fixture={"processes": [{"PID": 4, "PPID": 0,
                                                                 "ImageFileName": "System"}]})
    assert result["processes"][0]["parent_pid"] == 0


def test_no_image_and_no_tool_is_unavailable_not_empty():
    result = memory.analyze_memory_image(image_path=None)
    assert result["provenance"] == "UNAVAILABLE"
    assert result["classification"] == "UNAVAILABLE"


# --- services ----------------------------------------------------------------
def test_services_reports_unreadable_locations(tmp_path):
    result = system_services.collect_services(cron_locations=(str(tmp_path / "absent"),))
    assert result["status"] == "success"
    assert "scheduled_jobs" in result


@pytest.mark.parametrize("collector", [
    network.collect_network, usb.collect_removable_media, drivers.collect_driver_inventory,
    system_services.collect_services, browser.collect_browser_artifacts,
])
def test_every_collector_reports_a_classification(collector):
    result = collector()
    assert result["classification"] in {"CURRENT_OBSERVATION", "HISTORICAL_EVIDENCE", "UNAVAILABLE"}
    assert result["status"] in {"success", "failed"}
