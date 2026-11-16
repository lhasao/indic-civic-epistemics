# Protocol: condition B-ID (frozen before the run)

Sprint work, 15 November 2026. Written and frozen before any B-ID answer was collected. Its SHA-256 and the
analysis script's, with the time, are in `results/logs/bid_freeze.txt`. During the run, only operational
counts (errors, non-answers) are checked. No correctness is looked at until the run is complete.

## Why

In condition B (Parliament MCP), Marathi accuracy was 10 points below English (86% vs. 97%). With the record
pasted in (C), there was no gap. The tool traces show that B almost always had every bill's full record in
context, via `list_bills`. So one explanation is that, when the question is in another language, the model
struggles to identify which English record the question is about. B-ID tests this by giving the model the
bill's canonical PRS ID, removing the need to identify the bill.

## What changes, and what does not

- **Only change:** one line after the question: `<label> <PRS bill id>`. For example, in English:
  `PRS bill ID: the-pesticide-management-bill-2020`. This is added in every language, English included.
  - The label is translated by Sarvam (`data/prompt_strings_bid.json`), and every label back-translates to
    "PRS Bill ID:".
  - The ID is the Latin slug the tools accept.
- **Unchanged from B:**
  - model `sarvam-105b`, temperature 0, max_tokens 8000
  - the instruction, tools hint, translated questions, options and reply line
  - the option permutations, seeded by (question, run)
  - the 3 runs, 12 languages and 54 questions, so 1,944 answers
  - the 8 MCP tools, through the same stdio client, with at most 6 tool rounds
- **ID check (done before freezing):** through a real MCP session, all 9 PRS IDs:
  - appear in the `list_bills` records
  - are accepted by `bill_timeline` and `relevant_mps_for_bill`, each returning the right bill
- **Source snapshot:** `parliament-mcp-india` at `ac79744`, a clean tree. The dataset is
  `parliament.json`, SHA-256 `5afb0a02c82c218091537859e9cb769d643d6bc1d0cd4df284f6c583335e8675`, dated
  13 Nov 22:03, the same file B used.
- **Original results kept:**
  - `results/raw/{A,B,C}.jsonl` are set read-only.
  - B-ID writes to `results/raw_bid/BID.jsonl`.
- **A difference that cannot be controlled:** B ran on 13–14 Nov and B-ID runs on 15 Nov. The API serves the
  same model name, but the provider could have changed the model in between.

## Analysis (fixed now; `src/analyze_bid.py`)

- **Scoring:** the current parser, the same one used for the main results, applied to the stored replies.
  Non-answers count as not correct and are reported separately. Nothing is excluded.
- **Pairing:** B and B-ID answers are matched on (question, language, run).
- **Primary outcomes:**
  1. The change in accuracy (B-ID minus B), pooled over the 11 Indian languages.
  2. The change in the Marathi–English accuracy gap:
     [acc(mr, B-ID) − acc(en, B-ID)] − [acc(mr, B) − acc(en, B)].
- **Secondary outcomes:**
  - the change in accuracy for each language and for English
  - the change in the "I don't know" rate (pooled and per language)
  - the change in non-answers and in invented answers
- **Uncertainty:** a cluster bootstrap over the 9 bills (5,000 resamples, percentile 95% intervals), with all
  questions, languages and runs of a bill moving together. As a sensitivity check, the range of each primary
  estimate when one bill at a time is left out. Nine bills give limited precision; wide intervals are
  expected and will be reported as such.
- **Tool traces:** these separate the possible explanations for any change. They are descriptive, compared
  B vs. B-ID for English and pooled over the Indian languages.
  - **Selection within the full list:** among answers whose only bill data came from `list_bills` (no
    successful targeted call for the right bill), accuracy in B vs. B-ID.
  - **Redirect to targeted tools:** the share of answers with at least one successful `bill_timeline` or
    `relevant_mps_for_bill` call for the right bill, and the share that call `list_bills`.
  - **Fewer failed calls:** the share of answers with at least one failed tool call, and failed calls per
    answer.
  - These groups are not randomised. A difference within a group is a description, not a causal effect.
- **Interpretation, fixed in advance:**
  - If the Marathi–English gap shrinks and its interval excludes zero: giving the ID reduces the gap, which
    is consistent with bill identification as a source.
  - If the interval includes zero: no clear evidence either way, given 9 bills.
  - The tool traces say which explanation, if any, the change goes with. Nothing is claimed beyond that.
