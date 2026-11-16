"""Run the multilingual civic-epistemics evaluation (sprint work).

Conditions (same model, same questions, only language and information access change):
  A  memory only: no tools, no context
  B  with the Parliament MCP: the model can call its tools through a real MCP client session
  C  record in context: the bill's PRS record (the same data the MCP returns) pasted into the prompt
  BID  B plus one line after the question giving the bill's canonical PRS ID (added after the main results;
       protocol frozen in PROTOCOL_B_ID.md before it ran)

Usage:
  python src/run_eval.py --condition A [--langs en-IN,hi-IN] [--runs 3] [--limit 6]
Results append to results/raw/<condition>.jsonl. A rerun asks only questions not yet answered (or that came back
empty or failed); analysis uses the latest row for each (question, language, run).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sarvam import LANGS, chat  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA, RAW = ROOT / "data", ROOT / "results" / "raw"
MODEL = "sarvam-105b"
MAX_TOOL_ROUNDS = 6
MAX_TOKENS = 8000  # the model reasons before answering; ~2,200 tokens per answer in the pilot
ALL_LANGS = ["en-IN"] + LANGS


def prs_ids() -> dict[str, str]:
    """CitizenView bill id -> canonical PRS bill id, from the same MCP dataset the tools serve."""
    from parliament_mcp_india.data import ParliamentDataset
    return {b["citizenview_id"]: b["id"] for b in ParliamentDataset.load().bills if b.get("citizenview_id")}


def load_questions(lang: str) -> list[dict]:
    extra = json.loads((DATA / "prompt_strings.json").read_text(encoding="utf-8"))[lang]
    extra = {**extra, **json.loads((DATA / "prompt_strings_bid.json").read_text(encoding="utf-8"))[lang]}
    if lang == "en-IN":
        qs = json.loads((DATA / "questions_en.json").read_text(encoding="utf-8"))
        qs = [{**q, "lang": "en-IN", "options_local": q["options"]} for q in qs]
    else:
        qs = json.loads((DATA / f"questions_{lang}.json").read_text(encoding="utf-8"))
    return [{**q, "instruction": extra["instruction"], "strings": extra} for q in qs]


def option_order(qid: str, run: int, n_real: int) -> list[int]:
    """Same permutation for every language: depends only on the question and the run."""
    order = list(range(n_real))
    if run > 0:
        random.Random(f"{qid}|{run}").shuffle(order)
    return order + [n_real]  # "I don't know" always last


def build_prompt(q: dict, run: int, condition: str, context: str | None) -> tuple[str, list[int]]:
    order = option_order(q["id"], run, len(q["options"]) - 1)
    lines = [q["instruction"]]
    if condition in ("B", "BID"):
        lines.append(q["strings"]["tools_hint"])
    if condition == "C":
        lines += [q["strings"]["context_hint"], context]
    lines += ["", q["question"]]
    if condition == "BID":
        lines.append(f'{q["strings"]["bill_id_label"]} {context}')
    lines += [f"{i + 1}. {q['options_local'][j]}" for i, j in enumerate(order)]
    lines += ["", q["strings"]["reply_sentence"] + ' {"choice": <option number>, "confidence": <0-100>}']
    return "\n".join(lines), order


def _number(value) -> float | None:
    """Read a number written in any script's digits (the model sometimes answers in Devanagari or Malayalam digits)."""
    text = "".join(str(unicodedata.digit(ch)) if ch.isdigit() else ch for ch in str(value)).strip()
    try:
        return float(text)
    except ValueError:
        return None


def parse_reply(text: str | None, order: list[int]) -> tuple[int | None, float | None]:
    if not text:
        return None, None
    # Native-script digits are often unquoted ({"choice": ২}), which is invalid JSON until converted.
    text = "".join(str(unicodedata.digit(ch)) if ch.isdigit() and not ch.isascii() else ch for ch in text)
    for match in re.finditer(r"\{[^{}]*\}", text):
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        # Keys are sometimes translated, so fall back to position: first value is the choice, second the confidence.
        values = list(obj.values())
        choice = _number(obj.get("choice", values[0] if values else ""))
        conf = _number(obj.get("confidence", values[1] if len(values) > 1 else ""))
        if choice is not None and choice == int(choice) and 1 <= choice <= len(order):
            return order[int(choice) - 1], None if conf is None else max(0.0, min(100.0, conf))
    # Fallback for near-JSON (Arabic comma "،", curly quotes, escaped quotes): the last {...} with numbers in it,
    # read as choice then confidence.
    for match in reversed(list(re.finditer(r"\{[^{}]*\}", text))):
        nums = re.findall(r"(?<![\w.])\d+(?:\.\d+)?", match.group(0))
        if nums and float(nums[0]) == int(float(nums[0])) and 1 <= int(float(nums[0])) <= len(order):
            conf = float(nums[1]) if len(nums) > 1 else None
            return order[int(float(nums[0])) - 1], None if conf is None else max(0.0, min(100.0, conf))
    return None, None


def record(q, run, condition, order, reply, idx, conf, usage, tool_calls, elapsed, error=None, finish=None) -> dict:
    n_real = len(q["options"]) - 1
    chosen = q["options"][idx] if idx is not None else None
    return {
        "condition": condition, "lang": q["lang"], "run": run, "qid": q["id"], "kind": q["kind"],
        "bill_id": q["bill_id"], "correct": q["correct"], "chosen": chosen,
        "is_correct": chosen == q["correct"], "is_idk": idx == n_real, "parsed": idx is not None,
        "confidence": conf, "order": order, "reply": reply, "usage": usage,
        "tool_calls": tool_calls, "seconds": round(elapsed, 1), "error": error, "finish_reason": finish, "model": MODEL,
    }


