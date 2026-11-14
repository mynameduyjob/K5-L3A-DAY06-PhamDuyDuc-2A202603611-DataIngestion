"""Apply an explicitly AI-assisted, source-aware coherence draft.

Scores use BENCHMARK.md's 0-2 rubric: 0 unclear/cut thought, 1 partly
understandable but clipped or context-dependent, 2 self-contained and coherent.
The sample is fixed before inspection at unit pages 2,7,...,47, midpoint anchor,
first chunk covering the anchor. A/C relationships are explicit: C reuses B.
Student confirmation remains pending; this is not an independent human rating.
"""
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "results" / "coherence_audit_current.csv"
REVIEWER = "AI-assisted source-aware review; student confirmation pending"

LABELS = {
    "chapter-01-unit-02": (1, "Chunk clips the start and end of the exchange; the gist remains partly understandable.", "Chunk begins mid-exchange and ends mid-thought; the connected exchange is still partly understandable."),
    "chapter-02-unit-04": (1, "Fixed window begins with a clipped word and ends mid-question; the discussion topic is partly recoverable.", "Dialogue begins mid-turn without its setup, but the exchange itself remains partly understandable."),
    "chapter-04-unit-02": (1, "The window starts and ends inside sentences, obscuring both the antecedent and continuation.", "The chunk starts mid-sentence and relies on prior context, although the coin/potato explanation is mostly intact."),
    "chapter-06-unit-02": (1, "The passage starts after its antecedent and ends at an unfinished name; only part of the episode is self-contained.", "The chunk starts with an unexplained pronoun/action but preserves most of the escape episode."),
    "chapter-07-unit-02": (1, "It starts with a truncated word and cuts off during the list of supplies.", "It preserves the full raft-sale and escape sequence with a clear beginning and ending."),
    "chapter-08-unit-02": (1, "It begins inside a quoted clause and cuts off during the boat's turn.", "It retains the cannon episode and the boat's full search path as a coherent sequence."),
    "chapter-08-unit-07": (1, "The start is clipped and the ending trails off before the next thought finishes.", "It begins mid-context and ends with a lead-in to the next chunk, but the superstition examples are partly clear."),
    "chapter-10-unit-01": (1, "The start clips a noun phrase and the final sentence is cut off.", "It preserves the snake episode from discovery through Jim's injury and response."),
    "chapter-11-unit-03": (1, "It starts in the middle of a sentence and omits the setup for the exchange.", "It keeps the needle-threading interaction and the woman's response in a connected passage."),
    "chapter-12-unit-02": (1, "The start and end both cut through sentences, leaving the travel sequence incomplete.", "It presents a connected account of the second night through the view of St. Louis."),
}


def main():
    with PATH.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
        fields = list(rows[0])
    for row in rows:
        score_a, reason_a, reason_b = LABELS[row["unit_id"]]
        if row["strategy"] == "A":
            score, reason = score_a, reason_a
        else:
            # B and C have identical chunk IDs and text by design.
            b_score = 2 if row["unit_id"] in {
                "chapter-07-unit-02", "chapter-08-unit-02", "chapter-10-unit-01",
                "chapter-11-unit-03", "chapter-12-unit-02",
            } else 1
            score, reason = b_score, reason_b
        row["coherence_score_0_2"] = str(score)
        row["reason"] = reason
        row["reviewer"] = REVIEWER
        row["status"] = "ai_draft_pending_student_confirmation"
    with PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    scores = defaultdict(list)
    for row in rows:
        scores[row["strategy"]].append(int(row["coherence_score_0_2"]))
    for strategy, values in sorted(scores.items()):
        print(f"{strategy}: {sum(values)}/{len(values)} = {sum(values) / len(values):.2f}/2 (AI draft; confirmation pending)")


if __name__ == "__main__":
    main()
