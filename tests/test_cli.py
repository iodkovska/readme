"""The command-line runner: argument handling, and that it never tracebacks."""

from types import SimpleNamespace

import pytest

from vcbot import cli
from vcbot.analyst import AnalysisResult
from tests.test_scoring import make_memo


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "cli-unused")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")


@pytest.fixture
def files(tmp_path):
    deck = tmp_path / "deck.pdf"
    deck.write_bytes(b"%PDF-1.4 x")
    model = tmp_path / "model.xlsx"
    model.write_bytes(b"x")
    return SimpleNamespace(deck=str(deck), model=str(model), dir=tmp_path)


def stub_analyst(monkeypatch, result=None, error=None):
    """Replace Analyst so the CLI runs without touching the API."""
    seen = {}

    class FakeAnalyst:
        def __init__(self, cfg):
            seen["cfg"] = cfg

        def score(self, deal):
            seen["deal"] = deal
            if error:
                raise error
            return result

    monkeypatch.setattr(cli, "Analyst", FakeAnalyst)
    return seen


def test_builds_a_deal_from_every_input(files, tmp_path):
    note_file = tmp_path / "notes.txt"
    note_file.write_text("from the call")
    args = cli.parse_args(
        [
            "--deck", files.deck,
            "--model", files.model,
            "--url", "https://acme.com",
            "--note", "an angel intro",
            "--note-file", str(note_file),
            "--company", "Acme",
        ]
    )
    deal = cli.build_deal(args)
    assert [a.file_name for a in deal.decks] == ["deck.pdf"]
    assert [a.file_name for a in deal.models] == ["model.xlsx"]
    assert deal.websites == ["https://acme.com"]
    assert deal.notes == ["an angel intro", "from the call"]
    assert deal.company == "Acme"


def test_repeatable_flags_accumulate(files):
    args = cli.parse_args(["--deck", files.deck, "--deck", files.deck])
    assert len(cli.build_deal(args).decks) == 2


def test_missing_file_is_reported_not_traced(tmp_path):
    args = cli.parse_args(["--deck", str(tmp_path / "nope.pdf")])
    with pytest.raises(SystemExit, match="No such file"):
        cli.build_deal(args)


def test_no_material_exits_with_guidance():
    with pytest.raises(SystemExit, match="Nothing to score"):
        cli.main([])


def test_writes_the_docx_and_prints_the_path(monkeypatch, files, capsys, tmp_path):
    stub_analyst(
        monkeypatch,
        AnalysisResult(memo=make_memo(), warnings=[], research=None, sources=[]),
    )
    out = tmp_path / "memo.docx"
    assert cli.main(["--deck", files.deck, "--out", str(out)]) == 0
    assert out.exists() and out.stat().st_size > 0
    printed = capsys.readouterr().out
    assert str(out) in printed
    assert "Vektor Robotics" in printed


def test_quiet_prints_only_the_path(monkeypatch, files, capsys, tmp_path):
    stub_analyst(
        monkeypatch, AnalysisResult(memo=make_memo(), warnings=[], research=None, sources=[])
    )
    out = tmp_path / "memo.docx"
    cli.main(["--deck", files.deck, "--out", str(out), "--quiet"])
    assert capsys.readouterr().out.strip() == str(out)


def test_no_research_flag_disables_the_pass(monkeypatch, files, tmp_path):
    seen = stub_analyst(
        monkeypatch, AnalysisResult(memo=make_memo(), warnings=[], research=None, sources=[])
    )
    cli.main(["--deck", files.deck, "--out", str(tmp_path / "m.docx"), "--no-research"])
    assert seen["cfg"].enable_web_research is False


def test_research_is_on_by_default(monkeypatch, files, tmp_path):
    seen = stub_analyst(
        monkeypatch, AnalysisResult(memo=make_memo(), warnings=[], research=None, sources=[])
    )
    cli.main(["--deck", files.deck, "--out", str(tmp_path / "m.docx")])
    assert seen["cfg"].enable_web_research is True


def test_warnings_go_to_stderr(monkeypatch, files, capsys, tmp_path):
    stub_analyst(
        monkeypatch,
        AnalysisResult(memo=make_memo(), warnings=["could not reach the site"], research=None, sources=[]),
    )
    cli.main(["--deck", files.deck, "--out", str(tmp_path / "m.docx")])
    assert "could not reach the site" in capsys.readouterr().err


def test_api_failure_exits_nonzero_with_a_readable_message(monkeypatch, files, capsys, tmp_path):
    import httpx
    import anthropic

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    exc = anthropic.BadRequestError(
        message="Your credit balance is too low",
        response=httpx.Response(400, request=request),
        body=None,
    )
    stub_analyst(monkeypatch, error=exc)
    assert cli.main(["--deck", files.deck, "--out", str(tmp_path / "m.docx")]) == 1
    err = capsys.readouterr().err
    assert "out of credit" in err
    assert "Traceback" not in err


def test_default_output_name_comes_from_the_memo(monkeypatch, files, tmp_path):
    stub_analyst(
        monkeypatch, AnalysisResult(memo=make_memo(), warnings=[], research=None, sources=[])
    )
    monkeypatch.chdir(tmp_path)
    cli.main(["--deck", files.deck, "--quiet"])
    written = list(tmp_path.glob("Vektor_Robotics_scoring_memo_*.docx"))
    assert len(written) == 1
