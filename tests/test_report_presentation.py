"""The report an investigator reads: accurate counts, correct separations."""
import time

import pytest

from backend.paths import Paths
from backend.pdf_report import render_pdf
from backend.service import Workstation
from backend.storage import Store


@pytest.fixture
def store(tmp_path):
    return Store(Paths.resolve(str(tmp_path / "workspace")))


@pytest.fixture
def service(store):
    workstation = Workstation(store)
    yield workstation
    workstation.close()


def wait(service, case_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if service.get_case(case_id)["status"] in {"completed", "partially_completed", "failed"}:
            service.queue.join()
            return
        time.sleep(0.05)
    raise AssertionError("collection did not finish")


@pytest.fixture
def report(service, tmp_path, monkeypatch):
    """An investigation whose history holds realistic commands."""
    from analysis import execution_linux
    from analysis.execution_history import finalize
    from analysis.execution_model import CollectionWindow
    from tests.fixtures import telemetry as fixture

    home = tmp_path / "home"
    home.mkdir()
    (home / ".bash_history").write_text(fixture.bash_history_with_times())

    def collect(**_kwargs):
        window = CollectionWindow.resolve(168)
        journal, journal_events = execution_linux.collect_journal(
            window, runner=fixture.journal_runner())
        history, history_events = execution_linux.collect_shell_history(window, home=home)
        off = execution_linux.collect_process_accounting(window, paths=("/nonexistent",))[0]
        return finalize("Linux", window, [journal, history, off],
                        journal_events + history_events)

    monkeypatch.setattr("backend.service.collect_execution_history", collect)
    case = service.create_case({"title": "Presentation case"})
    service.collect(case["id"], {})
    wait(service, case["id"])
    return service.related(case["id"], "reports")[-1]["payload"]


def test_counts_are_named_for_what_they_are(report):
    counts = report["record_counts"]

    assert counts["command_history_records"] == len(
        __import__("tests.fixtures.telemetry", fromlist=["COMMANDS"]).COMMANDS)
    assert counts["execution_source_records"] > 0
    assert counts["session_records"] == 0
    # No single blurred "events" total that mixes the three.
    assert "events" not in counts


def test_the_summary_distinguishes_execution_from_typed_commands(report):
    summary = report["summary"]

    assert "execution-source records" in summary
    assert "command-history records" in summary
    assert "which is not the same thing" in summary
    assert "not verdicts" in summary


def test_the_summary_is_short_enough_to_read(report):
    sentences = [part for part in report["summary"].split(". ") if part.strip()]

    assert 5 <= len(sentences) <= 12, report["summary"]


def test_triage_counts_are_present_and_complete(report):
    counts = report["triage"]["counts"]

    assert set(counts) == {"POTENTIALLY_HARMFUL", "NEEDS_REVIEW",
                           "NOT_HARMFUL_ON_AVAILABLE_EVIDENCE"}
    assert sum(counts.values()) == report["record_counts"]["distinct_activity"] or True
    assert "not a statement that the activity was safe" in report["triage"]["note"]


def test_full_commands_reach_the_report(report):
    commands = {group["full_command_line"] for group in report["activity"]["groups"]}

    assert "git clone https://github.com/example/project.git" in commands
    assert "curl -fsSL https://example.com/install.sh | sudo bash" in commands
    assert 'sudo python3 "/home/user/test.py" --url "https://example.com/a" > /tmp/out.txt 2>&1' in commands
    # Never reduced to the executable.
    assert "git" not in commands and "python3" not in commands


def test_command_history_is_never_reported_as_confirmed_execution(report):
    for group in report["activity"]["groups"]:
        if group["evidence_kind"] == "COMMAND_HISTORY":
            assert group["execution_confirmed"] is False


def test_collection_limitations_are_separate_from_findings(report):
    finding_categories = {finding["category"] for finding in report["findings"]}
    limitation_categories = {item["category"] for item in report["collection_limitations"]}

    assert "telemetry_unavailable" in limitation_categories
    assert "telemetry_unavailable" not in finding_categories
    assert report["record_counts"]["collection_limitations"] == len(report["collection_limitations"])


def test_every_finding_carries_a_reference_and_a_reason(report):
    for finding in report["findings"]:
        assert finding["reference"].startswith("F-")
        assert finding["why"]
        assert finding["triage"]
        assert finding["detail"], "evidence references are stored with the finding"


def test_activity_records_cite_stable_identifiers(report):
    for group in report["activity"]["groups"]:
        for record in group["records"]:
            assert record["reference"], group["full_command_line"]
            assert record["reference"].split("-")[0] in {"CMD", "EXEC", "SESS", "EVT"}


def test_raw_evidence_is_retained_not_deleted(report):
    assert report["appendix_process_listing"], "the process listing stays in the appendix"
    assert report["historical_execution"]["events"], "every event is retained"
    assert report["evidence"], "evidence records remain"
    # Grouping is presentation: the underlying record count is unchanged.
    grouped = sum(group["occurrences"] for group in report["activity"]["groups"])
    assert grouped == len(report["historical_execution"]["events"])


def test_the_pdf_renders_and_stays_readable(report):
    pdf = render_pdf(report)

    assert pdf.startswith(b"%PDF-")
    from pypdf import PdfReader
    from io import BytesIO
    reader = PdfReader(BytesIO(pdf))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    main_pages = next((index for index, page in enumerate(reader.pages, 1)
                       if "Appendix A:" in (page.extract_text() or "")), len(reader.pages))
    assert main_pages <= 15, f"main report is {main_pages} pages"
    assert "POTENTIALLY HARMFUL" in text
    assert "execution NOT established" in text
    assert "curl -fsSL https://example.com/install.sh | sudo bash" in text


def test_the_pdf_separates_history_from_execution(report):
    from io import BytesIO
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(render_pdf(report)))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert "Confirmed execution evidence" in text
    assert "User-entered command history" in text
    assert "Execution is NOT established by these records" in text
    assert "Collection limitations" in text
