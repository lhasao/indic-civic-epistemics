# Indic Civic Epistemics

Apart Research AI x Epistemics Sprint, 13–15 November 2026 · Track 1 (Model Epistemics & Decision-Making Evals)

**Question:** when one AI model is asked the same factual questions about live Indian bills in English and
11 Indian languages, does it stay equally accurate, admit what it doesn't know, avoid inventing answers, and
give confidence that matches how often it is right? And does access to a sourced data tool (an MCP server)
close any gap between languages?

## Preexisting work vs. sprint work

As the sprint rules require, everything built before the sprint is marked preexisting. Sprint work started at
**21:43 IST, 13 November 2026**, when this repository was created. Times below are commit timestamps (IST).

### Preexisting (built before the sprint; not sprint work)

| Component | What it is | Evidence |
| --- | --- | --- |
| CitizenView website and pipeline | Plain-language briefs of live Indian bills from PRS Legislative Research, AI-structured English briefs, and Sarvam translations into 11 Indian languages | Repo `lhasao/research-app`; e.g. `87a4086` (shared English source, 14 Sep 2026), `0af3065` (25 Sep 2026) |
| Bill timelines | PRS stage history for each tracked bill (`data/bill-timelines.json`) | `c842e6d`, 24 Sep 2026 |
| Translated bill titles | CitizenView's stored titles in 11 languages (`data/bill_titles.json`, a read-only snapshot of existing database records, taken during the sprint) | Translations created in July–Sep 2026 |
| Committee MPs on bill pages | `data/bill-mps.json` | `8aa9654`, 13 Nov 2026 15:26 |
| Organisation positions | Checked public positions on each bill (not used in this study) | `4924c96`, 13 Nov 2026 16:27 |
| Parliament MCP (India) | MCP server with India's current MPs, committees and bill-committee links from PRS (`github.com/lhasao/parliament-mcp-india`, `main` branch); `data/parliament.json` is its dataset | `e6866d1`–`fa02bcf`, 13 Nov 2026 17:55–18:28 |
| Translation-drift eval design | Design notes in CitizenView `src/evals/PLAN.md` (not implemented before the sprint) | `8c20b9d`, 26 Aug 2026 |

### Sprint work (13–15 November 2026)

| Component | Where |
| --- | --- |
| Question set with PRS-sourced answers, plausible distractors and a trap question | `src/build_questions.py`, `data/questions_en.json` |
| Translation of the one fixed English questionnaire into 11 languages, plus back-translation for quality review | `src/translate_questions.py`, `src/sarvam.py`, `data/questions_<lang>.json`, `data/translation_review.csv` |
| `bill_timeline` tool added to the Parliament MCP | `parliament-mcp-india`, branch `sprint/bill-timeline-tool`, commit `4af73de` (13 Nov 2026 22:03) |
| Evaluation harness (memory-only, with-MCP, and record-in-context conditions) and analysis | `src/run_eval.py`, `src/analyze.py`, results in `results/` |
| Follow-up condition B-ID (MCP plus the bill's PRS ID), protocol frozen before the run (15 Nov 2026 13:49 IST) | `PROTOCOL_B_ID.md`, `src/analyze_bid.py`, `results/raw_bid/`, `results/bid/`, hashes in `results/logs/bid_freeze.txt` |

## Design

- **Control:** one model (Sarvam `sarvam-105b`), one fixed English questionnaire translated into each language,
  one answer key. Only the language changes. Each question is asked in 3 runs with option order reshuffled the
  same way for every language.
- **Answer key:** taken only from PRS-sourced data (bill timelines and PRS committee pages), never from AI-written briefs.
- **Questions (54 = 6 per bill × 9 bills):** house of introduction, month introduced, committee type, committee
  chair, whether the committee has reported, and a trap question asking for an assent date that doesn't exist.
- **Scoring:** multiple choice with lettered options and an explicit "I don't know" option, plus a 0–100
  confidence, so answers are scored by code identically in every language, with no AI grader.
- **Conditions:** A — memory only; B — with the Parliament MCP; C — the relevant PRS record pasted into the prompt;
  B-ID — B plus the bill's canonical PRS ID.

## Reproduce

Python 3.12, `pip install python-dotenv matplotlib mcp` and the Parliament MCP (`parliament-mcp-india`,
branch `sprint/bill-timeline-tool`), plus a `SARVAM_API_KEY`. Then `python src/run_eval.py --condition A`
(and B, C, BID with `--out results/raw_bid/BID.jsonl`), `python src/analyze.py`, `python src/analyze_bid.py`.

## Data and attribution

Bill data and answer key: PRS Legislative Research (prsindia.org), used under CC BY 4.0.

## Known limitations (also in the report)

- Questions are machine-translated by Sarvam, the same company whose model is tested. Hindi and Malayalam are
  reviewed by a native reader; other languages are checked by back-translation only.
- 9 bills is a small sample; results describe these bills and this model.
