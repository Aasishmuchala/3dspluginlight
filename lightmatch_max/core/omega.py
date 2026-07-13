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
    blocks = payload.get("content") or []
    return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()


def parse_json_from_text(text: str) -> Optional[dict]:
    """First balanced top-level {...} object in the reply (the model is instructed to
    output ONLY the JSON, but thinking spill / stray prose must not break parsing)."""
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
                            return obj
                    except json.JSONDecodeError:
                        break
                    break
        start = text.find("{", start + 1)
    return None


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


def image_block(png_or_jpeg_b64: str, media_type: str = "image/png") -> dict[str, Any]:
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": png_or_jpeg_b64}}


def text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}
