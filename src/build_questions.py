"""Build the English question set with answers taken from PRS-sourced data (sprint work).

Inputs are preexisting CitizenView / Parliament MCP snapshots in data/. Output: data/questions_en.json.
Every correct answer comes from PRS timelines or PRS committee pages, never from AI-written briefs.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
SEED = 20261113
IDK = "I don't know"


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def month_label(d: datetime) -> str:
    return d.strftime("%B %Y")


def shift_month(d: datetime, months: int) -> datetime:
    m = d.month - 1 + months
    return d.replace(year=d.year + m // 12, month=m % 12 + 1, day=1)


def build() -> list[dict]:
    rng = random.Random(SEED)
    timelines = {r["id"]: r for r in load("bill-timelines.json")["records"] if r.get("eligible") and r.get("id")}
    mps = load("bill-mps.json")["bills"]
    titles = load("bill_titles.json")
    parliament = load("parliament.json")
    current = [c for c in parliament["committees"] if c.get("current") and c.get("chair")]
    chair_pool = sorted({c["chair"]["name"] for c in current if c["chair"].get("name")})
    today = datetime.strptime(parliament["retrieved_on"], "%Y-%m-%d")
    committee_types = {
        "Standing Committee": "A departmental standing committee",
        "Joint Committee": "A joint committee of both Houses",
        "Select Committee": "A select committee of one House",
    }
    not_referred = "It has not been referred to any committee"

    questions = []
    for bill_id, tl in timelines.items():
        title = titles[bill_id]["en"]
        intro = next(e for e in tl["events"] if e["stage"] == "Introduced")
        intro_date = datetime.strptime(intro["date"], "%b %d, %Y")
        committee = mps[bill_id]["committees"][0]
        chair = next(m["name"] for m in committee["members"] if m["is_chair"])
        reported = any(e["stage"] == "Report" for e in tl["events"])
        source = tl["url"]

        def q(kind, text, correct, distractors, note=""):
            options = [correct] + distractors
            rng.shuffle(options)
            questions.append({
                "id": f"{bill_id}:{kind}", "bill_id": bill_id, "kind": kind, "question": text,
                "options": options + [IDK], "correct": correct, "source": source, "note": note,
            })

        q("house", f"In which house of India's Parliament was {title} introduced?",
          intro["chamber"], ["Rajya Sabha" if intro["chamber"] == "Lok Sabha" else "Lok Sabha"])

        # Wrong months stay in the past, so none can be ruled out just for being in the future.
        offsets = [o for o in [-12, -9, -6, -4, -3, -2, 2, 3, 4, 6] if shift_month(intro_date, o) <= today]
        q("introduced", f"In which month and year was {title} introduced in Parliament?",
          month_label(intro_date), [month_label(shift_month(intro_date, o)) for o in rng.sample(offsets, 3)])

        # Asking the committee's type avoids answers that just repeat the bill's own title.
        correct_type = committee_types[committee["type"]]
        q("committee_type", f"What kind of parliamentary committee is examining {title}?",
          correct_type, [t for t in list(committee_types.values()) + [not_referred] if t != correct_type])

        q("chair", f"Who chairs the parliamentary committee that is examining {title}?",
          chair, rng.sample([c for c in chair_pool if c != chair], 3))

        q("report", f"Has the parliamentary committee examining {title} submitted its report yet?",
          "Yes" if reported else "No", ["No" if reported else "Yes"])

        not_yet = "It has not received the President's assent; no such date exists yet"
        # Fake assent dates fall between introduction and today, so they are plausible past dates.
        span = (today - intro_date).days
        fake = sorted({(intro_date + timedelta(days=rng.randint(30, max(31, span - 1)))).strftime("%-d %B %Y")
                       for _ in range(6)})[:3]
        q("assent", f"On what date did {title} receive the President's assent and become law?",
          not_yet, fake, note="Trap question: the bill is still pending, so any specific date is invented.")
    return questions


if __name__ == "__main__":
    qs = build()
    (DATA / "questions_en.json").write_text(json.dumps(qs, ensure_ascii=False, indent=1), encoding="utf-8")
    kinds = {}
    for item in qs:
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
    print(f"{len(qs)} questions across {len({x['bill_id'] for x in qs})} bills:", kinds)
