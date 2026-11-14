"""Load PDF pages listed in a user-authored manifest."""
import unicodedata
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .models import DocumentPage


def normalize_text(text: str) -> str:
    """Normalize Unicode and whitespace while preserving paragraph breaks."""
    text = unicodedata.normalize("NFC", text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    paragraphs = []
    for line in lines:
        if line:
            paragraphs.append(line)
        elif paragraphs and paragraphs[-1] != "":
            paragraphs.append("")
    return "\n".join(paragraphs).strip()


def load_pdf(path: Path, document_id: str, source: str,
             included_pages: list[int] | None = None,
             metadata: dict | None = None) -> list[DocumentPage]:
    """Extract physical PDF pages; page numbers are one-based."""
    reader = PdfReader(str(path))
    selected = set(included_pages) if included_pages is not None else None
    pages = []
    for page_number, pdf_page in enumerate(reader.pages, start=1):
        if selected is not None and page_number not in selected:
            continue
        text = normalize_text(pdf_page.extract_text() or "")
        page_metadata = dict(metadata or {})
        page_metadata["extraction_status"] = "ok" if text else "empty_or_scanned"
        page_metadata["location_type"] = "physical_page"
        pages.append(DocumentPage(document_id, source, page_number, text, page_metadata))
    unknown = selected - {page.page for page in pages} if selected is not None else set()
    if unknown:
        raise ValueError(f"{path}: manifest page numbers out of range: {sorted(unknown)}")
    return pages


def load_text_units(path: Path, document_id: str, source: str,
                    units: list[dict[str, Any]], metadata: dict | None = None) -> list[DocumentPage]:
    """Load selected character ranges from a UTF-8 text source.

    Manifest offsets and character counts refer to this normalized full text.
    Each unit retains its stable ID and source-specific metadata.
    """
    text = normalize_text(path.read_text(encoding="utf-8-sig"))
    pages = []
    seen = set()
    for unit in units:
        required = ("unit_id", "page", "chapter", "start_char", "end_char", "char_count")
        missing = [key for key in required if key not in unit]
        if missing:
            raise ValueError(f"Text unit is missing fields: {', '.join(missing)}")
        unit_id = unit["unit_id"]
        if unit_id in seen:
            raise ValueError(f"Duplicate text unit ID: {unit_id}")
        seen.add(unit_id)
        start, end = unit["start_char"], unit["end_char"]
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start or end > len(text):
            raise ValueError(f"Invalid character boundaries for text unit {unit_id}")
        value = text[start:end]
        if len(value) != unit["char_count"]:
            raise ValueError(f"Character count mismatch for text unit {unit_id}: expected {unit['char_count']}, got {len(value)}")
        if len(value) < 1500:
            raise ValueError(f"Text unit {unit_id} has {len(value)} characters; minimum is 1500")
        unit_metadata = dict(metadata or {})
        unit_metadata.update({
            "unit_id": unit_id,
            "chapter": unit["chapter"],
            "char_start": start,
            "char_end": end,
            "char_count": len(value),
            "extraction_status": "ok",
            "location_type": "text_unit",
        })
        pages.append(DocumentPage(document_id, source, unit["page"], value, unit_metadata))
    if len(pages) < 30:
        raise ValueError(f"Need at least 30 useful text units; found {len(pages)}")
    return pages