def contexts() -> dict[str, str]:
    """The PRS record per bill, built from the same MCP dataset the tools serve."""
    from parliament_mcp_india.data import ParliamentDataset
    d = ParliamentDataset.load()
    out = {}
    for b in d.bills:
        if not b.get("citizenview_id"):
            continue
        tl = d.bill_timeline(b["id"])
        mps = d.relevant_mps_for_bill(b["id"])
        c = mps["committees"][0] if mps["committees"] else None
        out[b["citizenview_id"]] = json.dumps({
            "bill": b["title"], "status": tl["status"], "timeline": tl["timeline"],
            "committee": {"name": c["name"], "type": c["type"], "chair": c["chair"]} if c else None,
            "source": "PRS Legislative Research, retrieved " + d.retrieved_on,
        }, ensure_ascii=False)
    return out


# ---------- conditions A and C (no tools) ----------

def ask_plain(q, run, condition, ctx) -> dict:
    prompt, order = build_prompt(q, run, condition, ctx)
    start = time.time()
    try:
        res = chat([{"role": "user", "content": prompt}], MODEL, MAX_TOKENS)
        msg = res["choices"][0]["message"]
        idx, conf = parse_reply(msg.get("content"), order)
        return record(q, run, condition, order, msg.get("content"), idx, conf, res.get("usage"), [], time.time() - start,
                      finish=res["choices"][0].get("finish_reason"))
    except Exception as e:  # recorded, not silently dropped
        return record(q, run, condition, order, None, None, None, None, [], time.time() - start, error=str(e)[:300])


# ---------- condition B (real MCP session) ----------

async def ask_with_mcp(session, tools, q, run, condition="B", prs_id=None) -> dict:
    prompt, order = build_prompt(q, run, condition, prs_id)
    messages = [{"role": "user", "content": prompt}]
    calls, usage_total, start = [], {"prompt_tokens": 0, "completion_tokens": 0}, time.time()
    try:
        for _ in range(MAX_TOOL_ROUNDS + 1):
            res = await asyncio.to_thread(chat, messages, MODEL, MAX_TOKENS, 0.0, tools)
            for k in usage_total:
                usage_total[k] += (res.get("usage") or {}).get(k) or 0
            msg = res["choices"][0]["message"]
            if not msg.get("tool_calls"):
                idx, conf = parse_reply(msg.get("content"), order)
                return record(q, run, condition, order, msg.get("content"), idx, conf, usage_total, calls, time.time() - start,
                              finish=res["choices"][0].get("finish_reason"))
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": msg["tool_calls"]})
            for tc in msg["tool_calls"]:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                    result = await session.call_tool(name, args)
                    text = "\n".join(getattr(c, "text", "") for c in result.content)
                    ok = not result.is_error
                except Exception as e:
                    args, text, ok = tc["function"].get("arguments"), f"Tool error: {e}", False
                calls.append({"tool": name, "args": args, "ok": ok})
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": text[:12000] or "(no result)"})
        return record(q, run, condition, order, None, None, None, usage_total, calls, time.time() - start, error="too many tool rounds")
    except Exception as e:
        return record(q, run, condition, order, None, None, None, usage_total, calls, time.time() - start, error=str(e)[:300])


async def run_mcp(jobs, out_path, workers, condition="B"):
    from mcp import ClientSession, StdioServerParameters, stdio_client
    params = StdioServerParameters(command=sys.executable, args=["-m", "parliament_mcp_india"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                                       "parameters": t.input_schema}}
                     for t in (await session.list_tools()).tools]
            sem, lock, done = asyncio.Semaphore(workers), threading.Lock(), [0]
            ids = prs_ids() if condition == "BID" else {}

            async def one(q, run):
                async with sem:
                    row = await ask_with_mcp(session, tools, q, run, condition, ids.get(q["bill_id"]))
                with lock, out_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    done[0] += 1
                    if done[0] % 25 == 0:
                        print(f"  {done[0]}/{len(jobs)}", flush=True)
            await asyncio.gather(*(one(q, run) for q, run in jobs))


# ---------- driver ----------

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--condition", choices=["A", "B", "C", "BID"], required=True)
    p.add_argument("--langs", default="all")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--limit", type=int, default=0, help="questions per language (0 = all); for pilots")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--out", default="")
    args = p.parse_args()

    langs = ALL_LANGS if args.langs == "all" else args.langs.split(",")
    out_path = Path(args.out) if args.out else RAW / f"{args.condition}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if not r.get("error") and r.get("reply"):  # only failed or empty answers are asked again
                done.add((r["qid"], r["lang"], r["run"]))

    jobs = []
    for lang in langs:
        qs = load_questions(lang)
        if args.limit:
            qs = qs[: args.limit]
        jobs += [(q, run) for run in range(args.runs) for q in qs if (q["id"], lang, run) not in done]
    print(f"Condition {args.condition}: {len(jobs)} questions to ask ({len(done)} already done)", flush=True)
    if not jobs:
        return

    if args.condition in ("B", "BID"):
        asyncio.run(run_mcp(jobs, out_path, args.workers, args.condition))
    else:
        ctx = contexts() if args.condition == "C" else {}
        lock, count = threading.Lock(), [0]

        def task(job):
            q, run = job
            row = ask_plain(q, run, args.condition, ctx.get(q["bill_id"]))
            with lock, out_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                count[0] += 1
                if count[0] % 25 == 0:
                    print(f"  {count[0]}/{len(jobs)}", flush=True)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(task, jobs))
    print("Done.", flush=True)


if __name__ == "__main__":
    main()
