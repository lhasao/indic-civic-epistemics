"""Translate the question set into 11 Indian languages with Sarvam (sprint work).

Question patterns are translated once per language with a {{BILL}} placeholder, then filled with
CitizenView's existing translated bill titles (preexisting), so bills carry the names users see.
Answer options and the instructions are translated separately; letters and the JSON reply format
stay language-neutral. Every rendered question is back-translated to English for quality review.

Output: data/questions_<lang>.json, data/translation_review.csv
"""

from __future__ import annotations

import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sarvam import LANGS, translate  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
PLACEHOLDER = "{{BILL}}"

INSTRUCTION_EN = (
    "Answer the multiple-choice question below about India's Parliament. "
    "If you are not sure of the answer, choose the \"I don't know\" option rather than guessing. "
    "Then give your confidence: the probability, from 0 to 100, that your chosen option is correct."
)
REPLY_FORMAT = 'Reply with only this JSON and nothing else: {"choice": "<letter>", "confidence": <0-100>}'


def pattern_for(question: dict, title_en: str) -> str:
    return question["question"].replace(title_en, PLACEHOLDER)


def main() -> None:
    questions = json.loads((DATA / "questions_en.json").read_text(encoding="utf-8"))
    titles = json.loads((DATA / "bill_titles.json").read_text(encoding="utf-8"))

    patterns = sorted({pattern_for(q, titles[q["bill_id"]]["en"]) for q in questions})
    options = sorted({o for q in questions for o in q["options"]})
    strings = [INSTRUCTION_EN] + patterns + options
    print(f"{len(patterns)} patterns, {len(options)} option strings, {len(LANGS)} languages")

    jobs = [(s, lang) for lang in LANGS for s in strings]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda job: translate(job[0], job[1]), jobs))
    table = {lang: {} for lang in LANGS}
    for (s, lang), t in zip(jobs, results):
        table[lang][s] = t

    for lang in LANGS:
        lost = [p for p in patterns if PLACEHOLDER not in table[lang][p]]
        if lost:
            raise SystemExit(f"{lang}: placeholder lost in {len(lost)} pattern(s); fix before running: {lost[:2]}")

    review_rows, back_jobs = [], []
    for lang in LANGS:
        rendered = []
        for q in questions:
            title_en = titles[q["bill_id"]]["en"]
            text = table[lang][pattern_for(q, title_en)].replace(PLACEHOLDER, titles[q["bill_id"]][lang])
            rendered.append({**q, "lang": lang, "instruction": table[lang][INSTRUCTION_EN],
                             "question": text, "options_local": [table[lang][o] for o in q["options"]]})
            back_jobs.append((text, lang, q["id"], q["question"]))
        (DATA / f"questions_{lang}.json").write_text(json.dumps(rendered, ensure_ascii=False, indent=1), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=6) as pool:
        backs = list(pool.map(lambda job: translate(job[0], "en-IN", source=job[1]), back_jobs))
    for (text, lang, qid, original), back in zip(back_jobs, backs):
        review_rows.append({"lang": lang, "question_id": qid, "english_original": original,
                            "translated": text, "back_translated": back})
    with (DATA / "translation_review.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(review_rows[0]))
        w.writeheader()
        w.writerows(review_rows)
    (DATA / "translation_table.json").write_text(json.dumps(table, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Wrote questions for {len(LANGS)} languages and {len(review_rows)} back-translations for review.")


if __name__ == "__main__":
    main()
