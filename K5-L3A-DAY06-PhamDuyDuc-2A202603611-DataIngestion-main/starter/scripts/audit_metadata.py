"""Cross-check test top-3 metadata against the manifest and source units."""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.run import _load_corpus

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest, pages = _load_corpus(ROOT / "manifest.json")
    summary = json.loads((ROOT / "results" / "summary.json").read_text(encoding="utf-8"))
    question_path = (ROOT / summary["question_file"]).resolve()
    questions = json.loads(question_path.read_text(encoding="utf-8"))
    trace_path = (ROOT / summary.get("trace_file", "results/traces.json")).resolve()
    traces = json.loads(trace_path.read_text(encoding="utf-8"))
    source = manifest["sources"][0]
    by_location = {(page.document_id, page.page): page for page in pages}
    questions_by_id = {question["id"]: question for question in questions}
    rows = []

    for trace in traces:
        if trace["split"] != "test":
            continue
        question = questions_by_id[trace["question_id"]]
        for rank, hit in enumerate(trace["hits"], start=1):
            unit = by_location.get((hit["document_id"], hit["page"]))
            metadata = hit["metadata"]
            start, end = metadata.get("char_start"), metadata.get("char_end")
            text_matches = bool(unit and isinstance(start, int) and isinstance(end, int)
                                and 0 <= start < end <= len(unit.text)
                                and hit["text"] == unit.text[start:end])
            required_fields = ("unit_id", "chapter", "char_start", "char_end", "char_count", "extraction_status")
            complete = all(key in metadata for key in required_fields)
            matches_source = bool(
                unit
                and hit["document_id"] == source["source_id"]
                and hit["source"] == source["title"]
                and str(hit["page"]) == str(unit.page)
                and metadata.get("unit_id") == unit.metadata.get("unit_id")
                and metadata.get("chapter") == unit.metadata.get("chapter")
                and metadata.get("char_count") == len(unit.text)
                and metadata.get("location_type") == "text_unit"
            )
            filter_values = question.get("filter") or {}
            filter_ok = (not filter_values or all(str(metadata.get(k)) == str(v)
                                                  for k, v in filter_values.items()))
            passed = complete and matches_source and text_matches
            rows.append({
                "question_id": trace["question_id"],
                "strategy": trace["strategy"],
                "rank": rank,
                "chunk_id": hit["chunk_id"],
                "unit_id": metadata.get("unit_id", ""),
                "chapter": metadata.get("chapter", ""),
                "source_page_or_unit": hit["page"],
                "filter_applicable": bool(filter_values),
                "filter_compliant": filter_ok,
                "metadata_complete": complete,
                "metadata_matches_manifest": matches_source,
                "chunk_text_matches_unit_range": text_matches,
                "audit_pass": passed,
            })

    suffix = "_exploratory" if summary.get("run_type", "").startswith("exploratory") else ""
    output = ROOT / "results" / f"metadata_audit{suffix}.csv"
    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {output.name}: {sum(row['audit_pass'] for row in rows)}/{len(rows)} metadata rows pass")


if __name__ == "__main__":
    main()
