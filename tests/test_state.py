from vcbot.state import Attachment, Deal, DealStore


def test_roundtrip(tmp_path):
    store = DealStore(tmp_path)
    deal = store.load(42)
    assert not deal.has_material()

    deal.company = "Acme"
    deal.decks.append(
        Attachment(kind="pitch_deck", file_name="d.pdf", path="/tmp/d.pdf", mime="application/pdf", size=10)
    )
    deal.websites.append("https://acme.com")
    deal.notes.append("met at a conference")
    deal.awaiting = "fin_model"
    store.save(deal)

    loaded = store.load(42)
    assert loaded.company == "Acme"
    assert loaded.decks[0].file_name == "d.pdf"
    assert loaded.websites == ["https://acme.com"]
    assert loaded.awaiting == "fin_model"
    assert loaded.has_material()


def test_reset_clears(tmp_path):
    store = DealStore(tmp_path)
    deal = store.load(7)
    deal.notes.append("x")
    store.save(deal)
    assert store.load(7).has_material()
    store.reset(7)
    assert not store.load(7).has_material()


def test_corrupt_file_does_not_crash(tmp_path):
    store = DealStore(tmp_path)
    (tmp_path / "9.json").write_text("{not json", "utf-8")
    recovered = store.load(9)
    assert recovered.chat_id == 9
    assert not recovered.has_material()
    assert recovered.awaiting is None


def test_summary_lines_mark_progress(tmp_path):
    deal = Deal(chat_id=1)
    assert all(line.startswith("⬜") for line in deal.summary_lines())
    deal.websites.append("https://acme.com")
    lines = deal.summary_lines()
    assert any(line.startswith("✅") and "Website" in line for line in lines)
