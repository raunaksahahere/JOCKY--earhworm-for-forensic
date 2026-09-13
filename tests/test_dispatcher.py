import pytest

from communication import dispatcher
from compiler.parser import parse_command


@pytest.mark.parametrize(("source", "function", "args"), [
    ('HASH FILE "a b"', "hash_file", ("a b",)),
    ('ENCRYPT FILE "a b"', "encrypt_file", ("a b",)),
    ("SYSTEM INFO", "get_system_info", ()),
    ("PROCESSES", "list_processes", ()),
    ('LIST FILES "a b"', "list_files", ("a b",)),
    ('SEARCH FILE "a b" IN "c d"', "search_file", ("a b", "c d")),
])
def test_all_routes(source, function, args, monkeypatch):
    calls = []
    def collect(*values):
        calls.append(values)
        return {"status": "success"}
    monkeypatch.setattr(dispatcher, function, collect)
    assert dispatcher.execute_command(parse_command(source)) == {"status": "success"}
    assert calls == [args]


def test_unknown_dispatch_action():
    with pytest.raises(ValueError, match="Unsupported action"):
        dispatcher.execute_command({"action": "unknown"})


def test_real_files_pipeline(evidence):
    listed = dispatcher.execute_command(parse_command(f'LIST FILES "{evidence.parent}"'))
    assert evidence.name in [e["name"] for e in listed["entries"]]
    found = dispatcher.execute_command(parse_command(f'SEARCH FILE "नमूना" IN "{evidence.parent}"'))
    assert found["results"][0]["path"] == str(evidence)
