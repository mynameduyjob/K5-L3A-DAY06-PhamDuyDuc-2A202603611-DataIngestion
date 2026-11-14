"""Run the three retrieval strategies described in GUIDE.md."""
import json
import hashlib
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size
from .embeddings import MyEmbedder
from .evaluation import evaluate_query, summarize
from .ingestion import load_pdf, load_text_units
from .store import PgVectorStore

ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _load_corpus(manifest_path: Path):
    manifest = _read_json(manifest_path)
    sources = manifest.get("sources", [])
    if not sources:
        raise ValueError("manifest.json must contain a non-empty 'sources' list")
    pages, source_ids = [], set()
    for source in sources:
        required = ("source_id", "title", "path", "license_or_permission", "accessed_at", "metadata")
        missing = [key for key in required if key not in source]
        if missing:
            raise ValueError(f"Manifest source is missing fields: {', '.join(missing)}")
        if source["source_id"] in source_ids:
            raise ValueError(f"Duplicate source_id: {source['source_id']}")
        source_ids.add(source["source_id"])
        if not source["license_or_permission"].strip():
            raise ValueError(f"Record reuse/processing rights for {source['source_id']}")
        pdf = (ROOT / source["path"]).resolve()
        if not pdf.is_relative_to(ROOT.resolve()) or not pdf.is_file():
            raise ValueError(f"Source PDF must exist inside starter/: {source['path']}")
        if pdf.suffix.casefold() == ".pdf":
            if "included_pages" not in source:
                raise ValueError(f"PDF source needs included_pages: {source['source_id']}")
            pages.extend(load_pdf(pdf, source["source_id"], source["title"],
                                  source["included_pages"], source["metadata"]))
        elif pdf.suffix.casefold() == ".txt":
            if "included_units" not in source:
                raise ValueError(f"Text source needs included_units: {source['source_id']}")
            pages.extend(load_text_units(pdf, source["source_id"], source["title"],
                                         source["included_units"], source["metadata"]))
        else:
            raise ValueError(f"Unsupported source format {pdf.suffix!r}; use PDF or UTF-8 TXT")
    useful = [page for page in pages if len(page.text) >= 100]
    if len(useful) < 30:
        raise ValueError(f"Need at least 30 extracted content pages; found {len(useful)}. Check manifest and PDFs.")
    if any(page.metadata["extraction_status"] != "ok" for page in pages):
        empty = [f"{p.document_id}:p{p.page}" for p in pages if not p.text]
        raise ValueError("Empty/scanned pages need OCR or removal from included_pages: " + ", ".join(empty))
    return manifest, pages


