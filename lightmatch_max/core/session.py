"""Session state + persistence — one JSON file per session under
%LOCALAPPDATA%/LightMatchMax/sessions. Mirrors the web app's shapes (recipe,
attempts with score+correction, history rounds) so a session is portable between
the two by hand if ever needed."""

from __future__ import annotations

import base64
import io
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .engine import ATTEMPTS_CAP
from .metrics import measure_image

SESS_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "LightMatchMax" / "sessions"
CONFIG_PATH = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "LightMatchMax" / "config.json"


def capture(img, media_type: str = "image/png", max_edge: int = 1568, quality: int = 85) -> dict[str, Any]:
    """PIL image → {metrics, b64, media_type}: measured full pipeline + a downscaled
    JPEG for the wire (same 1568/0.85 send budget the web app uses)."""
    from PIL import Image

    metrics = measure_image(img)
    rgb = img.convert("RGB")
    long_edge = max(rgb.width, rgb.height)
    if long_edge > max_edge:
        s = max_edge / long_edge
        rgb = rgb.resize((max(1, round(rgb.width * s)), max(1, round(rgb.height * s))), Image.BILINEAR)
    buf = io.BytesIO()
    rgb.save(buf, format="JPEG", quality=quality)
    return {"metrics": metrics, "b64": base64.b64encode(buf.getvalue()).decode("ascii"), "media_type": "image/jpeg"}


def new_session(target: str = "vray7max") -> dict[str, Any]:
    return {
        "id": f"lmx-{uuid.uuid4().hex[:10]}",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "name": "",
        "target": target,
        "context": {"scene": "", "time": "", "rig": ""},
        "lock_globals": False,
        "ref": None,          # capture() dict
        "recipe": None,
        "attempts": [],        # {score, correction, at}
        "attempt_count": 0,
    }


def push_attempt(session: dict, score: float, correction: dict) -> None:
    session["attempt_count"] = int(session.get("attempt_count", 0)) + 1
    session.setdefault("attempts", []).append(
        {"score": score, "correction": correction, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    )
    while len(session["attempts"]) > ATTEMPTS_CAP:
        session["attempts"].pop(0)


def history_rounds(session: dict) -> list[dict]:
    """Recipe as round 0, each stored correction as its own round — the MOVE HISTORY
    the correction prompt reads (applied flags: v0.1 assumes applied unless marked)."""
    rounds: list[dict] = []
    recipe = session.get("recipe")
    if recipe and isinstance(recipe.get("values"), list):
        rounds.append({
            "round": 0,
            "moves": [
                {"param": v.get("param"), "from": v.get("from"), "to": v.get("set"),
                 "applied": v.get("applied", True), "why": v.get("why", "")}
                for v in recipe["values"] if isinstance(v, dict)
            ],
        })
    stored = session.get("attempts", [])
    first_n = int(session.get("attempt_count", len(stored))) - (len(stored) - 1) if stored else 1
    for i, att in enumerate(stored):
        corr = att.get("correction") or {}
        if isinstance(corr.get("moves"), list):
            rounds.append({
                "round": first_n + i,
                "moves": [
                    {"param": m.get("param"), "from": m.get("from"), "to": m.get("to"),
                     "applied": m.get("applied", True), "why": m.get("why", "")}
                    for m in corr["moves"] if isinstance(m, dict)
                ],
            })
    return rounds


# -- persistence ------------------------------------------------------------------------
def save(session: dict) -> Path:
    SESS_DIR.mkdir(parents=True, exist_ok=True)
    path = SESS_DIR / f"{session['id']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(session, f)
    return path


def load(session_id: str) -> Optional[dict]:
    path = SESS_DIR / f"{session_id}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_sessions() -> list[dict]:
    if not SESS_DIR.exists():
        return []
    out = []
    for p in sorted(SESS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            with open(p, "r", encoding="utf-8") as f:
                s = json.load(f)
            best = min((a["score"] for a in s.get("attempts", []) if isinstance(a.get("score"), (int, float))), default=None)
            out.append({"id": s.get("id"), "name": s.get("name", ""), "created": s.get("created", ""),
                        "target": s.get("target", ""), "attempts": len(s.get("attempts", [])), "best_score": best,
                        "lock_globals": bool(s.get("lock_globals"))})
        except Exception:
            continue
    return out


# -- key/prefs --------------------------------------------------------------------------
def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
