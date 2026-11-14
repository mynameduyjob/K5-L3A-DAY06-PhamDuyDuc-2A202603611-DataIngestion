"""Build the fixed, evidence-checked benchmark for the selected units."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.run import _load_corpus

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifest.json"
OUTPUT = ROOT / "benchmark.json"
LOCK = ROOT / "benchmark.lock.json"

# The current questions have not been run through retrieval. Earlier exploratory
# test results are known, so this replacement split is not an independent holdout.
# Every quote is checked against the manifest unit and chapter before writing.
# These type labels make the mix auditable; they do not affect retrieval.
QUESTION_TYPES = [
    "direct", "exception", "paraphrase", "direct", "paraphrase",
    "paraphrase", "direct", "paraphrase", "direct", "condition",
    "direct", "direct", "direct", "condition", "direct",
    "paraphrase", "paraphrase", "condition", "direct", "condition",
    "paraphrase", "paraphrase", "condition",
]
ITEMS = [
    ("dev", "Who does Huck say wrote The Adventures of Tom Sawyer, and how does he describe its truthfulness?", "Mark Twain wrote it, and Huck says the book mostly told the truth.", "That book was made by Mr. Mark Twain, and he told the truth, mainly. There was things which he stretched, but mainly he told the truth.", "I", None),
    ("dev", "Which people does Huck name as exceptions when he says most people have lied?", "Aunt Polly, the widow, and possibly Mary.", "I never seen anybody but lied one time or another, without it was Aunt Polly, or the widow, or maybe Mary.", "I", None),
    ("dev", "Where are Huck and Tom walking when they try to move quietly away from the house?", "Along a path through the trees toward the end of the widow's garden.", "We went tiptoeing along a path amongst the trees back towards the end of the widow", "II", None),
    ("dev", "In Chapter II, what name does Tom give his gang, and what do the members plan to do to travelers?", "He calls them highwaymen; they plan to stop travelers, rob them, and kill them.", "We are highwaymen. We stop stages and carriages on the road, with masks on, and kill the people and take their watches and money.", "II", {"chapter": "II"}),
    ("dev", "Why does Miss Watson reprimand Huck the morning after the boys' nighttime outing?", "Because of his dirty clothes, covered with grease and clay.", "Well, I got a good going-over in the morning from old Miss Watson on account of my clothes; but the widow she didn’t scold, but only cleaned off the grease and clay", "III", None),
    ("dev", "What does Miss Watson tell Huck to do to receive what he asks for?", "Pray every day.", "She told me to pray every day, and whatever I asked for I would get it.", "III", None),
    ("dev", "What does Huck say he can do after attending school for several months?", "He can spell, read, and write a little.", "I had been to school most all the time and could spell and read and write just a little", "IV", None),
    ("dev", "What does Huck ask Judge Thatcher to do with the six thousand dollars?", "Take it; Huck says he wants to give him all of it.", "I want you to take it; I want to give it to you", "IV", None),
    ("dev", "Why does Huck say he is afraid of Pap?", "Pap used to beat him.", "I used to be scared of him all the time, he tanned me so much.", "V", None),
    ("dev", "What does Pap threaten to do if Huck keeps attending school?", "He threatens to beat him.", "if I catch you about that school I’ll tan you good.", "V", None),
    ("dev", "In Chapter VI, how long does Pap leave Huck locked in the cabin on one occasion?", "Three days.", "Once he locked me in and was gone three days.", "VI", {"chapter": "VI"}),
    ("dev", "What does Pap say the jug of whisky contains enough for?", "Two drunks and one delirium tremens.", "After supper pap took the jug, and said he had enough whisky there for two drunks and one delirium tremens.", "VI", None),
    ("dev", "What animal does Huck find while hunting for birds in the woods?", "A wild pig.", "and was hunting around for some birds when I see a wild pig", "VII", None),
    ("dev", "After checking the bank, what does Huck conclude about whether anyone can see his tracks?", "He says it is all safe and he has left no track.", "It was all grass clear to the canoe, so I hadn’t left a track.", "VII", None),
    ("dev", "When Huck wakes on Jackson's Island, what time does he estimate it is?", "After eight o'clock.", "The sun was up so high when I waked that I judged it was after eight o’clock.", "VIII", None),
    ("dev", "In Chapter I, what does the widow say she intends to do for Huck?", "She intends to civilize him.", "The Widow Douglas she took me for her son, and allowed she would sivilize me", "I", {"chapter": "I"}),
    ("dev", "What does Pap do with the three dollars Huck borrows from Judge Thatcher?", "Pap takes the money and gets drunk.", "I borrowed three dollars from Judge Thatcher, and pap took it and got drunk", "V", None),
    ("dev", "In Chapter VII, what two signs does Huck leave to make people think he was killed?", "He bloodies an axe with his hair and leaves the axe in the cabin.", "Well, last I pulled out some of my hair, and blooded the axe good, and stuck it on the back side, and slung the axe in the corner.", "VII", {"chapter": "VII"}),
    ("test", "In Chapter X, what bites Jim when he lies down on the blanket?", "The snake's mate bites Jim.", "when Jim flung himself down on the blanket while I struck a light the snake’s mate was there, and bit him.", "X", {"chapter": "X"}),
    ("test", "In Chapter XII, what danger does Jim suspect if they board the wreck?", "He suspects there may be a watchman aboard.", "Like as not dey’s a watchman on dat wrack.", "XII", {"chapter": "XII"}),
    ("test", "In Chapter IX, why does Jim want their supplies moved into the cavern?", "The cavern would shelter their belongings from rain and hide them if anyone came to the island.", "Jim said if we had the canoe hid in a good place, and had all the traps in the cavern, we could rush there if anybody was to come to the island, and they would never find us without dogs. And, besides, he said them little birds had said it was going to rain, and did I want the things to get wet?", "IX", {"chapter": "IX"}),
    ("test", "In Chapter XI, what does Mrs. Loftus say about the man who directed Huck to Goshen?", "She says he was probably drunk and gave Huck exactly the wrong directions.", "He was drunk, I reckon. He told you just exactly wrong.", "XI", {"chapter": "XI"}),
    ("test", "In Chapter XI, if Huck gets into trouble after leaving, whom does Mrs. Loftus tell him to contact, and what will she do?", "He should send word to Mrs. Judith Loftus, and she will try to help him.", "if you get into trouble you send word to Mrs. Judith Loftus, which is me, and I’ll do what I can to get you out of it.", "XI", {"chapter": "XI"}),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replace-unrun-lock", action="store_true", help="replace a frozen benchmark only when its hash has no run summary")
    args = parser.parse_args()
    if LOCK.exists():
        if not args.replace_unrun_lock:
            raise SystemExit("benchmark.lock.json exists; benchmark is frozen. Use --replace-unrun-lock only for an unrun version.")
        summary_path = ROOT / "results" / "summary.json"
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            previous_lock = json.loads(LOCK.read_text(encoding="utf-8"))
            if summary.get("question_sha256") == previous_lock.get("sha256"):
                raise SystemExit("This benchmark hash already has a run summary; it cannot be replaced.")
    manifest, pages = _load_corpus(MANIFEST)
    questions = []
    for number, (split, question, answer, quote, chapter, filters) in enumerate(ITEMS, start=1):
        normalized_quote = " ".join(quote.split()).casefold()
        matches = [page for page in pages if page.metadata["chapter"] == chapter and normalized_quote in " ".join(page.text.split()).casefold()]
        if len(matches) != 1:
            raise ValueError(f"q{number:02d}: expected one evidence unit in chapter {chapter}, found {len(matches)} for quote {quote!r}")
        page = matches[0]
        questions.append({
            "id": f"q{number:02d}",
            "split": split,
            "question_type": QUESTION_TYPES[number - 1],
            "topic_chapter": chapter,
            "question": question,
            "expected_answer": answer,
            "gold_source_id": manifest["sources"][0]["source_id"],
            "gold_page": page.page,
            "gold_unit_id": page.metadata["unit_id"],
            "evidence_quote": quote,
            "accepted_evidence": [{
                "source_id": manifest["sources"][0]["source_id"],
                "page": page.page,
                "unit_id": page.metadata["unit_id"],
                "quote": quote,
            }],
            "filter": filters or {},
            "filter_source": "question" if filters else "none",
        })
    from src.run import _load_questions
    _load_questions_from_memory = OUTPUT.with_name(".benchmark.validation.json")
    _load_questions_from_memory.write_text(json.dumps(questions, ensure_ascii=False), encoding="utf-8")
    try:
        _load_questions(_load_questions_from_memory, pages)
    finally:
        _load_questions_from_memory.unlink(missing_ok=True)
    OUTPUT.write_text(json.dumps(questions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.name}: {len(questions)} questions; {sum(q['split'] == 'dev' for q in questions)} dev, {sum(q['split'] == 'test' for q in questions)} test")


if __name__ == "__main__":
    main()
