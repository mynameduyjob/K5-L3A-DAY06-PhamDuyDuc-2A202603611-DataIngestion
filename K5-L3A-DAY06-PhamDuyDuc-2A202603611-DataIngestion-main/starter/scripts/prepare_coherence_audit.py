"""Create a fixed, same-source-position chunk-coherence review sheet."""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.chunking import by_paragraph, fixed_size
from src.run import _load_corpus

OUTPUT = ROOT / "results" / "coherence_audit_current.csv"


def main():
    _, pages = _load_corpus(ROOT / "manifest.json")
    chunks = {
        "A": [chunk for page in pages for chunk in fixed_size(page, size=500, overlap=50)],
        "B": [chunk for page in pages for chunk in by_paragraph(page, max_size=1000)],
    }
    chunks["C"] = chunks["B"]
    # Choose one location per fifth source unit, starting with unit/page 2,
    # before inspecting chunk boundaries or any retrieval scores.
    sample_pages = list(range(2, len(pages) + 1, 5))[:10]
    rows = []
    for page_number in sample_pages:
        page = next(page for page in pages if page.page == page_number)
        anchor = len(page.text) // 2
        for strategy in ("A", "B", "C"):
            covering = [chunk for chunk in chunks[strategy]
                        if chunk.page == page.page
                        and chunk.metadata["char_start"] <= anchor < chunk.metadata["char_end"]]
            if not covering:
                raise RuntimeError(f"No {strategy} chunk covers sample anchor {page.page}@{anchor}")
            chunk = covering[0]
            rows.append({
                "sample_rule": "page/unit 2,7,12,...,47; local midpoint; first chunk covering anchor",
                "unit_id": page.metadata["unit_id"],
                "chapter": page.metadata["chapter"],
                "source_page_or_unit": page.page,
                "anchor_char_in_unit": anchor,
                "strategy": strategy,
                "chunk_id": chunk.chunk_id,
                "chunk_start_char": chunk.metadata["char_start"],
                "chunk_end_char": chunk.metadata["char_end"],
                "chunk_text": chunk.text,
                "coherence_score_0_2": "",
                "reason": "",
                "reviewer": "",
                "status": "pending_reviewer",
            })
    OUTPUT.parent.mkdir(exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {OUTPUT.name}: {len(rows)} rows; 10 fixed source positions x 3 strategies")


if __name__ == "__main__":
    main()
