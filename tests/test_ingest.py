import csv

import pytest

from vcbot import ingest


def test_find_url_variants():
    assert ingest.find_url("check https://acme.com/about out") == "https://acme.com/about"
    assert ingest.find_url("acme.com") == "https://acme.com"
    assert ingest.find_url("see http://a.io.") == "http://a.io"
    assert ingest.find_url("no link here") is None


def test_classify_by_extension():
    assert ingest.classify("deck.pdf") == "pitch_deck"
    assert ingest.classify("Deck.PPTX") == "pitch_deck"
    assert ingest.classify("slide.png") == "pitch_deck"
    assert ingest.classify("model.xlsx") == "fin_model"
    assert ingest.classify("actuals.csv") == "fin_model"
    assert ingest.classify("notes.txt") == "notes"
    assert ingest.classify("archive.zip") is None


def test_clamp_flags_truncation():
    assert ingest.clamp("abc", 10) == "abc"
    out = ingest.clamp("x" * 50, 10)
    assert out.startswith("x" * 10)
    assert "truncated" in out


def test_extract_csv(tmp_path):
    path = tmp_path / "m.csv"
    with path.open("w", newline="") as fh:
        csv.writer(fh).writerows([["month", "mrr"], ["Jan", "1000"], ["Feb", "1400"]])
    out = ingest.extract_file(path)
    assert "month | mrr" in out
    assert "Feb | 1400" in out


def test_extract_spreadsheet_includes_values_and_formulas(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "model.xlsx"
    wb = Workbook()
    sheet = wb.active
    sheet.title = "P&L"
    sheet["A1"], sheet["B1"] = "revenue", 1000
    sheet["A2"], sheet["B2"] = "growth", "=B1*1.2"
    wb.save(path)

    out = ingest.extract_file(path)
    assert "Sheet: P&L (computed values)" in out
    assert "Sheet: P&L (formulas)" in out
    assert "=B1*1.2" in out


def test_unsupported_file_raises(tmp_path):
    path = tmp_path / "thing.zip"
    path.write_bytes(b"PK\x03\x04")
    with pytest.raises(ingest.IngestError):
        ingest.extract_file(path)


def test_html_to_text_strips_scripts_and_keeps_meta():
    html = """
    <html><head><title>Acme</title>
    <meta name="description" content="Robots for warehouses">
    <style>body{color:red}</style></head>
    <body><script>alert(1)</script><h1>We build arms</h1><p>Seed stage.</p></body></html>
    """
    out = ingest.html_to_text(html)
    assert "Title: Acme" in out
    assert "Robots for warehouses" in out
    assert "We build arms" in out
    assert "alert(1)" not in out
    assert "color:red" not in out


def test_pdf_block_shape(tmp_path):
    path = tmp_path / "deck.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    block = ingest.pdf_document_block(path, "Pitch deck: deck.pdf")
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf"
    assert "\n" not in block["source"]["data"]
