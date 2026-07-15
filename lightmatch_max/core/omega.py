"""Omega gateway client — the plugin's single network surface. Same hard-won wire
contract the web app runs on (verified live 2026-07-04 against the real gateway):
  - NO tools / tool_choice (the gateway 500s on them) — the JSON schema is embedded
    in the system prompt and the reply is parsed out of the TEXT blocks;
  - non-streaming; Bearer key; anthropic-version header;
  - retries with backoff on 429/5xx; ~100s wall-clock ceiling per attempt."""

from __future__ import annotations

import json
import time
from typing import Any, Optional

import requests

GATEWAY_URL = "https://omega.kesarcloud.in/v1/messages"
TIMEOUT_S = 120
BACKOFF_S = (2.0, 6.0, 15.0)
DEFAULT_MODEL = "claude-opus-4-8"


class OmegaError(RuntimeError):
    def __init__(self, message: str, kind: str = "other", raw: str = ""):
        super().__init__(message)
        self.kind = kind
        self.raw = raw


def extract_text(payload: dict) -> str:
    """Concatenate the text blocks of a well-formed Anthropic reply. Tolerates EVERY
    malformed 200 shape the third-party gateway might emit — a string/dict `content`, a
    list with non-dict items, or a non-string `text` — by degrading to '' (which routes
    into call()'s 'the model returned no text' → retry path) instead of raising an
    AttributeError/TypeError out of the un-guarded call site (omega.py audit 2026-07-16)."""
    blocks = payload.get("content")
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "text":
            t = b.get("text", "")
            if isinstance(t, str):
                parts.append(t)
    return "\n".join(parts).strip()


def parse_json_from_text(text: str, require: Optional[str] = None) -> Optional[dict]:
    """First balanced top-level {...} object in the reply (the model is instructed to
    output ONLY the JSON, but thinking spill / stray prose must not break parsing). When
    `require` is given, prefer the first object that CONTAINS that key — so a leading
    stray/thinking dict (e.g. `{"warm": true}`) can't shadow the real `{"values": [...]}`
    and make analyze report 'no recipe JSON' on a reply that DID carry one. Falls back to
    the first parseable object when none contains the key (omega.py audit 2026-07-16)."""
    fallback: Optional[dict] = None
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start : i + 1])
                        if isinstance(obj, dict):
                            if require is None or require in obj:
                                return obj
                            if fallback is None:
                                fallback = obj  # remember, keep scanning for a shape-valid one
                    except (json.JSONDecodeError, RecursionError, ValueError):
                        # untrusted model reply — deeply-nested JSON can raise RecursionError
                        # from json.loads; degrade to fallback (no recipe), never crash analyze
                        break
                    break
        start = text.find("{", start + 1)
    return fallback


def call(
    key: str,
    system: str,
    messages: list[dict],
    model: str = DEFAULT_MODEL,
    max_tokens: int = 8192,
) -> str:
    """One resilient gateway round; returns the reply TEXT. Raises OmegaError with a
    typed kind (auth | network | other) on failure."""
    if not key:
        raise OmegaError("No API key set — paste your oc_ key in LightMatch's settings.", "auth")
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "stream": False,
        "system": system,
        "messages": messages,
    }
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {key}",
        "anthropic-version": "2023-06-01",
    }
    last = "gateway request failed"
    for attempt in range(len(BACKOFF_S) + 1):
        try:
            res = requests.post(GATEWAY_URL, json=body, headers=headers, timeout=TIMEOUT_S)
        except requests.RequestException as e:
            last = f"network error: {e}"
            res = None
        if res is not None:
            if res.status_code == 401:
                raise OmegaError("Gateway returned 401 — the API key is missing or invalid.", "auth")
            if res.ok:
                try:
                    payload = res.json()
                except ValueError:
                    payload = {}
                text = extract_text(payload)
                if text:
                    return text
                last = "the model returned no text"
            elif res.status_code == 429 or 500 <= res.status_code <= 599:
                last = f"gateway HTTP {res.status_code}"
            else:
                raise OmegaError(
                    f"Gateway request failed: HTTP {res.status_code} — {res.text[:200]}",
                    "other",
                    res.text[:2000],
                )
        if attempt < len(BACKOFF_S):
            time.sleep(BACKOFF_S[attempt])
    raise OmegaError(last, "network")


def ping(key: str, model: str = DEFAULT_MODEL) -> str:
    """A minimal round-trip to confirm the key + network + omega wire work through the
    Python client, BEFORE committing to a full analyze. Returns a short OK string;
    raises OmegaError on auth/network/gateway failure (the diagnostic surfaces it)."""
    text = call(
        key,
        "Reply with exactly the two characters: OK",
        [{"role": "user", "content": "ping"}],
        model=model,
        max_tokens=16,
    )
    return f"gateway reachable ({model}): {text.strip()[:24]!r}"


def image_block(png_or_jpeg_b64: str, media_type: str = "image/png") -> dict[str, Any]:
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": png_or_jpeg_b64}}


def text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}
