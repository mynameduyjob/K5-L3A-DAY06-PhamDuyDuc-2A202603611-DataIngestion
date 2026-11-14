"""Evidence-based retrieval metrics and trace serialization helpers."""
import re
import unicodedata
from collections import defaultdict
from typing import Any


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFC", value or "").casefold()
    return " ".join(re.findall(r"\w+", value, flags=re.UNICODE))


def _evidence_hit(question: dict[str, Any], hit: dict[str, Any]) -> bool:
    accepted = question.get("accepted_evidence") or [{
        "source_id": question["gold_source_id"], "page": question["gold_page"],
        "unit_id": question.get("gold_unit_id"), "quote": question["evidence_quote"],
    }]
    for candidate in accepted:
        correct_location = (hit["document_id"] == candidate["source_id"]
                            and str(hit["page"]) == str(candidate["page"]))
        if candidate.get("unit_id"):
            correct_location = correct_location and hit["metadata"].get("unit_id") == candidate["unit_id"]
        quote = _normalize(candidate["quote"])
        if correct_location and quote and quote in _normalize(hit["text"]):
            return True
    return False


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    evidence_hits = [_evidence_hit(question, hit) for hit in hits]
    filters = question.get("filter") or {}
    filter_compliant = [all(str(hit["metadata"].get(k)) == str(v) for k, v in filters.items())
                        for hit in hits]
    return {
        "question_id": question["id"],
        "split": question["split"],
        "question": question["question"],
        "gold_source_id": question["gold_source_id"],
        "gold_page": question["gold_page"],
        "gold_unit_id": question.get("gold_unit_id"),
        "evidence_quote": question["evidence_quote"],
        "accepted_evidence": question.get("accepted_evidence"),
        "filter": filters,
        "hits": hits,
        "hit_at_1": bool(evidence_hits and evidence_hits[0]),
        "evidence_hit_at_3": any(evidence_hits[:3]),
        "filter_compliant_at_3": all(filter_compliant[:3]) if filters and hits else (None if not filters else False),
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for trace in traces:
        groups[(trace["strategy"], trace["split"])].append(trace)
    summary = {}
    for (strategy, split), rows in sorted(groups.items()):
        count = len(rows)
        filter_rows = [r for r in rows if r.get("filter")]
        filter_hits = [r["filter_compliant_at_3"] for r in filter_rows]
        summary[f"{strategy}/{split}"] = {
            "questions": count,
            "hit_at_1": {"hits": sum(r["hit_at_1"] for r in rows), "total": count},
            "evidence_hit_at_3": {"hits": sum(r["evidence_hit_at_3"] for r in rows), "total": count},
            "filter_compliant_at_3": ({"hits": sum(bool(v) for v in filter_hits), "total": len(filter_hits)}
                                       if filter_rows else None),
        }
    return summary
