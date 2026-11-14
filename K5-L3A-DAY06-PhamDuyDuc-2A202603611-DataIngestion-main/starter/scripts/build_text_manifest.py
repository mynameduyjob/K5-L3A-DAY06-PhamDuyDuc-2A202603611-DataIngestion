"""Create a reproducible manifest for the first twelve Huckleberry Finn chapters."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.ingestion import normalize_text

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "huck_finn_pg76.txt"
MANIFEST_PATH = ROOT / "manifest.json"
TARGET_CHARS = 3000
CHAPTERS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]


def chapter_spans(text: str):
    author_note = text.index("THE AUTHOR.")
    pattern = re.compile(r"(?m)^CHAPTER (THE LAST|[IVXLCDM]+)\.?$")
    matches = [m for m in pattern.finditer(text, author_note) if m.group(1) in CHAPTERS or m.group(1) == "XIII"]
    actual = []
    for match in matches:
        if match.group(1) not in [chapter for _, chapter in actual]:
            actual.append((match.start(), match.group(1)))
    positions = {chapter: position for position, chapter in actual}
    if any(chapter not in positions for chapter in CHAPTERS + ["XIII"]):
        raise ValueError("Could not locate the complete chapter I-XIII boundaries in source text")
    return [(chapter, positions[chapter], positions["XIII"] if index == len(CHAPTERS) - 1 else positions[CHAPTERS[index + 1]])
            for index, chapter in enumerate(CHAPTERS)]


def split_chapter(text: str, chapter: str, page_start: int):
    paragraph_spans = [(m.start(), m.end()) for m in re.finditer(r"\S.*?(?=\n\n|$)", text, flags=re.S)]
    groups = []
    group_start = group_end = None
    for start, end in paragraph_spans:
        if group_start is not None and end - group_start > TARGET_CHARS and group_end - group_start >= 1500:
            groups.append((group_start, group_end))
            group_start = group_end = None
        if group_start is None:
            group_start = start
        group_end = end
    if group_start is not None:
        if group_end - group_start < 1500:
            if not groups:
                raise ValueError(f"Chapter {chapter}: unable to make a 1,500-character unit")
            previous_start, _ = groups.pop()
            groups.append((previous_start, group_end))
        else:
            groups.append((group_start, group_end))

    units = []
    for offset, (start, end) in enumerate(groups, start=1):
        absolute_start, absolute_end = page_start + start, page_start + end
        units.append({
            "unit_id": f"chapter-{int(chapter, 10) if chapter.isdigit() else roman_number(chapter):02d}-unit-{offset:02d}",
            "page": 0,
            "chapter": chapter,
            "start_char": absolute_start,
            "end_char": absolute_end,
            "char_count": end - start,
        })
    return units


def roman_number(value: str) -> int:
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    total, previous = 0, 0
    for char in reversed(value):
        current = values[char]
        total += -current if current < previous else current
        previous = max(previous, current)
    return total


def main():
    text = normalize_text(DATA_PATH.read_text(encoding="utf-8-sig"))
    units = []
    for chapter, start, end in chapter_spans(text):
        units.extend(split_chapter(text[start:end], chapter, start))
    for page, unit in enumerate(units, start=1):
        unit["page"] = page
    if len(units) < 30:
        raise ValueError(f"Expected at least 30 source units; generated {len(units)}")

    manifest = {
        "sources": [{
            "source_id": "huck_finn_early_journey",
            "title": "Adventures of Huckleberry Finn — Chapters I–XII",
            "path": "data/huck_finn_pg76.txt",
            "source_path_or_url": "https://www.gutenberg.org/ebooks/76",
            "license_or_permission": (
                "Project Gutenberg eBook #76; the source states public domain in the USA and includes its full license. "
                "Mark Twain died in 1910; this noncommercial educational corpus is used as a public-domain literary work. "
                "The original source file and its Project Gutenberg notice/license are retained in this repository."
            ),
            "accessed_at": "2026-11-14",
            "snapshot_or_version": "Project Gutenberg plain-text eBook #76; header says last updated 2026-05-17.",
            "physical_pages": None,
            "unit_rule": (
                "No page numbering in the plain-text source. Use chapters I-XII, split at paragraph boundaries into "
                "ordered units near 3,000 normalized characters; merge a final remainder under 1,500 characters "
                "into the preceding unit in the same chapter. Character offsets are Python Unicode code-point offsets "
                "in the full NFC-normalized source file. Units are not duplicated."
            ),
            "metadata": {"author": "Mark Twain", "language": "en", "work_type": "novel"},
            "included_units": units,
        }]
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {MANIFEST_PATH.name}: {len(units)} units, {sum(unit['char_count'] for unit in units):,} normalized characters")


if __name__ == "__main__":
    main()
