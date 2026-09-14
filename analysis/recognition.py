"""
Software recognition from evidence, not from filenames.

An investigator should not have to research `/usr/bin/python3` because the raw
record is unfamiliar. But the reason JOCKY can say what that file is must be
evidence about *this* machine, not a list of names someone typed into the
source. A file called `python3` sitting in `/tmp` is not Python, and a
recognition layer that says otherwise is worse than none.

So recognition is layered over things the system already records:

  package ownership   the package manager states which package owns this exact
                      path, with a version. This alone covers the whole
                      distribution -- 400,000-odd paths here -- with nothing
                      hardcoded.
  snap metadata       a path under /snap/<name>/ whose meta/snap.yaml names and
                      versions it.
  vendor layout       a small curated set of descriptors for software that
                      installs outside any package manager, each requiring a
                      marker file to be present, not just a directory name.
  trusted location    an OS-managed directory. Weak on its own, and reported as
                      "in an OS-managed location", never as an identity.

Nothing here executes anything. Running `--version` would be the obvious way to
get a version number and is exactly what a forensic tool must not do: it changes
the machine under examination and it runs a binary whose provenance is the open
question. Versions come from metadata that is already on disk.

Recognition is never a safety verdict. It answers "what is this", and the
triage layer decides separately what the surrounding evidence says. A recognized
program in an unusual place, downloaded and run, is still a lead.
"""

from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path

RECOGNITION_VERSION = 1

HIGH, MODERATE, LOW, NONE = "HIGH", "MODERATE", "LOW", "NONE"

#: Where package managers record which file belongs to which package.
DPKG_INFO = "/var/lib/dpkg/info"
DPKG_STATUS = "/var/lib/dpkg/status"
SNAP_ROOT = "/snap"
REFERENCE_PATH = Path(__file__).with_name("data") / "software_reference.json"

#: Directories the operating system manages. Being here is not an identity and
#: is reported as a location, never as a name.
TRUSTED_LOCATIONS = (
    "/usr/bin/", "/usr/sbin/", "/bin/", "/sbin/", "/usr/lib/", "/usr/libexec/",
    "/usr/share/", "/lib/", "/usr/local/bin/", "/usr/local/lib/", "/usr/local/sbin/",
)

#: A path under one of these is not OS-managed however familiar its name looks.
UNTRUSTED_PREFIXES = ("/tmp/", "/var/tmp/", "/dev/shm/", "/run/user/")

MAX_INDEXED_PACKAGES = 20000
MAX_SNAP_ENTRIES = 500


def _normalize(path):
    if not path:
        return ""
    text = str(path).replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text


