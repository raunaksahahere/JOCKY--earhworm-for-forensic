"""Small validated command boundary; no filesystem access or path rewriting."""

from dataclasses import dataclass
from typing import Literal

SCHEMA_VERSION = 1
Action = Literal["hash", "encrypt", "list", "search", "system_info", "processes"]
_TARGETS = {"hash": "file", "encrypt": "file", "list": "files", "search": "file"}


class CommandError(ValueError):
    code = "invalid_command"
    kind = "validation"


class CommandSyntaxError(CommandError):
    code = "invalid_syntax"
    kind = "parser"

    def __init__(self, message: str, line: int = 1, column: int = 1):
        super().__init__(message)
        self.line = line
        self.column = column


class CommandValidationError(CommandError):
    pass


@dataclass(frozen=True)
class Command:
    action: Action
    target: str | None = None
    path: str | None = None
    search_path: str | None = None

    def __post_init__(self) -> None:
        if self.action not in (*_TARGETS, "system_info", "processes"):
            raise CommandValidationError(f"Unsupported action: {self.action}")
        expected_target = _TARGETS.get(self.action)
        if self.target != expected_target:
            raise CommandValidationError("Command target does not match its action")
        for field, required in (("path", expected_target is not None),
                                ("search_path", self.action == "search")):
            value = getattr(self, field)
            if not required:
                if value is not None:
                    raise CommandValidationError(f"Unexpected {field} for {self.action}")
            elif not isinstance(value, str) or not value.strip():
                raise CommandValidationError(f"{field} cannot be empty")
            elif any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise CommandValidationError(f"{field} contains a control character")

    def to_dispatch_dict(self) -> dict:
        """The original dispatcher shape, including omission of unused keys."""
        return {key: value for key, value in {
            "action": self.action, "target": self.target,
            "path": self.path, "search_path": self.search_path,
        }.items() if value is not None}

    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, **self.to_dispatch_dict()}
