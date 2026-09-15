"""Turning uploads and links into something the model can read.

PDFs go to the API untouched as document blocks — Claude renders the pages, so
chart-heavy slides survive. Everything else (spreadsheets, PPTX, HTML) is
flattened to text here, because the API has no native reader for those.
"""

from __future__ import annotations

import base64
import csv
import io
import re
from pathlib import Path

import httpx

PDF_SUFFIXES = {".pdf"}
SLIDE_SUFFIXES = {".pptx"}
SHEET_SUFFIXES = {".xlsx", ".xlsm"}
CSV_SUFFIXES = {".csv", ".tsv"}
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rst"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# Keep a single spreadsheet from swallowing the whole prompt.
MAX_SHEET_ROWS = 400
MAX_SHEET_COLS = 40

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


class IngestError(Exception):
    """Raised when a file or URL cannot be read; the message is shown to the user."""


def clamp(text: str, limit: int) -> str:
    """Trim `text` to `limit` characters, saying so rather than truncating silently."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[... truncated at {limit:,} characters ...]"


def find_url(text: str) -> str | None:
    """Pull the first URL out of a message, tolerating a bare `acme.com`."""
    match = URL_RE.search(text)
    if match:
        return match.group(0).rstrip(".,);")
    bare = text.strip().split()[0] if text.strip() else ""
    if re.fullmatch(r"[\w-]+(\.[\w-]+)+(/\S*)?", bare) and "." in bare:
        return f"https://{bare}"
    return None


def classify(file_name: str) -> str | None:
    """Guess whether an upload is a deck or a financial model from its extension."""
    suffix = Path(file_name).suffix.lower()
    if suffix in PDF_SUFFIXES | SLIDE_SUFFIXES | IMAGE_SUFFIXES:
        return "pitch_deck"
    if suffix in SHEET_SUFFIXES | CSV_SUFFIXES:
        return "fin_model"
    if suffix in TEXT_SUFFIXES:
        return "notes"
    return None


def pdf_document_block(path: Path, title: str) -> dict:
    """A base64 PDF document block; Claude reads the rendered pages directly."""
    data = base64.standard_b64encode(Path(path).read_bytes()).decode("ascii")
    return {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": data},
        "title": title,
    }


def image_block(path: Path) -> dict:
    suffix = Path(path).suffix.lower()
    media_type = IMAGE_MEDIA_TYPES.get(suffix, "image/png")
    data = base64.standard_b64encode(Path(path).read_bytes()).decode("ascii")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data},
    }


def extract_pptx(path: Path) -> str:
    from pptx import Presentation

    prs = Presentation(str(path))
    out: list[str] = []
    for index, slide in enumerate(prs.slides, start=1):
        pieces: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                pieces.append(shape.text_frame.text.strip())
            if getattr(shape, "has_table", False):
                rows = [
                    " | ".join(cell.text.strip() for cell in row.cells)
                    for row in shape.table.rows
                ]
                pieces.append("\n".join(rows))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            pieces.append(f"[speaker notes] {slide.notes_slide.notes_text_frame.text.strip()}")
        out.append(f"--- Slide {index} ---\n" + "\n".join(pieces))
    return "\n\n".join(out)


def extract_spreadsheet(path: Path) -> str:
    """Render each sheet as a pipe-separated grid, formulas included.

    Two passes per sheet: the computed values (what the founder's numbers say)
    and the formulas (how they got there), since a model built on hardcoded
    hockey sticks reads very differently from one with real drivers.
    """
    from openpyxl import load_workbook

    def grid(workbook, note: str) -> list[str]:
        chunks: list[str] = []
        for sheet in workbook.worksheets:
            if sheet.sheet_state != "visible":
                continue
            rows: list[str] = []
            for row in sheet.iter_rows(max_row=MAX_SHEET_ROWS, max_col=MAX_SHEET_COLS):
                cells = ["" if c.value is None else str(c.value) for c in row]
                while cells and not cells[-1]:
                    cells.pop()
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                chunks.append(f"--- Sheet: {sheet.title} ({note}) ---\n" + "\n".join(rows))
        return chunks

    values_wb = load_workbook(str(path), data_only=True, read_only=True)
    parts = grid(values_wb, "computed values")
    values_wb.close()

    formulas_wb = load_workbook(str(path), data_only=False, read_only=True)
    parts += grid(formulas_wb, "formulas")
    formulas_wb.close()

    return "\n\n".join(parts)


def extract_csv(path: Path) -> str:
    raw = Path(path).read_text("utf-8", errors="replace")
    delimiter = "\t" if Path(path).suffix.lower() == ".tsv" else ","
    reader = csv.reader(io.StringIO(raw), delimiter=delimiter)
    rows = [" | ".join(row) for _, row in zip(range(MAX_SHEET_ROWS), reader)]
    return "\n".join(rows)


def extract_file(path: Path) -> str:
    """Flatten a non-PDF upload to text."""
    suffix = Path(path).suffix.lower()
    try:
        if suffix in SLIDE_SUFFIXES:
            return extract_pptx(path)
        if suffix in SHEET_SUFFIXES:
            return extract_spreadsheet(path)
        if suffix in CSV_SUFFIXES:
            return extract_csv(path)
        if suffix in TEXT_SUFFIXES:
            return Path(path).read_text("utf-8", errors="replace")
    except IngestError:
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced to the user as a chat message
        raise IngestError(f"could not read {Path(path).name}: {exc}") from exc
    raise IngestError(f"unsupported file type: {suffix or path.name}")


def html_to_text(html: str) -> str:
    """Strip a page down to readable copy, keeping headings as structure."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else ""
    description = ""
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find(
        "meta", attrs={"property": "og:description"}
    )
    if meta and meta.get("content"):
        description = meta["content"].strip()

    body = soup.get_text("\n", strip=True)
    body = re.sub(r"\n{3,}", "\n\n", body)

    header = "\n".join(p for p in (f"Title: {title}" if title else "",
                                   f"Description: {description}" if description else "") if p)
    return f"{header}\n\n{body}".strip()


def fetch_website(url: str, timeout: float = 25.0) -> str:
    """Fetch a URL and return its readable text."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; VCAnalystBot/0.1; +https://example.invalid/bot)"
    }
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise IngestError(
            f"{url} returned HTTP {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        raise IngestError(f"could not reach {url}: {exc}") from exc

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type and "text" not in content_type:
        raise IngestError(f"{url} is not a web page (content-type: {content_type or 'unknown'})")

    text = html_to_text(response.text)
    if not text.strip():
        raise IngestError(
            f"{url} rendered no readable text — it may be a JavaScript-only site. "
            "Paste the key copy under 'Additional info' instead."
        )
    return text