class SoftwareIndex:
    """Everything recognition reads, gathered once.

    Built once per collection and reused for every artifact and event. Doing
    this per record would mean re-reading a hundred megabytes of package
    metadata for each one, which is how a recognition layer makes an
    investigator's screen slow.
    """

    def __init__(self, *, dpkg_info=DPKG_INFO, dpkg_status=DPKG_STATUS,
                 snap_root=SNAP_ROOT, reference_path=REFERENCE_PATH):
        self.paths: dict[str, str] = {}
        self.packages: dict[str, dict] = {}
        self.snaps: dict[str, dict] = {}
        self.vendors: list[dict] = []
        self.sources: list[dict] = []
        # Kept so matching uses the root this index was built over, not the
        # module default. A configurable root that matching ignores is a
        # configuration option that silently does nothing.
        self.snap_root = _normalize(snap_root).rstrip("/")
        self._load_dpkg(dpkg_info, dpkg_status)
        self._load_snaps(snap_root)
        self._load_reference(reference_path)

    # --- package manager --------------------------------------------------
    def _load_dpkg(self, info_directory, status_path):
        listings = sorted(glob.glob(os.path.join(info_directory, "*.list")))[:MAX_INDEXED_PACKAGES]
        if not listings:
            self.sources.append({"source": "dpkg", "status": "NOT_AVAILABLE",
                                 "detail": f"No package file lists under {info_directory}."})
            return
        for listing in listings:
            package = os.path.basename(listing)[:-5].split(":")[0]
            try:
                with open(listing, encoding="utf-8", errors="replace") as handle:
                    for line in handle:
                        entry = line.rstrip("\n")
                        if entry and entry != "/.":
                            self.paths.setdefault(_normalize(entry), package)
            except OSError:
                continue
        self._load_dpkg_status(status_path)
        self.sources.append({"source": "dpkg", "status": "AVAILABLE",
                             "detail": f"{len(self.paths)} paths from {len(listings)} packages."})

    def _load_dpkg_status(self, status_path):
        """Package name, version and origin, from the installed-package status."""
        try:
            text = Path(status_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        for block in text.split("\n\n"):
            if not block.strip():
                continue
            fields = {}
            for line in block.splitlines():
                if line.startswith((" ", "\t")):
                    continue
                key, _, value = line.partition(":")
                fields[key.strip().lower()] = value.strip()
            name = fields.get("package")
            if name:
                self.packages[name] = {
                    "package": name, "version": fields.get("version"),
                    "origin": fields.get("maintainer"), "section": fields.get("section"),
                    "description": (fields.get("description") or "").split("\n")[0] or None,
                    "status": fields.get("status"),
                }

    # --- snap --------------------------------------------------------------
    def _load_snaps(self, snap_root):
        metas = sorted(glob.glob(os.path.join(snap_root, "*", "current", "meta", "snap.yaml")))
        if not metas:
            self.sources.append({"source": "snap", "status": "NOT_AVAILABLE",
                                 "detail": f"No snap metadata under {snap_root}."})
            return
        for meta in metas[:MAX_SNAP_ENTRIES]:
            fields = {}
            try:
                with open(meta, encoding="utf-8", errors="replace") as handle:
                    for line in handle:
                        if line.startswith((" ", "\t", "-")) or ":" not in line:
                            continue
                        key, _, value = line.partition(":")
                        fields[key.strip().lower()] = value.strip()
            except OSError:
                continue
            name = fields.get("name") or meta.split(os.sep)[-4]
            self.snaps[name] = {
                "name": name, "title": fields.get("title") or name,
                "version": fields.get("version"), "summary": fields.get("summary"),
                "meta_path": meta,
            }
        self.sources.append({"source": "snap", "status": "AVAILABLE",
                             "detail": f"{len(self.snaps)} installed snaps."})

    # --- curated vendor layouts -------------------------------------------
    def _load_reference(self, reference_path):
        try:
            data = json.loads(Path(reference_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.sources.append({"source": "vendor reference", "status": "NOT_AVAILABLE",
                                 "detail": f"Could not read {reference_path}."})
            return
        self.vendors = data.get("entries", [])
        self.reference_meta = {"name": data.get("name"), "version": data.get("version"),
                               "entry_count": len(self.vendors)}
        self.sources.append({
            "source": "vendor reference", "status": "AVAILABLE",
            "detail": f"{len(self.vendors)} vendor layout descriptors "
                      f"(v{data.get('version')}). Each requires a marker file to be present."})


def _link_target(path):
    """Where a symbolic link points, if it is one. Reads metadata only."""
    try:
        if not os.path.islink(path):
            return None
        return _normalize(os.path.realpath(path))
    except OSError:
        return None


def _unrecognized(path, reason):
    return {
        "recognized": False, "recognized_name": None, "category": None, "description": None,
        "version": None, "confidence": NONE, "recognition_basis": [], "basis_codes": [],
        "source": None, "matched_evidence": [], "recognition_version": RECOGNITION_VERSION,
        "resolved_from": None, "limitations": [reason],
    }


def _result(*, name, category, version, confidence, basis, codes, source, limitations,
            description=None, evidence=(), recognized=True, resolved_from=None):
    return {
        "recognized": recognized, "recognized_name": name, "category": category,
        "description": description, "version": version, "confidence": confidence,
        "recognition_basis": list(basis), "basis_codes": list(codes), "source": source,
        "matched_evidence": list(evidence), "recognition_version": RECOGNITION_VERSION,
        "resolved_from": resolved_from, "limitations": list(limitations),
    }


def _read_version(marker_path, spec):
    """Read a version out of a vendor marker file. Never runs the program."""
    try:
        text = Path(marker_path).read_text(encoding="utf-8", errors="replace")[:16384]
    except OSError:
        return None
    if spec.get("version_json_key"):
        try:
            return str(json.loads(text).get(spec["version_json_key"]) or "") or None
        except ValueError:
            return None
    if spec.get("version_regex"):
        match = re.search(spec["version_regex"], text)
        return match.group(1) if match else None
    first = text.strip().splitlines()[0] if text.strip() else ""
    return first[:64] or None


def _vendor_match(path, index):
    """A curated layout descriptor, which must find its marker file on disk."""
    for entry in index.vendors:
        prefix = entry.get("path_contains")
        if not prefix or prefix not in path:
            continue
        root = path[: path.index(prefix) + len(prefix)].rstrip("/")
        marker = os.path.join(root, entry["marker"]) if entry.get("marker") else None
        if marker and not os.path.exists(marker):
            # The directory name alone proves nothing. Anyone can make a folder
            # called "flutter"; only an installation has the marker inside it.
            continue
        version = _read_version(marker, entry) if marker else None
        basis = [f"The path lies under a {entry['name']} installation layout"]
        if marker:
            basis.append(f"the expected marker file {entry['marker']} is present at {root}")
        if version:
            basis.append(f"its metadata records version {version}")
        return _result(
            name=entry["name"], category=entry.get("category", "application"), version=version,
            confidence=entry.get("confidence", MODERATE),
            basis=[", ".join(basis) + "."], codes=["vendor_layout"],
            source=f"{entry['name']} installation at {root}",
            limitations=[
                "Layout recognition identifies an installation of this software. It does not "
                "verify the files are the vendor's, which would need a signature or a published "
                "hash."])
    return None


def _snap_match(path, index):
    root = getattr(index, "snap_root", SNAP_ROOT)
    if not path.startswith(root + "/"):
        return None
    name = path[len(root) + 1:].split("/")[0]
    record = index.snaps.get(name)
    if not record:
        return None
    version = record.get("version")
    return _result(
        name=record.get("title") or name, category="snap package", version=version,
        confidence=HIGH,
        basis=[f"The path is inside the installed snap '{name}'"
               + (f", which its metadata versions as {version}" if version else "") + "."],
        codes=["snap_metadata"], source=f"snap metadata at {record['meta_path']}",
        limitations=["Snap metadata states what the snap declares about itself."])


def _package_match(path, index):
    package = index.paths.get(path)
    if not package:
        return None
    details = index.packages.get(package, {})
    version = details.get("version")
    description = details.get("description")
    basis = [f"The package manager records that '{package}' owns exactly this path"
             + (f", at version {version}" if version else "") + "."]
    if details.get("origin"):
        basis.append(f"The package originates from {details['origin']}.")
    return _result(
        name=package, description=description,
        category=details.get("section") or "operating system package",
        version=version, confidence=HIGH, basis=basis, codes=["package_manager_ownership"],
        source=f"dpkg package {package}" + (f" {version}" if version else ""),
        limitations=[
            "Package ownership establishes which package placed a file at this path. It does not "
            "establish that the bytes now there are still the package's; compare the hash against "
            "the distribution to check that."])


def recognize_path(path, index) -> dict:
    """What, if anything, JOCKY can say this path is.

    Order is by strength of evidence. A weaker layer never overrides a stronger
    one, and a location-only answer is deliberately not an identity.
    """
    normalized = _normalize(path)
    if not normalized:
        return _unrecognized(path, "No path was recorded, so nothing could be looked up.")

    for matcher in (_package_match, _snap_match, _vendor_match):
        result = matcher(normalized, index)
        if result:
            return result

    # /usr/bin/code is a link into /usr/share/code. Reading where a link points
    # is a metadata read like any other; it is not running anything. The result
    # records that the answer came from the target so the investigator can see
    # the step that was taken.
    target = _link_target(normalized)
    if target and target != normalized:
        for matcher in (_package_match, _snap_match, _vendor_match):
            result = matcher(target, index)
            if result:
                result["resolved_from"] = normalized
                result["recognition_basis"].append(
                    f"{normalized} is a symbolic link to {target}, which is what was identified.")
                return result

    if normalized.startswith(UNTRUSTED_PREFIXES):
        return _unrecognized(
            normalized,
            "No package, snap or known installation layout accounts for this path, and it is in a "
            "world-writable location. A familiar-looking filename here is not evidence of what the "
            "file is.")
    if normalized.startswith(TRUSTED_LOCATIONS):
        # Deliberately not "recognized". Knowing where a file sits is not
        # knowing what it is, and a file in a system directory that no package
        # placed there is precisely the case worth telling an investigator
        # about rather than quietly reassuring them.
        return _result(
            recognized=False, name=None, version=None, confidence=LOW,
            category="unattributed file in an OS-managed location",
            basis=[f"The path is in {os.path.dirname(normalized)}, a directory the operating "
                   "system manages, but no package claims it."],
            codes=["trusted_system_location"], source="filesystem location",
            limitations=[
                "This says where the file is, not what it is. A file placed in a system directory "
                "by something other than the package manager looks exactly like this, and which "
                "of the two it is matters."])
    return _unrecognized(
        normalized,
        "No package, snap or known installation layout accounts for this path.")


def recognize_artifacts(artifacts, *, index=None) -> dict:
    """Attach a recognition result to every artifact record, in place.

    Returns a summary for the report. Recognition is computed once here, during
    analysis, and persisted with the record: recomputing it per screen render
    would re-read the package database every time an investigator scrolled.
    """
    index = index or SoftwareIndex()
    recognized, by_name = 0, {}
    for record in artifacts or []:
        result = recognize_path(record.get("path"), index)
        result["matched_evidence"] = [record["reference"]] if record.get("reference") else []
        record["recognition"] = result
        if result["recognized"]:
            recognized += 1
            key = result["recognized_name"]
            entry = by_name.setdefault(key, {"name": key, "category": result["category"],
                                             "version": result["version"], "count": 0,
                                             "confidence": result["confidence"],
                                             "basis_codes": result["basis_codes"],
                                             "evidence": []})
            entry["count"] += 1
            entry["evidence"].extend(result["matched_evidence"])
    return {
        "recognition_version": RECOGNITION_VERSION,
        "artifacts_examined": len(artifacts or []),
        "artifacts_recognized": recognized,
        "software": sorted(by_name.values(), key=lambda item: (-item["count"], item["name"] or "")),
        "sources": index.sources,
        "note": ("Recognition states what a file is, on the evidence of package metadata and "
                 "installation layout. It is not a statement that the file is safe, and it never "
                 "suppresses a concern signal."),
    }


def recognize_events(events, *, index=None) -> dict:
    """Attach recognition to execution and command evidence.

    An event is recognized by its executable, never by its process name: the
    name is what the record says it called itself, and that is the one field an
    attacker chooses freely.
    """
    index = index or SoftwareIndex()
    recognized = 0
    for event in events or []:
        image = event.get("executable")
        if not image:
            event["recognition"] = _unrecognized(
                None, "This record names no executable path, so there was nothing to look up. "
                      "A process name alone is not evidence of what ran.")
            continue
        result = recognize_path(image, index)
        result["matched_evidence"] = [event["reference"]] if event.get("reference") else []
        event["recognition"] = result
        recognized += result["recognized"]
    return {"events_examined": len(events or []), "events_recognized": recognized}