def _load_questions(path: Path, pages):
    questions = _read_json(path)
    if not isinstance(questions, list):
        raise ValueError("benchmark.json must be a JSON array of question records")
    if len(questions) < 20:
        raise ValueError(f"Need at least 20 questions; found {len(questions)}")
    ids = set()
    page_lookup = {(p.document_id, str(p.page)): p for p in pages}
    for q in questions:
        required = ("id", "split", "question", "question_type", "topic_chapter", "expected_answer", "gold_source_id", "gold_page", "evidence_quote")
        missing = [key for key in required if key not in q]
        if missing:
            raise ValueError(f"Question missing fields {missing}: {q.get('id', '<no id>')}")
        if q["id"] in ids:
            raise ValueError(f"Duplicate question id: {q['id']}")
        ids.add(q["id"])
        if q["split"] not in ("dev", "test"):
            raise ValueError(f"Question {q['id']}: split must be dev or test")
        if q["question_type"] not in ("direct", "paraphrase", "condition", "exception"):
            raise ValueError(f"Question {q['id']}: question_type must be direct, paraphrase, condition, or exception")
        page = page_lookup.get((q["gold_source_id"], str(q["gold_page"])))
        if page is None:
            raise ValueError(f"Question {q['id']}: gold page is not in the included corpus")
        if q.get("gold_unit_id") and page.metadata.get("unit_id") != q["gold_unit_id"]:
            raise ValueError(f"Question {q['id']}: gold_unit_id does not match gold_page")
        if str(page.metadata.get("chapter")) != str(q["topic_chapter"]):
            raise ValueError(f"Question {q['id']}: topic_chapter does not match the gold source location")
        accepted = q.get("accepted_evidence") or [{
            "source_id": q["gold_source_id"], "page": q["gold_page"],
            "unit_id": q.get("gold_unit_id"), "quote": q["evidence_quote"],
        }]
        if not isinstance(accepted, list) or not accepted:
            raise ValueError(f"Question {q['id']}: accepted_evidence must be a non-empty list")
        accepted_locations = set()
        for candidate in accepted:
            candidate_page = page_lookup.get((candidate.get("source_id"), str(candidate.get("page"))))
            if candidate_page is None:
                raise ValueError(f"Question {q['id']}: accepted evidence page is not in the corpus")
            if candidate.get("unit_id") and candidate_page.metadata.get("unit_id") != candidate["unit_id"]:
                raise ValueError(f"Question {q['id']}: accepted evidence unit_id does not match its page")
            evidence = " ".join(str(candidate.get("quote", "")).split()).casefold()
            page_text = " ".join(candidate_page.text.split()).casefold()
            if not evidence or evidence not in page_text:
                raise ValueError(f"Question {q['id']}: accepted evidence quote is absent after normalization")
            accepted_locations.add((candidate["source_id"], str(candidate["page"]), candidate.get("unit_id"), candidate["quote"]))
        canonical = (q["gold_source_id"], str(q["gold_page"]), q.get("gold_unit_id"), q["evidence_quote"])
        if canonical not in accepted_locations:
            raise ValueError(f"Question {q['id']}: canonical gold evidence must also be listed in accepted_evidence")
        if not q["expected_answer"].strip() or not q["question"].strip():
            raise ValueError(f"Question {q['id']}: question and expected_answer must be non-empty")
        if q.get("filter") and not isinstance(q["filter"], dict):
            raise ValueError(f"Question {q['id']}: filter must be an object")
        expected_filter_source = "question" if q.get("filter") else "none"
        if q.get("filter_source") != expected_filter_source:
            raise ValueError(f"Question {q['id']}: filter_source must be {expected_filter_source!r}")
        for key, value in (q.get("filter") or {}).items():
            if not isinstance(key, str) or not key or isinstance(value, (dict, list)) or value is None:
                raise ValueError(f"Question {q['id']}: filter keys must be non-empty strings and values must be scalar")
            if not any(str(page.metadata.get(key)) == str(value) for page in pages):
                raise ValueError(f"Question {q['id']}: filter {key}={value!r} is not present in corpus metadata")
            if str(value).casefold() not in q["question"].casefold():
                raise ValueError(f"Question {q['id']}: filter value {value!r} must be stated in the question before retrieval")
    counts = Counter(q["split"] for q in questions)
    if counts["dev"] < 15 or counts["test"] < 5:
        raise ValueError(f"Need at least 15 dev and 5 test questions; found {dict(counts)}")
    filtered = [q for q in questions if q.get("filter")]
    if len(filtered) < 3 or not any(q["split"] == "test" for q in filtered):
        raise ValueError("Need at least 3 metadata-filter questions, including at least 1 test question")
    question_types = {q["question_type"] for q in questions}
    if not {"direct", "paraphrase"}.issubset(question_types) or not question_types.intersection({"condition", "exception"}):
        raise ValueError("Benchmark needs direct, paraphrase, and condition/exception question types")
    return questions


def _validate_benchmark_lock(benchmark_path: Path, lock_path: Path) -> dict:
    """Refuse to run if the benchmark differs from its explicitly frozen snapshot."""
    if not lock_path.is_file():
        raise ValueError("benchmark.lock.json is missing; validate and freeze the benchmark before running")
    lock = _read_json(lock_path)
    actual_hash = hashlib.sha256(benchmark_path.read_bytes()).hexdigest()
    if actual_hash != lock.get("sha256"):
        raise ValueError("benchmark.json changed after it was frozen; do not run until the benchmark version is reviewed and re-frozen")
    return lock


