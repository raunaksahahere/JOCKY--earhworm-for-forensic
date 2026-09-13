import pytest

from analysis.indicators import evaluate_filename


@pytest.mark.parametrize(("name", "count"), [
    ("notes.txt", 0), ("sample.exe", 1), ("SAMPLE.EXE", 1), ("invoice.pdf.exe", 2),
    (".config", 1), ("", 0), (".", 0), ("archive.exe.txt", 0),
    ("photo.jpg.backup", 0), ("report.pdf.exe.txt", 0), ("नमूना.txt", 0),
])
def test_filename_heuristics(name, count):
    indicators = evaluate_filename(name)
    assert len(indicators) == count
    assert all(i["level"] in {"info", "warning"} and i["detail"] for i in indicators)


def test_double_extension_advisory():
    flags = evaluate_filename("invoice.pdf.exe")
    assert any(flag["label"] == "Possible extension spoofing" for flag in flags)
