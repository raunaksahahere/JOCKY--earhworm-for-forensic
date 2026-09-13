"""
JOCKY dispatcher.

Routes a parsed command (produced by compiler.parser) to the matching
analysis module. Every action here is read-only forensic observation or
evidence-handling utility work -- there is no offensive, evasive, or
system-altering capability wired into this dispatcher.
"""

from analysis.files import list_files, search_file
from analysis.hashing import hash_file
from analysis.processes import list_processes
from analysis.system import get_system_info
from crypto.crypto import encrypt_file

SUPPORTED_ACTIONS = (
    "hash",
    "encrypt",
    "system_info",
    "processes",
    "list",
    "search",
)


def execute_command(parsed_command: dict) -> dict:
    action = parsed_command.get("action")

    if action == "hash":
        path = parsed_command.get("path")
        if not path:
            raise ValueError("No file path provided")
        return hash_file(path)

    if action == "encrypt":
        path = parsed_command.get("path")
        if not path:
            raise ValueError("No file path provided")
        return encrypt_file(path)

    if action == "system_info":
        return get_system_info()

    if action == "processes":
        return list_processes()

    if action == "list":
        path = parsed_command.get("path")
        return list_files(path)

    if action == "search":
        path = parsed_command.get("path")
        search_path = parsed_command.get("search_path")
        return search_file(path, search_path)

    raise ValueError(f"Unsupported action: {action}")
