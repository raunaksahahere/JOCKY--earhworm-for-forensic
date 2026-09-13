"""
Static, read-only indicator heuristics.

These helpers only LABEL file names/extensions for analyst attention.
They never execute, modify, quarantine, or otherwise act on files, and
they never claim to make a malware verdict -- they surface conventional,
publicly documented triage heuristics used in defensive digital
forensics so a human analyst can decide what to look at next.
"""

from __future__ import annotations

# Extensions that commonly warrant a closer look during triage.
# Presence of one of these is a NEUTRAL, INFORMATIONAL flag only.
NOTABLE_EXTENSIONS = {
    ".exe": "Windows executable",
    ".dll": "Windows dynamic-link library",
    ".scr": "Windows screensaver executable (often disguised as documents)",
    ".bat": "Windows batch script",
    ".cmd": "Windows command script",
    ".ps1": "PowerShell script",
    ".vbs": "VBScript file",
    ".js": "JavaScript file (executes when opened by a script host)",
    ".jar": "Java archive (executable)",
    ".msi": "Windows installer package",
    ".sh": "Shell script",
}

# Document/media extensions that are frequently spoofed via a
# "double extension" trick, e.g. "invoice.pdf.exe".
COMMONLY_SPOOFED = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".jpeg", ".png", ".txt", ".zip"}


def evaluate_filename(filename: str) -> list[dict]:
    """Return a list of neutral, human-readable indicator labels for a filename.

    This is a static string-based heuristic only. It performs no file
    execution, no behavioral analysis, and no content scanning.
    """
    flags: list[dict] = []
    lower = filename.lower()
    parts = lower.split(".")

    ext = ""
    if "." in lower:
        ext = "." + parts[-1]

    if ext in NOTABLE_EXTENSIONS:
        flags.append(
            {
                "level": "info",
                "label": f"Notable extension ({ext})",
                "detail": NOTABLE_EXTENSIONS[ext],
            }
        )

    # Double-extension heuristic: e.g. report.pdf.exe
    if len(parts) >= 3:
        second_last = "." + parts[-2]
        if second_last in COMMONLY_SPOOFED and ext in NOTABLE_EXTENSIONS:
            flags.append(
                {
                    "level": "warning",
                    "label": "Possible extension spoofing",
                    "detail": (
                        f"File appears to combine a document-style extension "
                        f"({second_last}) with an executable extension ({ext})."
                    ),
                }
            )

    if lower.startswith(".") and len(lower) > 1:
        flags.append(
            {
                "level": "info",
                "label": "Hidden file",
                "detail": "Filename begins with a dot and may be hidden by default file listings.",
            }
        )

    return flags
