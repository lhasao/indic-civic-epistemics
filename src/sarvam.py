"""Minimal Sarvam API client: translation and chat (sprint work)."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # a local .env with SARVAM_API_KEY
load_dotenv(Path.home() / "Documents" / "citizenview" / ".env")  # the author's setup
KEY = os.environ["SARVAM_API_KEY"]
LANGS = ["hi-IN", "bn-IN", "ta-IN", "te-IN", "mr-IN", "kn-IN", "gu-IN", "ml-IN", "pa-IN", "od-IN", "ur-IN"]


def _post(url: str, body: dict, timeout: int = 120) -> dict:
    for attempt in range(5):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"api-subscription-key": KEY, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return json.loads(res.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:200]
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"Sarvam HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError):
            if attempt < 4:
                time.sleep(5 * (attempt + 1))
                continue
            raise
    raise RuntimeError("unreachable")


def translate(text: str, target: str, source: str = "en-IN") -> str:
    out = _post("https://api.sarvam.ai/translate", {
        "input": text, "source_language_code": source, "target_language_code": target,
        "model": "sarvam-translate:v1", "mode": "formal",
    })
    result = out.get("translated_text")
    if not isinstance(result, str) or not result.strip():
        raise RuntimeError(f"Empty translation for {target}")
    return result.strip()


def chat(messages: list[dict], model: str = "sarvam-105b", max_tokens: int = 2500, temperature: float = 0.0,
         tools: list[dict] | None = None) -> dict:
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if tools:
        body["tools"], body["tool_choice"] = tools, "auto"
    return _post("https://api.sarvam.ai/v1/chat/completions", body, timeout=240)
