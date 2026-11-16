"""Analyse the evaluation results (sprint work).

Reads results/raw/<condition>.jsonl, keeps the latest row for each (question, language, run), and writes:
  results/summary.csv          one row per condition x language, with bootstrap 95% intervals
  results/by_kind.csv          the same measures per question type
  results/gap_vs_english.csv   each language's difference from English (paired over questions)
  results/fig_*.png            figures for the report
Usage: python src/analyze.py
"""

from __future__ import annotations

import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_eval import parse_reply  # noqa: E402
from sarvam import LANGS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "results" / "raw", ROOT / "results"
ALL_LANGS = ["en-IN"] + LANGS
BOOT, SEED = 2000, 20261113
OPTIONS = {q["id"]: q["options"] for q in json.loads((ROOT / "data" / "questions_en.json").read_text(encoding="utf-8"))}


def load() -> list[dict]:
    rows = {}
    for path in sorted(RAW.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            rows[(r["condition"], r["qid"], r["lang"], r["run"])] = r  # latest wins
    return [reparse(r) for r in rows.values()]


def reparse(r: dict) -> dict:
    """Score every stored reply with the current parser, so parser fixes apply without asking the model again."""
    q_opts = OPTIONS[r["qid"]]
    idx, conf = parse_reply(r["reply"], r["order"])
    chosen = q_opts[idx] if idx is not None else None
    return {**r, "chosen": chosen, "confidence": conf, "parsed": idx is not None,
            "is_correct": chosen == r["correct"], "is_idk": idx == len(q_opts) - 1}


def measures(rows: list[dict]) -> dict:
    """Measures over a set of answers. Calibration uses substantive answers only (not "I don't know")."""
    n = len(rows)
    if not n:
        return {}
    answered = [r for r in rows if r["parsed"] and not r["is_idk"]]
    wrong = [r for r in answered if not r["is_correct"]]
    trap = [r for r in rows if r["kind"] == "assent"]
    calib = [(r["confidence"] / 100, 1.0 if r["is_correct"] else 0.0) for r in answered if r["confidence"] is not None]
    out = {
        "n": n,
        "accuracy": sum(r["is_correct"] for r in rows) / n,
        "idk_rate": sum(r["is_idk"] for r in rows) / n,
        "invention_rate": len(wrong) / n,
        "non_answer_rate": sum(not r["parsed"] for r in rows) / n,
        "trap_invention": (sum(r["parsed"] and not r["is_idk"] and not r["is_correct"] for r in trap) / len(trap)) if trap else None,
        "brier": (sum((p - y) ** 2 for p, y in calib) / len(calib)) if calib else None,
        "ece": ece(calib),
        "conf_when_wrong": (sum(r["confidence"] for r in wrong if r["confidence"] is not None)
                            / max(1, sum(r["confidence"] is not None for r in wrong))) if wrong else None,
        "conf_on_idk": mean([r["confidence"] for r in rows if r["is_idk"] and r["confidence"] is not None]),
    }
    if rows[0]["condition"] == "B":
        out["used_tools"] = sum(bool(r["tool_calls"]) for r in rows) / n
    return out


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def ece(pairs, bins=10):
    if not pairs:
        return None
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        group = [(p, y) for p, y in pairs if lo <= p < hi or (b == bins - 1 and p == 1.0)]
        if group:
            total += len(group) / len(pairs) * abs(mean([p for p, _ in group]) - mean([y for _, y in group]))
    return total


def bootstrap(rows, key, rng):
    """95% interval, resampling questions (all runs of a question move together)."""
    by_q = defaultdict(list)
    for r in rows:
        by_q[r["qid"]].append(r)
    qids = list(by_q)
    vals = []
    for _ in range(BOOT):
        sample = [r for q in rng.choices(qids, k=len(qids)) for r in by_q[q]]
        v = measures(sample).get(key)
        if v is not None:
            vals.append(v)
    if not vals:
        return None, None
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def consistency(rows):
    """Share of answers matching English for the same question and run; and share of questions answered the same in every run."""
    idx = {(r["condition"], r["qid"], r["lang"], r["run"]): r for r in rows}
    out = {}
    for (cond, lang) in {(r["condition"], r["lang"]) for r in rows}:
        mine = [r for r in rows if r["condition"] == cond and r["lang"] == lang and r["parsed"]]
        pairs = [(r, idx.get((cond, r["qid"], "en-IN", r["run"]))) for r in mine]
        pairs = [(a, b) for a, b in pairs if b and b["parsed"]]
        same_as_en = mean([a["chosen"] == b["chosen"] for a, b in pairs]) if lang != "en-IN" else None
        by_q = defaultdict(set)
        for r in mine:
            by_q[r["qid"]].add(r["chosen"])
        stable = mean([len(v) == 1 for v in by_q.values()])
        out[(cond, lang)] = {"same_as_english": same_as_en, "stable_across_runs": stable}
    return out


def fmt(v):
    return "" if v is None else round(v, 4)


def main() -> None:
    rows = load()
    rng = random.Random(SEED)
    conds = sorted({r["condition"] for r in rows})
    cons = consistency(rows)
    keys = ["accuracy", "idk_rate", "invention_rate", "trap_invention", "brier", "ece", "conf_when_wrong"]

    summary = []
    for c in conds:
        for lang in ALL_LANGS:
            sub = [r for r in rows if r["condition"] == c and r["lang"] == lang]
            if not sub:
                continue
            m = measures(sub)
            row = {"condition": c, "lang": lang, **{k: fmt(v) for k, v in m.items()}, **{k: fmt(v) for k, v in cons[(c, lang)].items()}}
            for k in ("accuracy", "invention_rate", "idk_rate"):
                lo, hi = bootstrap(sub, k, rng)
                row[f"{k}_lo"], row[f"{k}_hi"] = fmt(lo), fmt(hi)
            summary.append(row)
    write_csv(OUT / "summary.csv", summary)

    by_kind = []
    for c in conds:
        for lang in ALL_LANGS:
            for kind in sorted({r["kind"] for r in rows}):
                sub = [r for r in rows if r["condition"] == c and r["lang"] == lang and r["kind"] == kind]
                if sub:
                    by_kind.append({"condition": c, "lang": lang, "kind": kind, **{k: fmt(v) for k, v in measures(sub).items()}})
    write_csv(OUT / "by_kind.csv", by_kind)

    gaps = []
    for c in conds:
        en = {(r["qid"], r["run"]): r for r in rows if r["condition"] == c and r["lang"] == "en-IN"}
        for lang in LANGS:
            pairs = [(r, en[(r["qid"], r["run"])]) for r in rows
                     if r["condition"] == c and r["lang"] == lang and (r["qid"], r["run"]) in en]
            if not pairs:
                continue
            for k in ("accuracy", "invention_rate"):
                gap, lo, hi = paired_gap(pairs, k, rng)
                gaps.append({"condition": c, "lang": lang, "measure": k, "minus_english": fmt(gap), "lo": fmt(lo), "hi": fmt(hi)})
    write_csv(OUT / "gap_vs_english.csv", gaps)

    figures(rows, summary, conds)
    for line in summary:
        print(line["condition"], line["lang"], {k: line.get(k) for k in keys})


def paired_gap(pairs, key, rng):
    by_q = defaultdict(list)
    for a, b in pairs:
        by_q[a["qid"]].append((a, b))
    qids = list(by_q)

    def diff(ps):
        ma, mb = measures([a for a, _ in ps]), measures([b for _, b in ps])
        return ma[key] - mb[key]

    point = diff(pairs)
    vals = sorted(diff([p for q in rng.choices(qids, k=len(qids)) for p in by_q[q]]) for _ in range(BOOT))
    return point, vals[int(0.025 * BOOT)], vals[int(0.975 * BOOT) - 1]


def write_csv(path, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def figures(rows, summary, conds):
    langs = [l for l in ALL_LANGS if any(s["lang"] == l for s in summary)]
    labels = [l.split("-")[0] for l in langs]
    for key, title in (("accuracy", "Accuracy"), ("invention_rate", "Invented answers (wrong, not \"I don't know\")"),
                       ("idk_rate", "\"I don't know\" rate")):
        fig, ax = plt.subplots(figsize=(10, 3.6))
        width = 0.8 / max(1, len(conds))
        for i, c in enumerate(conds):
            vals, err = [], [[], []]
            for l in langs:
                s = next((s for s in summary if s["condition"] == c and s["lang"] == l), None)
                v = s[key] if s and s[key] != "" else 0
                vals.append(v)
                err[0].append(max(0, v - (s.get(f"{key}_lo") or v)) if s else 0)
                err[1].append(max(0, (s.get(f"{key}_hi") or v) - v) if s else 0)
            xs = [j + (i - (len(conds) - 1) / 2) * width for j in range(len(langs))]
            ax.bar(xs, vals, width, yerr=err, capsize=2, label={"A": "A memory only", "B": "B with MCP", "C": "C record in prompt"}[c])
        ax.set_xticks(range(len(langs)), labels)
        ax.set_ylim(0, 1)
        ax.set_title(title)
        ax.legend(fontsize=8, ncol=3)
        fig.tight_layout()
        fig.savefig(OUT / f"fig_{key}.png", dpi=200)
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(4.5, 4.5))
    ax.plot([0, 1], [0, 1], ls="--", c="grey", lw=1)
    for c in conds:
        for group, sel in (("English", lambda l: l == "en-IN"), ("Indian languages", lambda l: l != "en-IN")):
            pairs = [(r["confidence"] / 100, r["is_correct"]) for r in rows if r["condition"] == c and sel(r["lang"])
                     and r["parsed"] and not r["is_idk"] and r["confidence"] is not None]
            pts = []
            for b in range(10):
                g = [(p, y) for p, y in pairs if b / 10 <= p < (b + 1) / 10 or (b == 9 and p == 1.0)]
                if len(g) >= 5:
                    pts.append((mean([p for p, _ in g]), mean([y for _, y in g])))
            if pts:
                ax.plot(*zip(*pts), marker="o", ls="-" if group == "English" else ":", label=f"{c} {group}")
    ax.set_xlabel("Stated confidence")
    ax.set_ylabel("Share correct")
    ax.set_title("Calibration (substantive answers)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "fig_calibration.png", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    main()
