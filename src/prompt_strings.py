"""Translate the fixed prompt sentences into each language (sprint work).

The instruction reuses the translation made with the questions; the tool hint, context hint and reply
sentence are translated here. The JSON reply template itself stays as code in every language.
Output: data/prompt_strings.json
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sarvam import LANGS, translate  # noqa: E402
from translate_questions import INSTRUCTION_EN  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
EXTRA = {
    "tools_hint": "You can use the tools provided to look up current parliamentary data before answering.",
    "context_hint": "Here is the record for this bill from PRS Legislative Research:",
    "reply_sentence": "Reply with only this JSON and nothing else:",
}


def main() -> None:
    table = json.loads((DATA / "translation_table.json").read_text(encoding="utf-8"))
    out = {"en-IN": {"instruction": INSTRUCTION_EN, **EXTRA}}
    jobs = [(lang, key, text) for lang in LANGS for key, text in EXTRA.items()]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda j: translate(j[2], j[0]), jobs))
    for lang in LANGS:
        out[lang] = {"instruction": table[lang][INSTRUCTION_EN]}
    for (lang, key, _), text in zip(jobs, results):
        out[lang][key] = text
    (DATA / "prompt_strings.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Wrote prompt strings for {len(out)} languages")


if __name__ == "__main__":
    main()
