"""
Structured metadata mirroring compiler/Language.md.

Kept separate from the grammar/parser so the frontend can render an
command reference via GET /commands. Regression tests validate its examples
against the grammar; this metadata is not generated from the grammar.
"""

LANGUAGE_REFERENCE = [
    {
        "name": "HASH",
        "syntax": "HASH FILE <path>",
        "example": "HASH FILE evidence.bin",
        "description": "Compute a SHA-256 digest of a file. Quote paths containing spaces.",
        "category": "integrity",
    },
    {
        "name": "ENCRYPT",
        "syntax": "ENCRYPT FILE <path>",
        "example": "ENCRYPT FILE evidence.bin",
        "description": "Reserved v1 syntax. Safe export requires an explicit destination and recovery passphrase through the evidence export API; this command fails without them.",
        "category": "evidence-handling",
    },
    {
        "name": "SYSTEM INFO",
        "syntax": "SYSTEM INFO",
        "example": "SYSTEM INFO",
        "description": "Collect read-only host system information (OS, CPU, memory, runtime).",
        "category": "system",
    },
    {
        "name": "LIST FILES",
        "syntax": "LIST FILES <path>",
        "example": "LIST FILES ./evidence",
        "description": "List files and directories at a given path with metadata.",
        "category": "filesystem",
    },
    {
        "name": "PROCESSES",
        "syntax": "PROCESSES",
        "example": "PROCESSES",
        "description": "Observe currently running processes (read-only).",
        "category": "system",
    },
    {
        "name": "SEARCH FILE",
        "syntax": "SEARCH FILE <name> IN <path>",
        "example": "SEARCH FILE malware.exe IN ./samples",
        "description": "Search a directory tree for files matching a name.",
        "category": "filesystem",
    },
]
