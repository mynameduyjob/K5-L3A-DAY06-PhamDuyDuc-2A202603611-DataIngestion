"""Prepare the same five-test-question audit rows for each strategy.

If matching retrieval traces do not exist, retrieved fields stay blank; old traces
from a different benchmark hash are never reused.
"""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "benchmark.json"
LOCK = ROOT / "benchmark.lock.json"
SUMMARY = ROOT / "results" / "summary.json"
TRACES = ROOT / "results" / "traces.json"
OUTPUT = ROOT / "results" / "manual_audit_current.csv"


def main():
    benchmark_bytes = BENCHMARK.read_bytes()
    digest = hashlib.sha256(benchmark_bytes).hexdigest()
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    if digest != lock["sha256"]:
        raise SystemExit("benchmark.json does not match benchmark.lock.json")
    questions = json.loads(benchmark_bytes.decode("utf-8"))
    traces_by_key = {}
    if SUMMARY.exists() and TRACES.exists():
        summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
        if summary.get("question_sha256") == digest:
            traces = json.loads(TRACES.read_text(encoding="utf-8"))
            traces_by_key = {(trace["question_id"], trace["strategy"]): trace for trace in traces}

    rows = []
    for question in (q for q in questions if q["split"] == "test"):
        for strategy in ("A", "B", "C"):
            trace = traces_by_key.get((question["id"], strategy))
            hits = trace.get("hits", []) if trace else []
            top3 = [{key: hit.get(key) for key in ("chunk_id", "text", "score", "document_id", "source", "page", "metadata")}
                    for hit in hits[:3]]
            rows.append({
                "question_id": question["id"],
                "strategy": strategy,
                "question": question["question"],
                "expected_answer": question["expected_answer"],
                "filter": json.dumps(question.get("filter", {}), ensure_ascii=False),
                "accepted_evidence": json.dumps(question["accepted_evidence"], ensure_ascii=False),
                "top3_retrieval": json.dumps(top3, ensure_ascii=False) if trace else "",
                "automatic_evidence_hit_at_3": trace.get("evidence_hit_at_3") if trace else "",
                "grounding_score_0_2": "",
                "grounding_reason": "",
                "metadata_source_page_correct": "",
                "filter_compliant": "",
                "reviewer": "",
                "status": "pending_manual_review" if trace else "pending_retrieval",
            })
    with OUTPUT.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {OUTPUT.name}: {len(rows)} rows; {len(traces_by_key)} matching traces; benchmark {digest}")


if __name__ == "__main__":
    main()
