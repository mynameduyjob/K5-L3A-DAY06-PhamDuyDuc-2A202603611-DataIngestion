"""Explicitly freeze the current benchmark bytes for a subsequent run.

Run only before evaluating this exact question set. The lock is checked by src.run.
"""
import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.run import _load_corpus, _load_questions

BENCHMARK = ROOT / "benchmark.json"
LOCK = ROOT / "benchmark.lock.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replace", action="store_true", help="replace an existing lock; only for a new, unrun benchmark version")
    args = parser.parse_args()
    if LOCK.exists() and not args.replace:
        raise SystemExit("Lock already exists. Keep it unchanged after a run; use --replace only for a new, unrun benchmark version.")
    questions = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    if args.replace:
        summary_path = ROOT / "results" / "summary.json"
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            current_hash = hashlib.sha256(BENCHMARK.read_bytes()).hexdigest()
            if summary.get("question_sha256") == current_hash:
                raise SystemExit("This benchmark hash already has a run summary; it cannot be re-frozen as unrun.")
    _, pages = _load_corpus(ROOT / "manifest.json")
    _load_questions(BENCHMARK, pages)
    counts = Counter(q["split"] for q in questions)
    filtered = Counter(q["split"] for q in questions if q.get("filter"))
    chapter_splits = {
        split: sorted({q["topic_chapter"] for q in questions if q["split"] == split},
                      key=lambda chapter: (len(chapter), chapter))
        for split in ("dev", "test")
    }
    chapter_overlap = sorted(set(chapter_splits["dev"]) & set(chapter_splits["test"]))
    if len(questions) < 20 or counts["dev"] < 15 or counts["test"] < 5:
        raise SystemExit(f"Insufficient benchmark size/split: total={len(questions)}, splits={dict(counts)}")
    if sum(filtered.values()) < 3 or filtered["test"] < 1:
        raise SystemExit(f"Need >=3 filter questions including >=1 test; found {dict(filtered)}")
    required_types = {"direct", "paraphrase"}
    types = {q.get("question_type") for q in questions}
    if not required_types.issubset(types) or not types.intersection({"condition", "exception"}):
        raise SystemExit(f"Question types lack required variety: {sorted(str(x) for x in types)}")
    if chapter_overlap:
        raise SystemExit(f"Dev/test chapter groups overlap: {chapter_overlap}")
    lock = {
        "benchmark_file": "benchmark.json",
        "sha256": hashlib.sha256(BENCHMARK.read_bytes()).hexdigest(),
        "locked_at_utc": datetime.now(timezone.utc).isoformat(),
        "question_count": len(questions),
        "split_counts": dict(counts),
        "filtered_counts": dict(filtered),
        "question_types": dict(Counter(q["question_type"] for q in questions)),
        "chapter_groups": chapter_splits,
        "dev_test_chapter_overlap": chapter_overlap,
        "test_question_ids": [q["id"] for q in questions if q["split"] == "test"],
        "locked_before_first_run": True,
        "independence_status": "topic_grouped_unrun_test_with_prior_exploratory_leakage_risk; current test rows have not been run",
        "risk_note": "Dev/test questions are grouped by disjoint chapters, but earlier exploratory test results from chapters VIII-XII were inspected. Do not describe the new test as an independent holdout. Keep this lock and benchmark unchanged after the first run; later corrections require a new benchmark version and exploratory labeling.",
    }
    LOCK.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(lock, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
