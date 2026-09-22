"""Saved diagnostics: every conversation kept on disk and resumable.

Companies and agent sessions otherwise live only in process memory, so a
restart lost every diagnostic and there was nothing to go back to. This keeps
both as plain JSON files under config.HISTORY_DIR (chat_history/ in the project
root), one file each, so they can be read, copied or deleted by hand:

- companies/<id>.json: an uploaded P&L as the app holds it, EBITDA history and
  trend included, so a reopened diagnostic still has its figures and chart.
- sessions/<id>.json: the agent's full state (the same fields as
  agent.Session), the transcript the UI shows, and a small summary block for
  the history list.

Writes go to a temporary file first and are then renamed into place, so a
crash mid-write never leaves half a file. Nothing here calls a model.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import threading
from pathlib import Path
from typing import Optional

import config

_LOCK = threading.Lock()
# Ids arrive in URLs; anything else could walk out of the history folder.
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _dir(kind: str) -> Path:
    d = config.HISTORY_DIR / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(kind: str, item_id: str) -> Optional[Path]:
    if not _SAFE_ID.match(item_id or ""):
        return None
    return _dir(kind) / f"{item_id}.json"


def _write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    with _LOCK:
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, path)


def _read(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A missing or damaged file reads as absent rather than failing the
        # whole list.
        return None


# --- companies -----------------------------------------------------------------

def save_company(company: dict, now: float) -> None:
    path = _path("companies", company["id"])
    if path is not None:
        _write(path, {"updated_at": now, "company": company})


def load_companies() -> list[dict]:
    out = []
    for p in _dir("companies").glob("*.json"):
        d = _read(p)
        if d and isinstance(d.get("company"), dict):
            out.append(d["company"])
    return out


# --- sessions ------------------------------------------------------------------

def _summary(session) -> dict:
    """The fields a history list row needs, computed once at save time."""
    p = session.portco
    last_agent = next((m["content"] for m in reversed(session.transcript)
                       if m["role"] == "assistant"), "")
    return {
        "company_id": p["id"],
        "industry": p["industry"],
        "fiscal_year": p.get("fiscal_year"),
        "revenue": p.get("financials", {}).get("revenue"),
        "findings_count": len(session.findings),
        "message_count": len(session.transcript),
        "preview": " ".join(last_agent.split())[:160],
    }


def save_session(session, now: float) -> None:
    """Write the whole session. Called after every completed turn."""
    path = _path("sessions", session.id)
    if path is None:
        return
    state = dataclasses.asdict(session)
    transcript = state.pop("transcript")
    _write(path, {
        "id": session.id,
        "created_at": session.created_at,
        "updated_at": now,
        "summary": _summary(session),
        "transcript": transcript,
        "state": state,
    })


def load_session(session_id: str) -> Optional[dict]:
    """The saved state, with its transcript, ready for agent.restore_session."""
    path = _path("sessions", session_id)
    d = _read(path) if path is not None else None
    if not d or not isinstance(d.get("state"), dict):
        return None
    return {**d["state"], "transcript": d.get("transcript", [])}


def list_sessions(limit: int = 100) -> list[dict]:
    rows = []
    for p in _dir("sessions").glob("*.json"):
        d = _read(p)
        if not d or "summary" not in d:
            continue
        rows.append({"id": d["id"], "created_at": d.get("created_at"),
                     "updated_at": d.get("updated_at"), **d["summary"]})
    rows.sort(key=lambda r: r.get("updated_at") or 0, reverse=True)
    return rows[:limit]


def delete_session(session_id: str) -> bool:
    path = _path("sessions", session_id)
    if path is None or not path.exists():
        return False
    with _LOCK:
        path.unlink()
    return True
