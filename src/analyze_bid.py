"""Analyse condition B-ID against B, as fixed in PROTOCOL_B_ID.md (sprint work).

Writes results/bid/effects.csv (paired changes with bill-clustered bootstrap intervals and leave-one-bill-out
ranges) and results/bid/mechanisms.csv (tool-trace measures). Usage: python src/analyze_bid.py
"""

from __future__ import annotations

import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import reparse  # noqa: E402
from sarvam import LANGS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "bid"
BOOT, SEED = 5000, 20261115
TARGETED = ("bill_timeline", "relevant_mps_for_bill")


def load(path: Path) -> dict:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        rows[(r["qid"], r["lang"], r["run"])] = reparse(r)
    return rows


def acc(rows):
    return sum(r["is_correct"] for r in rows) / len(rows) if rows else float("nan")


def rate(rows, key):
    return sum(bool(r[key]) for r in rows) / len(rows) if rows else float("nan")


def invented(rows):
    return sum(r["parsed"] and not r["is_idk"] and not r["is_correct"] for r in rows) / len(rows) if rows else float("nan")


def non_answer(rows):
    return sum(not r["parsed"] for r in rows) / len(rows) if rows else float("nan")


MEASURES = {"accuracy": acc, "idk_rate": lambda v: rate(v, "is_idk"), "invention_rate": invented, "non_answer_rate": non_answer}


def effects(pairs_by_bill: dict, bills: list[str]) -> dict:
    """All estimates for a (multi)set of bills. pairs_by_bill[bill] = list of (b_row, bid_row)."""
    pairs = [p for b in bills for p in pairs_by_bill[b]]
    out = {}
    for name, f in MEASURES.items():
        for group, sel in (("en-IN", lambda l: l == "en-IN"), ("indian_pooled", lambda l: l != "en-IN"),
                           *((l, (lambda x, l=l: x == l)) for l in LANGS)):
            sub = [(b, d) for b, d in pairs if sel(b["lang"])]
            if sub:
                out[(name, group)] = (f([b for b, _ in sub]), f([d for _, d in sub]))
    a = {g: out[("accuracy", g)] for g in ("en-IN", "mr-IN")}
    gap_b, gap_bid = a["mr-IN"][0] - a["en-IN"][0], a["mr-IN"][1] - a["en-IN"][1]
    out[("mr_minus_en_gap", "accuracy")] = (gap_b, gap_bid)
    return out


def main() -> None:
    b_rows = load(ROOT / "results" / "raw" / "B.jsonl")
    bid_rows = load(ROOT / "results" / "raw_bid" / "BID.jsonl")
    keys = sorted(set(b_rows) & set(bid_rows))
    print(f"Paired answers: {len(keys)} (B {len(b_rows)}, B-ID {len(bid_rows)})")
    pairs_by_bill = defaultdict(list)
    for k in keys:
        pairs_by_bill[b_rows[k]["bill_id"]].append((b_rows[k], bid_rows[k]))
    bills = sorted(pairs_by_bill)

    point = effects(pairs_by_bill, bills)
    rng = random.Random(SEED)
    boots = defaultdict(list)
    for _ in range(BOOT):
        e = effects(pairs_by_bill, rng.choices(bills, k=len(bills)))
        for k, (x, y) in e.items():
            boots[k].append(y - x)
    loo = defaultdict(list)
    for left_out in bills:
        for k, (x, y) in effects(pairs_by_bill, [b for b in bills if b != left_out]).items():
            loo[k].append(y - x)

    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for k, (x, y) in point.items():
        vals = sorted(v for v in boots[k] if v == v)
        rows.append({"measure": k[0], "group": k[1], "B": round(x, 4), "B_ID": round(y, 4), "change": round(y - x, 4),
                     "ci_lo": round(vals[int(0.025 * len(vals))], 4), "ci_hi": round(vals[int(0.975 * len(vals)) - 1], 4),
                     "loo_min": round(min(loo[k]), 4), "loo_max": round(max(loo[k]), 4)})
    write(OUT / "effects.csv", rows)

    mech = []
    for cond, data in (("B", b_rows), ("B-ID", bid_rows)):
        for group, sel in (("en-IN", lambda l: l == "en-IN"), ("indian_pooled", lambda l: l != "en-IN"), ("mr-IN", lambda l: l == "mr-IN")):
            v = [data[k] for k in keys if sel(data[k]["lang"])]
            targeted = [r for r in v if targeted_hit(r)]
            list_only = [r for r in v if not targeted_hit(r) and any(t["ok"] and t["tool"] == "list_bills" for t in r["tool_calls"])]
            mech.append({
                "condition": cond, "group": group, "n": len(v),
                "share_targeted_hit": round(len(targeted) / len(v), 4),
                "share_called_list_bills": round(sum(any(t["tool"] == "list_bills" for t in r["tool_calls"]) for r in v) / len(v), 4),
                "share_list_bills_only": round(len(list_only) / len(v), 4),
                "acc_when_targeted_hit": round(acc(targeted), 4) if targeted else "",
                "acc_when_list_bills_only": round(acc(list_only), 4) if list_only else "",
                "share_with_failed_call": round(sum(any(not t["ok"] for t in r["tool_calls"]) for r in v) / len(v), 4),
                "failed_calls_per_answer": round(sum(sum(not t["ok"] for t in r["tool_calls"]) for r in v) / len(v), 4),
                "tool_calls_per_answer": round(sum(len(r["tool_calls"]) for r in v) / len(v), 4),
                "no_tool_call": round(sum(not r["tool_calls"] for r in v) / len(v), 4),
            })
    write(OUT / "mechanisms.csv", mech)

    for r in rows:
        if r["group"] in ("en-IN", "indian_pooled", "mr-IN", "accuracy") or r["measure"] == "mr_minus_en_gap":
            print(r)
    for m in mech:
        print(m)


_DATA = None


def targeted_hit(r) -> bool:
    """A successful bill_timeline / relevant_mps_for_bill call that resolves to the question's bill."""
    global _DATA
    if _DATA is None:
        from parliament_mcp_india.data import ParliamentDataset
        _DATA = ParliamentDataset.load()
        _DATA.cv = {b.get("citizenview_id"): b["id"] for b in _DATA.bills}
    for t in r["tool_calls"]:
        if t["ok"] and t["tool"] in TARGETED and isinstance(t["args"], dict):
            b = _DATA.find_bill(str(t["args"].get("bill", "")))
            if b and b["id"] == _DATA.cv[r["bill_id"]]:
                return True
    return False


def write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
