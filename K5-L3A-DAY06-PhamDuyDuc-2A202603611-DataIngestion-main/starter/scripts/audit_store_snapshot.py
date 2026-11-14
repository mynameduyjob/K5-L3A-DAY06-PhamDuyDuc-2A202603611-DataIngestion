"""Read-only audit that the persistent pgvector rows match this corpus/chunker."""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.chunking import by_paragraph, fixed_size
from src.run import _load_corpus
from src.store import PgVectorStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reingest", action="store_true",
                        help="transactionally replace each strategy with the same persisted real vectors, then verify no duplicates")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    _, pages = _load_corpus(ROOT / "manifest.json")
    expected = {
        "A": [chunk for page in pages for chunk in fixed_size(page, size=500, overlap=50)],
        "B": [chunk for page in pages for chunk in by_paragraph(page, max_size=1000)],
    }
    expected["C"] = expected["B"]
    database_url = os.environ.get("DATABASE_URL", "")
    store = PgVectorStore(database_url, 2048)
    print(store.describe())
    audit = {"store": store.describe(), "reingest_used_cached_real_model_vectors": bool(args.reingest),
             "strategies": {}}
    with psycopg.connect(database_url) as conn:
        for strategy, chunks in expected.items():
            rows = conn.execute(
                "SELECT chunk_id, document_id, source, page, text, metadata, embedding::text FROM document_chunks WHERE strategy = %s",
                (strategy,),
            ).fetchall()
            actual = {row[0]: row[1:6] for row in rows}
            by_id = {chunk.chunk_id: chunk for chunk in chunks}
            same_ids = set(actual) == set(by_id)
            same_rows = same_ids and all(
                actual[chunk_id] == (
                    by_id[chunk_id].document_id,
                    by_id[chunk_id].source,
                    by_id[chunk_id].page,
                    by_id[chunk_id].text,
                    by_id[chunk_id].metadata,
                )
                for chunk_id in by_id
            )
            distinct_count = len(actual)
            print({
                "strategy": strategy,
                "expected_chunks": len(chunks),
                "database_rows": len(rows),
                "distinct_chunk_ids": distinct_count,
                "ids_match": same_ids,
                "content_and_metadata_match": same_rows,
            })
            if len(rows) != len(chunks) or distinct_count != len(chunks) or not same_rows:
                raise SystemExit(f"Persistent store snapshot does not match current {strategy} chunks")
            if args.reingest:
                # Reuse only the already persisted, real model vectors after the
                # exact source/chunk/metadata snapshot has passed the checks above.
                vector_by_id = {
                    row[0]: [float(value) for value in row[6].strip("[]").split(",")]
                    for row in rows
                }
                ordered_chunks = sorted(chunks, key=lambda chunk: chunk.chunk_id)
                vectors = [vector_by_id[chunk.chunk_id] for chunk in ordered_chunks]
                started = time.perf_counter()
                store.upsert(strategy, ordered_chunks, vectors)
                upsert_seconds = time.perf_counter() - started
                with psycopg.connect(database_url) as verify_conn:
                    after = verify_conn.execute(
                        "SELECT chunk_id, embedding::text FROM document_chunks WHERE strategy = %s ORDER BY chunk_id",
                        (strategy,),
                    ).fetchall()
                preserved_vectors = all(
                    row[1] == rows_by_id[row[0]][6] for row in after
                ) if (rows_by_id := {item[0]: item for item in rows}) else False
                after_ids = [row[0] for row in after]
                reingest_ok = (len(after) == len(chunks)
                               and len(set(after_ids)) == len(chunks)
                               and set(after_ids) == set(by_id)
                               and preserved_vectors)
                print({"strategy": strategy, "same_snapshot_reingested": True,
                       "rows_after_reingest": len(after), "distinct_ids_after_reingest": len(set(after_ids)),
                       "vectors_preserved": preserved_vectors, "no_duplicate_rows": reingest_ok,
                       "upsert_seconds": upsert_seconds})
                audit["strategies"][strategy] = {
                    "expected_rows": len(chunks), "rows_after_reingest": len(after),
                    "distinct_ids": len(set(after_ids)), "content_and_metadata_match": same_rows,
                    "vectors_preserved": preserved_vectors, "no_duplicate_rows": reingest_ok,
                    "upsert_seconds_with_cached_vectors": upsert_seconds,
                    "embedding_seconds": 0.0,
                }
                if not reingest_ok:
                    raise SystemExit(f"Idempotent upsert verification failed for {strategy}")
    if args.reingest:
        output = ROOT / "results" / "store_snapshot_audit.json"
        output.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
