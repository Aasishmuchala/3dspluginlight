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


# -- per-camera model (Stage 2) --------------------------------------------------------
# A session holds MANY camera slots keyed by camera name. Each slot carries its OWN
# reference (target), base render (BYO or grabbed), recipe, and refine history — so
# picking a camera in the dock recalls that camera's whole state. "" is the default slot
# (no camera picked). context / lock_globals / renderer stay scene-wide on the session.
def new_camera_slot() -> dict[str, Any]:
    """One camera's state: reference + base + recipe + attempts. All JSON-serializable, so
    a slot (including the user's loaded base render) persists with the session."""
    return {"ref": None, "base": None, "recipe": None, "attempts": [], "attempt_count": 0}


def new_session(target: str = "vray7max") -> dict[str, Any]:
    return {
        "id": f"lmx-{uuid.uuid4().hex[:10]}",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "name": "",
        "target": target,
        "context": {"scene": "", "time": "", "rig": ""},
        "lock_globals": False,
        "active_camera": "",                    # key into `cameras`; "" = default slot
        "cameras": {"": new_camera_slot()},     # name -> slot
    }


def camera_slot(session: dict, name: str) -> dict:
    """The slot for camera `name`, created lazily. name "" (or falsy) = the default slot.
    The single place slots are minted, so the shape never drifts."""
    cams = session.setdefault("cameras", {})
    key = name or ""
    if key not in cams or not isinstance(cams.get(key), dict):
        cams[key] = new_camera_slot()
    return cams[key]


def migrate_session(session: dict) -> dict:
    """Bring a legacy single-slot session (top-level ref/recipe/attempts) up to the
    per-camera model by wrapping it into the default slot cameras[""]. Idempotent: a
    session already on the new model just gets its keys ensured. Mutates and returns it."""
    if not isinstance(session, dict):
        return session
    if not isinstance(session.get("cameras"), dict) or not session.get("cameras"):
        session["cameras"] = {"": {
            "ref": session.pop("ref", None),
            "base": session.pop("base", None),
            "recipe": session.pop("recipe", None),
            "attempts": session.pop("attempts", None) or [],
            "attempt_count": session.pop("attempt_count", None) or 0,
        }}
    session.setdefault("active_camera", "")
    # ensure the active slot exists (a hand-edited active_camera could point nowhere)
    camera_slot(session, session.get("active_camera") or "")
    return session


def push_attempt(slot: dict, score: float, correction: dict) -> None:
    """Append a scored attempt to ONE camera slot (not the whole session)."""
    slot["attempt_count"] = int(slot.get("attempt_count", 0)) + 1
    slot.setdefault("attempts", []).append(
        {"score": score, "correction": correction, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    )
    while len(slot["attempts"]) > ATTEMPTS_CAP:
        slot["attempts"].pop(0)


def history_rounds(slot: dict) -> list[dict]:
    """Recipe as round 0, each stored correction as its own round — the MOVE HISTORY the
    correction prompt reads, for ONE camera slot (applied flags: assumes applied unless
    marked)."""
    rounds: list[dict] = []
    recipe = slot.get("recipe")
    if recipe and isinstance(recipe.get("values"), list):
        rounds.append({
            "round": 0,
            "moves": [
                {"param": v.get("param"), "from": v.get("from"), "to": v.get("set"),
                 "applied": v.get("applied", True), "why": v.get("why", "")}
                for v in recipe["values"] if isinstance(v, dict)
            ],
        })
    stored = slot.get("attempts", [])
    first_n = int(slot.get("attempt_count", len(stored))) - (len(stored) - 1) if stored else 1
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
        return migrate_session(json.load(f))


def list_sessions() -> list[dict]:
    if not SESS_DIR.exists():
        return []
    out = []
    for p in sorted(SESS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            with open(p, "r", encoding="utf-8") as f:
                s = migrate_session(json.load(f))
            slots = list(s.get("cameras", {}).values())
            scores = [a["score"] for slot in slots for a in (slot.get("attempts") or [])
                      if isinstance(a.get("score"), (int, float))]
            attempts = sum(len(slot.get("attempts") or []) for slot in slots)
            named = [k for k in s.get("cameras", {}) if k]  # real cameras (exclude the "" default)
            out.append({"id": s.get("id"), "name": s.get("name", ""), "created": s.get("created", ""),
                        "target": s.get("target", ""), "attempts": attempts,
                        "best_score": min(scores, default=None), "cameras": len(named),
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