def main() -> None:
    load_dotenv(ROOT / ".env")
    results = ROOT / "results"
    results.mkdir(exist_ok=True)
    run_started = datetime.now(timezone.utc).isoformat()
    run_clock = time.perf_counter()
    stage = "load_corpus"
    strategy_in_progress = None
    lock = None
    model_name = None
    progress = {"run_started_utc": run_started, "strategies": {}}

    def save_progress() -> None:
        (results / "run_progress.json").write_text(
            json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    try:
        manifest, pages = _load_corpus(ROOT / "manifest.json")
        benchmark_path = ROOT / "benchmark.json"
        lock = _validate_benchmark_lock(benchmark_path, ROOT / "benchmark.lock.json")
        questions = _load_questions(benchmark_path, pages)
        progress.update({
            "benchmark_sha256": lock["sha256"],
            "source_units": len(pages),
            "source_characters": sum(len(page.text) for page in pages),
            "question_count": len(questions),
            "split_counts": dict(Counter(q["split"] for q in questions)),
        })
        model_name = os.environ.get("EMBEDDING_MODEL", "").strip()
        embedder = MyEmbedder(model_name)
        store = PgVectorStore(os.environ.get("DATABASE_URL", ""), embedder.dimensions)
        progress.update({"model": embedder.model_name,
                         "embedding_dimensions": embedder.dimensions,
                         "provider": embedder.provider_name,
                         "model_revision": embedder.model_revision,
                         "device": embedder.device})

        stage = "initialize_vector_store"
        store.create_schema()
        store_description = store.describe()

        stage = "chunking"
        chunk_started = time.perf_counter()
        pages_a = [chunk for page in pages for chunk in fixed_size(page, size=500, overlap=50)]
        chunking_a_seconds = time.perf_counter() - chunk_started
        chunk_started = time.perf_counter()
        pages_b = [chunk for page in pages for chunk in by_paragraph(page, max_size=1000)]
        chunking_b_seconds = time.perf_counter() - chunk_started
        strategies = {"A": pages_a, "B": pages_b, "C": pages_b}
        elapsed, chunk_stats, usage_stats, stored_rows = {}, {}, {}, {}
        chunking_times = {"A": chunking_a_seconds, "B": chunking_b_seconds, "C": 0.0}
        for name, chunks in strategies.items():
            lengths = sorted(len(chunk.text) for chunk in chunks)
            chunk_stats[name] = {
                "count": len(chunks),
                "characters": sum(lengths),
                "length_chars": {
                    "min": lengths[0] if lengths else 0,
                    "median": lengths[len(lengths) // 2] if lengths else 0,
                    "max": lengths[-1] if lengths else 0,
                },
                "length_histogram_chars": {
                    "1-250": sum(1 <= value <= 250 for value in lengths),
                    "251-500": sum(251 <= value <= 500 for value in lengths),
                    "501-750": sum(501 <= value <= 750 for value in lengths),
                    "751-1000": sum(751 <= value <= 1000 for value in lengths),
                    "1001+": sum(value > 1000 for value in lengths),
                },
            }
        progress["chunk_stats"] = chunk_stats
        progress["chunking_seconds"] = chunking_times
        save_progress()

        for strategy, chunks in strategies.items():
            strategy_in_progress = strategy
            progress["active_strategy"] = strategy
            # B and C use identical chunks, so reuse vectors and avoid duplicate API calls.
            if strategy == "C":
                vectors = vectors_b
                seconds = 0.0
                usage = {
                    "successful_requests": 0, "successful_batches": 0,
                    "prompt_tokens": 0, "total_tokens": 0,
                    "reported_cost_usd": 0.0, "usage_reported": True, "cost_reported": True,
                }
            else:
                started = time.perf_counter()
                stage = f"embed_documents_{strategy}"
                embedder.reset_usage()
                try:
                    vectors = embedder.embed_documents([chunk.text for chunk in chunks])
                finally:
                    seconds = time.perf_counter() - started
                    usage = embedder.usage_snapshot()
                    progress.setdefault("strategies", {})[strategy] = {
                        "chunking_seconds": chunking_times[strategy],
                        "document_embedding_seconds": seconds,
                        "embedding_usage": usage,
                        "chunk_count": chunk_stats[strategy]["count"],
                        "chunk_characters": chunk_stats[strategy]["characters"],
                    }
                    save_progress()
                if strategy == "B":
                    vectors_b = vectors
            elapsed[strategy] = seconds
            usage_stats[strategy] = usage
            progress.setdefault("strategies", {})[strategy] = {
                "chunking_seconds": chunking_times[strategy],
                "document_embedding_seconds": seconds,
                "embedding_usage": usage,
                "chunk_count": chunk_stats[strategy]["count"],
                "chunk_characters": chunk_stats[strategy]["characters"],
            }
            save_progress()

            stage = f"store_upsert_{strategy}"
            upsert_started = time.perf_counter()
            stored_rows[strategy] = store.upsert(strategy, chunks, vectors)
            upsert_seconds = time.perf_counter() - upsert_started
            progress["strategies"][strategy].update({
                "upsert_seconds": upsert_seconds,
                "stored_rows": stored_rows[strategy],
            })
            progress["strategies"][strategy]["ingest_seconds"] = (
                chunking_times[strategy] + seconds + upsert_seconds
            )
            save_progress()

        stage = "embed_queries"
        strategy_in_progress = None
        embedder.reset_usage()
        started = time.perf_counter()
        query_vectors = embedder.embed_documents([q["question"] for q in questions])
        query_seconds = time.perf_counter() - started
        query_usage = embedder.usage_snapshot()
        traces = []
        retrieval_seconds = {}
        for strategy in ("A", "B", "C"):
            stage = f"retrieve_{strategy}"
            retrieval_started = time.perf_counter()
            for question, query_vector in zip(questions, query_vectors):
                filters = question.get("filter") if strategy == "C" else None
                hits = store.search(strategy, query_vector, top_k=3, filters=filters)
                trace = evaluate_query(question, hits)
                trace["strategy"] = strategy
                trace["expected_answer"] = question["expected_answer"]
                trace["question_type"] = question["question_type"]
                trace["topic_chapter"] = question["topic_chapter"]
                traces.append(trace)
            retrieval_seconds[strategy] = time.perf_counter() - retrieval_started

        (results / "traces.json").write_text(json.dumps(traces, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = summarize(traces)
        def embedding_cost(usage: dict) -> float | None:
            if embedder.model_name.endswith(":free"):
                return 0.0
            return usage.get("reported_cost_usd")

        report = {
            "run_started_utc": run_started,
            "corpus_manifest": "manifest.json",
            "question_file": "benchmark.json",
            "question_sha256": lock["sha256"],
            "trace_file": "results/traces.json",
            "benchmark_lock": "benchmark.lock.json",
            "benchmark_independence_status": lock.get("independence_status", "unspecified"),
            "run_type": "exploratory_holdout; do not treat test metrics as independent because earlier test results were inspected",
            "sources": len(manifest["sources"]),
            "questions": len(questions),
            "same_questions_and_labels_for_all_strategies": True,
            "physical_pages_extracted": sum(p.metadata.get("location_type") == "physical_page" for p in pages),
            "source_units_loaded": len(pages),
            "content_units_counted": sum(len(p.text) >= 100 for p in pages),
            "provider": embedder.provider_name,
            "model": embedder.model_name,
            "model_revision": embedder.model_revision,
            "device": embedder.device,
            "embedding_dimensions": embedder.dimensions,
            "document_query_embedding_method": "same provider, model, tokenizer and encode method for chunks and queries; local embeddings are L2-normalized before cosine search",
            "source_characters": sum(len(page.text) for page in pages),
            "source_tokens_reported_by_provider": None,
            "vector_store": store_description,
            "search": "exact cosine distance (<=>); no ANN index",
            "reingest_policy": "Each strategy is transactionally deleted and replaced; chunk primary keys and post-upsert row counts prevent duplicates. Source edits are re-read, rechunked and re-embedded on the next run.",
            "strategies": {
                name: {"chunking": "fixed 500 chars, overlap 50" if name == "A" else "paragraph-aware, max 1000 chars",
                       "metadata_filter": name == "C", **chunk_stats[name],
                       "chunking_seconds": chunking_times[name],
                       "document_embedding_seconds": elapsed[name],
                       "document_embedding_prompt_tokens": usage_stats[name]["prompt_tokens"],
                       "document_embedding_total_tokens": usage_stats[name]["total_tokens"],
                       "document_embedding_requests": usage_stats[name]["successful_requests"],
                       "document_embedding_batches": usage_stats[name]["successful_batches"],
                       "document_embeddings_reused_from": "B" if name == "C" else None,
                       "document_embedding_cost_usd": embedding_cost(usage_stats[name]),
                       "upsert_seconds": progress["strategies"][name]["upsert_seconds"],
                       "stored_rows": stored_rows[name],
                       "ingest_seconds": progress["strategies"][name]["ingest_seconds"]}
                for name in ("A", "B", "C")
            },
            "query_embedding_seconds": query_seconds,
            "query_embedding_tokens": query_usage["total_tokens"],
            "query_embedding_requests": query_usage["successful_requests"],
            "query_embedding_batches": query_usage["successful_batches"],
            "query_embedding_cost_usd": embedding_cost(query_usage),
            "total_paid_api_cost_usd": (
                sum(embedding_cost(usage_stats[name]) or 0.0 for name in ("A", "B", "C"))
                + (embedding_cost(query_usage) or 0.0)
            ),
            "retrieval_seconds": retrieval_seconds,
            "end_to_end_seconds": time.perf_counter() - run_clock,
            "metrics": summary,
            "manual_assessment": "See results/manual_audit_current.csv; labels require reviewer completion.",
        }
        (results / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (results / "last_error.json").unlink(missing_ok=True)
        progress.update({"status": "completed", "summary_file": "summary.json",
                         "trace_file": "traces.json", "end_to_end_seconds": report["end_to_end_seconds"]})
        save_progress()
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception as exc:
        progress.update({"status": "failed", "stage": stage,
                         "strategy": strategy_in_progress,
                         "elapsed_seconds": time.perf_counter() - run_clock})
        save_progress()
        error = {
            "run_started_utc": run_started,
            "benchmark_sha256": lock.get("sha256") if lock else None,
            "model": model_name,
            "stage": stage,
            "strategy": strategy_in_progress,
            "elapsed_seconds": time.perf_counter() - run_clock,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        (results / "last_error.json").write_text(json.dumps(error, ensure_ascii=False, indent=2), encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
