"""
The memory-analysis workflow: register, hash, analyse, normalize, link.

A memory image is evidence like any other, so it goes through the evidence
workflow first -- registered, hashed, provenance recorded -- and only then is
analysed. The result carries the digest of the image it came from, so a finding
derived from memory can be traced to the exact bytes that produced it.

JOCKY does not acquire memory and does not parse images itself. It drives
existing read-only tooling. Where no tool is present the workflow says so and
stops, rather than producing an empty result that reads like an absence of
findings.
"""

from __future__ import annotations

import json
import logging

from analysis.detections import detect_memory
from analysis.memory import FIXTURE, REAL, UNAVAILABLE, analyze_memory_image, available_tool
from backend.casework import CaseworkError
from backend.storage import encode, identifier, now
from backend.versions import versions

QUEUED, RUNNING, COMPLETED, FAILED = "QUEUED", "RUNNING", "COMPLETED", "FAILED"


class MemoryWorkflow:
    """Registration through to normalized, linked memory evidence."""

    def __init__(self, store, casework):
        self.store, self.casework = store, casework

    def capability(self) -> dict:
        """What this host can actually do with a memory image, said plainly."""
        tool = available_tool()
        return {
            "tool_available": bool(tool),
            "tool": tool["name"] if tool else None,
            "tool_path": tool["path"] if tool else None,
            "acquires_memory": False,
            "parses_images_itself": False,
            "read_only": True,
            "detail": (f"{tool['name']} is installed and will be driven read-only."
                       if tool else
                       "No supported memory-analysis tool is installed. JOCKY drives existing "
                       "read-only tooling rather than parsing images itself; without one, a "
                       "registered image can be hashed and preserved but not analysed."),
        }

    def register_image(self, data: dict) -> dict:
        """Register a memory image as an evidence source before analysing it."""
        record = self.casework.register_evidence({
            **data,
            "source_type": "memory_image",
            "description": data.get("description") or "Memory image for analysis",
            "collector": data.get("collector") or "investigator-supplied memory image",
        })
        with self.store.transaction() as db:
            db.execute(
                "UPDATE evidence_sources SET container_format=?,format_detail=? WHERE id=?",
                ("raw", "Treated as a raw image. JOCKY does not convert or repackage evidence.",
                 record["id"]))
        return self.casework.get_evidence(record["id"])

    def analyse(self, data: dict) -> dict:
        """Run one analysis over a registered image, or over a fixture.

        The image is re-verified immediately before analysis. Analysing bytes
        that no longer match what was registered would produce evidence
        attributed to a source it did not come from.
        """
        evidence_id = data.get("evidence_source_id")
        fixture = data.get("fixture")
        image_path, digest = data.get("image_path"), None

        if evidence_id:
            source = self.casework.verify_evidence(evidence_id)
            if source["verification_state"] == "MISMATCH":
                raise CaseworkError(
                    f"{evidence_id} no longer matches the digest it was registered with. It is not "
                    "the image that was acquired, and JOCKY will not attribute findings to it.",
                    "conflict", 409)
            if source["verification_state"] == "MISSING":
                raise CaseworkError(f"{evidence_id} is no longer present at its recorded path",
                                    "not_found", 404)
            image_path = source["stored_path"] or source["original_path"]
            digest = source["sha256"]
        elif not fixture and not image_path:
            raise CaseworkError(
                "Analysis needs either a registered evidence_source_id, an image_path, or a "
                "fixture. JOCKY does not acquire memory.")

        analysis_id = f"MEM-{identifier()[:8].upper()}"
        case_id = data.get("case_id")
        investigation_id = data.get("investigation_id")
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO memory_analyses (id,investigation_id,case_id,evidence_source_id,"
                " image_path,image_sha256,tool,provenance,status,started_at,versions)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (analysis_id, investigation_id, case_id, evidence_id, image_path, digest,
                 None, UNAVAILABLE, RUNNING, now(), encode(versions())))
            self.casework.audit("memory.analysis_started", object_type="memory_analysis",
                                object_id=analysis_id, case_id=case_id,
                                investigation_id=investigation_id,
                                detail={"evidence_source": evidence_id, "sha256": digest}, db=db)

        try:
            result = analyze_memory_image(image_path, fixture=fixture, image_sha256=digest,
                                          evidence_source_id=evidence_id)
            findings = detect_memory(result)
            status, error = COMPLETED, None
        except Exception as exception:  # recorded, never swallowed
            logging.exception("Memory analysis failed")
            result, findings = {"provenance": UNAVAILABLE}, []
            status, error = FAILED, {"code": "analysis_failed", "message": str(exception)}

        result["findings"] = findings
        with self.store.transaction() as db:
            db.execute(
                "UPDATE memory_analyses SET status=?,completed_at=?,result=?,error=?,tool=?,"
                " plugin=?,provenance=? WHERE id=?",
                (status, now(), encode(result), encode(error) if error else None,
                 result.get("tool"), json.dumps(result.get("plugins") or {}),
                 result.get("provenance", UNAVAILABLE), analysis_id))
            if evidence_id:
                db.execute("UPDATE evidence_sources SET processing_status=? WHERE id=?",
                           ("ANALYSED" if status == COMPLETED else "ANALYSIS_FAILED", evidence_id))
            self.casework.audit(
                "memory.analysis_finished", object_type="memory_analysis", object_id=analysis_id,
                case_id=case_id, investigation_id=investigation_id,
                outcome="success" if status == COMPLETED else "failed",
                detail={"provenance": result.get("provenance"),
                        "processes": len(result.get("processes") or []),
                        "findings": len(findings)}, db=db)
        return self.get(analysis_id)

    def get(self, analysis_id: str) -> dict:
        rows = self.store.rows("SELECT * FROM memory_analyses WHERE id=?", (analysis_id,))
        if not rows:
            raise CaseworkError("Memory analysis not found", "not_found", 404)
        record = rows[0]
        for key in ("result", "error", "versions", "plugin"):
            record[key] = json.loads(record[key]) if record[key] else None
        record["provenance_statement"] = self._provenance_statement(record)
        return record

    def list(self, *, case_id=None, investigation_id=None, limit=200) -> list:
        clauses, args = [], []
        for column, value in (("case_id", case_id), ("investigation_id", investigation_id)):
            if value:
                clauses.append(f"{column}=?")
                args.append(value)
        query = "SELECT id FROM memory_analyses"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        rows = self.store.rows(query + " ORDER BY started_at DESC LIMIT ?",
                               tuple(args) + (int(limit),))
        return [self.get(row["id"]) for row in rows]

    @staticmethod
    def _provenance_statement(record) -> str:
        """One sentence a reader can rely on about where this evidence came from."""
        provenance = record.get("provenance")
        if provenance == REAL:
            return (f"Produced by {record.get('tool')} reading the image at "
                    f"{record.get('image_path')}"
                    + (f", SHA-256 {record.get('image_sha256')}" if record.get("image_sha256")
                       else ", whose digest was not recorded")
                    + ". The image was not modified.")
        if provenance == FIXTURE:
            return ("Produced from a recorded or synthetic fixture. This is not evidence about any "
                    "real machine and must not be presented as such.")
        return ("No memory evidence was produced. Nothing should be concluded from the absence of "
                "memory findings in this investigation.")
