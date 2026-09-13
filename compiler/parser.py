from pathlib import Path

from lark import Lark, UnexpectedInput

from .commands import Command, CommandSyntaxError, CommandValidationError
from .Transformer import JockyTransformer

BASE_DIR = Path(__file__).resolve().parent
parser = Lark((BASE_DIR / "grammar.lark").read_text(encoding="utf-8"), start="start")


def parse_validated_command(text: str) -> Command:
    if not isinstance(text, str):
        raise CommandValidationError("Command must be a string")
    if not text.strip():
        raise CommandValidationError("Command cannot be empty")
    if any((ord(char) < 32 and char != "\t") or ord(char) == 127 for char in text):
        raise CommandSyntaxError("Only one command line is supported; control characters are not allowed")
    try:
        tree = parser.parse(text.strip(" \t"))
    except UnexpectedInput as error:
        line, column = max(1, error.line or 1), max(1, error.column or 1)
        raise CommandSyntaxError(
            f"Invalid command syntax at line {line}, column {column}. "
            "Quote paths containing spaces; use a supported command form.", line, column,
        ) from error
    return Command(**JockyTransformer().transform(tree))


def parse_command(command: str) -> dict:
    """Backward-compatible entry point returning the original dictionary shape."""
    return parse_validated_command(command).to_dispatch_dict()
