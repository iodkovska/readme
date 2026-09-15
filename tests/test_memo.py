from vcbot.memo import TELEGRAM_LIMIT, chunk, filename_for, render_chat, render_markdown
from tests.test_scoring import make_memo


def test_markdown_contains_the_essentials():
    out = render_markdown(make_memo(team=9))
    assert "Acme Robotics" in out
    assert "TRACK" in out
    assert "| Team |" in out
    assert "single customer" in out
    assert "What is net revenue retention?" in out


def test_chat_render_fits_one_telegram_message():
    assert len(render_chat(make_memo())) <= TELEGRAM_LIMIT


def test_chunk_respects_the_limit():
    text = "\n\n".join(f"Paragraph {i} " + "x" * 300 for i in range(60))
    parts = chunk(text)
    assert len(parts) > 1
    assert all(len(p) <= TELEGRAM_LIMIT for p in parts)
    assert "".join(p.replace("\n", "") for p in parts).count("x") == text.count("x")


def test_chunk_leaves_short_text_alone():
    assert chunk("short") == ["short"]


def test_chunk_handles_a_single_unbroken_run():
    parts = chunk("y" * (TELEGRAM_LIMIT * 2 + 5))
    assert all(len(p) <= TELEGRAM_LIMIT for p in parts)


def test_filename_is_filesystem_safe():
    memo = make_memo()
    memo.company_name = "Acme / Robotics: Inc."
    name = filename_for(memo)
    assert "/" not in name and ":" not in name
    assert name.endswith(".md")
