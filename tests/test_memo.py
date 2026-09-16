from vcbot.memo import TELEGRAM_LIMIT, chunk, render_chat, score_bar
from tests.test_scoring import make_memo


def test_chat_render_carries_the_headline_numbers():
    out = render_chat(make_memo(market=3, product=3))
    assert "Vektor Robotics" in out
    assert "SCORING: 22/30" in out
    assert "TRACK" in out
    assert "Market" in out and "Tech" in out


def test_chat_render_shows_pros_and_cons():
    out = render_chat(make_memo())
    assert "Traction: ARR grew 4.5x in twelve months" in out
    assert "Traction: 71% of ARR is one customer" in out


def test_chat_render_fits_one_telegram_message():
    assert len(render_chat(make_memo())) <= TELEGRAM_LIMIT


def test_score_bar_is_three_wide():
    assert score_bar(3) == "\u2588\u2588\u2588"
    assert score_bar(0) == "\u2591\u2591\u2591"
    assert len(score_bar(2)) == 3


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
