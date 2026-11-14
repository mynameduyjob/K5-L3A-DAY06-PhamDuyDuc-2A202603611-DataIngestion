"""Fixed-window and paragraph-aware chunking with stable traceable IDs."""
import hashlib

from .models import Chunk, DocumentPage


def _make_chunk(page: DocumentPage, start: int, end: int, text: str) -> Chunk:
    identity = f"{page.document_id}:{page.page}:{start}:{end}:{text}"
    chunk_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    metadata = dict(page.metadata)
    metadata.update({"char_start": start, "char_end": end})
    return Chunk(chunk_id, page.document_id, page.source, page.page, text, metadata)


def fixed_size(page: DocumentPage, size: int = 500, overlap: int = 50) -> list[Chunk]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("Require size > 0 and 0 <= overlap < size")
    text = page.text.strip()
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        left, right = start, end
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        if left < right:
            chunks.append(_make_chunk(page, left, right, text[left:right]))
        if end == len(text):
            break
        start = end - overlap
    return chunks


def by_paragraph(page: DocumentPage, max_size: int = 1000) -> list[Chunk]:
    if max_size <= 0:
        raise ValueError("max_size must be positive")
    text = page.text.strip()
    chunks = []
    group_start = None
    group_end = None

    def flush():
        nonlocal group_start, group_end
        if group_start is not None:
            chunks.append(_make_chunk(page, group_start, group_end, text[group_start:group_end]))
        group_start, group_end = None, None

    cursor = 0
    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            cursor += 2
            continue
        para_start = text.find(paragraph, cursor)
        if para_start < 0:
            para_start = cursor
        para_end = para_start + len(paragraph)
        cursor = para_end + 2

        if len(paragraph) > max_size:
            flush()
            for start in range(para_start, para_end, max_size):
                end = min(start + max_size, para_end)
                chunks.append(_make_chunk(page, start, end, text[start:end]))
            continue

        if group_start is not None and para_end - group_start > max_size:
            flush()
        if group_start is None:
            group_start = para_start
        group_end = para_end
    flush()
    return chunks
