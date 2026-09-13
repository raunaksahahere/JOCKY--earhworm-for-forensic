import json

import pytest

from compiler.commands import Command, CommandError, CommandSyntaxError, CommandValidationError
from compiler.Language_meta import LANGUAGE_REFERENCE
from compiler.parser import parse_command, parse_validated_command


@pytest.mark.parametrize(("source", "expected"), [
    ("HASH FILE a.bin", {"action": "hash", "target": "file", "path": "a.bin"}),
    ("ENCRYPT FILE a.bin", {"action": "encrypt", "target": "file", "path": "a.bin"}),
    ("LIST FILES .", {"action": "list", "target": "files", "path": "."}),
    ("SEARCH FILE abc IN ./folder", {"action": "search", "target": "file", "path": "abc", "search_path": "./folder"}),
    ("SYSTEM INFO", {"action": "system_info"}),
    ("PROCESSES", {"action": "processes"}),
])
def test_legacy_shapes(source, expected):
    assert parse_command(source) == expected
    model = parse_validated_command(source)
    assert model.to_dispatch_dict() == expected
    assert json.loads(json.dumps(model.to_dict())) == {"schema_version": 1, **expected}


@pytest.mark.parametrize("path", [
    "a.bin", "/var/evidence.bin", "./samples/../case.bin", r"C:\Evidence\a.bin",
    r"C:\new\test" + "\\", "C:/Case/a.bin", r"\\server\share\file.bin", "नमूना.bin",
    "日本語/证据.bin", "file-[1]_(2);$x&@!.bin", "~/$HOME/*.bin", r"a\b.bin",
])
def test_unquoted_path_is_literal(path):
    assert parse_command("HASH FILE " + path)["path"] == path


@pytest.mark.parametrize("quote", ['"', "'"])
@pytest.mark.parametrize("path", [
    "a file.bin", r"C:\Case Files\new\test.bin", "C:/Case Files/नमूना.bin",
    "/case files/../case 1.bin", " leading and trailing ", "IN", r"\\host\share name" + "\\",
])
def test_quoted_paths(quote, path):
    assert parse_command(f"HASH FILE {quote}{path}{quote}")["path"] == path


@pytest.mark.parametrize(("source", "path"), [
    ('HASH FILE "O\'Brien.bin"', "O'Brien.bin"),
    ('HASH FILE \'a"b.bin\'', 'a"b.bin'),
])
def test_opposite_quote_is_literal(source, path):
    assert parse_command(source)["path"] == path


def test_search_both_arguments_quoted():
    assert parse_command('SEARCH FILE "invoice IN case" IN "C:\\Case Files\\"') == {
        "action": "search", "target": "file", "path": "invoice IN case", "search_path": "C:\\Case Files\\",
    }


@pytest.mark.parametrize("source", [
    "HASH", "HASH FILE", "HASH FILE x y", "ENCRYPT FILE", "LIST FILES", "SYSTEM",
    "SYSTEM INFO x", "PROCESSES x", "SEARCH FILE x", "SEARCH FILE x IN",
    "SEARCH FILE x IN y z", "DELETE FILE x", "hash FILE x", "HASHFILE x",
    "SYSTEMINFO", 'HASH FILE "unclosed', "HASH FILE 'unclosed", 'HASH FILE "x"junk',
    'HASH FILE "a""b"', "HASH FILE x\nPROCESSES", "HASH FILE x\x00", "PROCESSES\n",
])
def test_invalid_syntax(source):
    with pytest.raises(CommandSyntaxError) as caught:
        parse_command(source)
    assert caught.value.code == "invalid_syntax"
    assert caught.value.line >= 1 and caught.value.column >= 1


@pytest.mark.parametrize("source", [None, 12, {}, [], "", "  ", 'HASH FILE ""', "LIST FILES ''", 'HASH FILE "   "'])
def test_validation_errors(source):
    with pytest.raises(CommandValidationError):
        parse_command(source)


@pytest.mark.parametrize("source", ["  SYSTEM\tINFO  ", "SYSTEM  INFO", "\tSYSTEM INFO\t"])
def test_horizontal_whitespace(source):
    assert parse_command(source) == {"action": "system_info"}


@pytest.mark.parametrize("entry", LANGUAGE_REFERENCE, ids=lambda e: e["name"])
def test_documented_examples_parse(entry):
    assert parse_validated_command(entry["example"]).action


@pytest.mark.parametrize("kwargs", [
    {"action": "delete"}, {"action": "hash", "target": "file"},
    {"action": "system_info", "path": "x"}, {"action": "hash", "path": "x"},
    {"action": "search", "target": "file", "path": "x"},
    {"action": "processes", "search_path": "x"},
    {"action": "hash", "target": "file", "path": "a\tb"},
])
def test_domain_validation(kwargs):
    with pytest.raises(CommandError):
        Command(**kwargs)
