"""Shared state writer for the dashboard.

The CLI (cj_chat.py) calls these helpers as it progresses through each pipeline
stage; the Streamlit dashboard (dashboard.py) reads the same file with a
1-second polling refresh to show the audience what's happening.

Schema (state/current.json — overwritten on every stage):
{
  "status":       "idle" | "listening" | "transcribing" | "routing"
                   | "thinking" | "speaking" | "done",
  "turn_id":      int,                 # increments each turn
  "question":     str | null,          # filled after STT
  "routing":      { primary_topic, secondary_topics, confidence, reasoning }
                                       # filled after router
  "response":     str | null,          # filled after inference
  "stage_started_at": float (epoch),
  "stage_label":  str,                 # human-readable "Routing question..."
  "history":      [ { turn_id, question, routing, response, ts } ... ]
}

Writes are atomic (write-to-tmp + rename) so the dashboard never sees a
half-written file.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

STATE_DIR = Path(__file__).parent / "state"
STATE_FILE = STATE_DIR / "current.json"

_MAX_HISTORY = 20


def _ensure_dir() -> None:
    STATE_DIR.mkdir(exist_ok=True)


def _read() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {
            "status": "idle",
            "turn_id": 0,
            "question": None,
            "routing": None,
            "response": None,
            "stage_started_at": time.time(),
            "stage_label": "Waiting for the next turn",
            "history": [],
        }
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        # Reader may have caught a tear; return idle and let the next write fix it.
        return {
            "status": "idle",
            "turn_id": 0,
            "question": None,
            "routing": None,
            "response": None,
            "stage_started_at": time.time(),
            "stage_label": "Waiting for the next turn",
            "history": [],
        }


def _write_atomic(state: dict[str, Any]) -> None:
    _ensure_dir()
    # Same-directory tempfile + os.replace = atomic on every OS we care about.
    fd, tmp_path = tempfile.mkstemp(
        prefix="state.", suffix=".tmp", dir=str(STATE_DIR)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, STATE_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# Public API ---------------------------------------------------------------

def begin_turn() -> int:
    """Mark the start of a new turn. Returns the new turn_id."""
    state = _read()
    state["turn_id"] = int(state.get("turn_id", 0)) + 1
    state["question"] = None
    state["routing"] = None
    state["response"] = None
    state["status"] = "idle"
    state["stage_label"] = f"Turn {state['turn_id']} starting"
    state["stage_started_at"] = time.time()
    _write_atomic(state)
    return state["turn_id"]


def set_status(status: str, label: str) -> None:
    state = _read()
    state["status"] = status
    state["stage_label"] = label
    state["stage_started_at"] = time.time()
    _write_atomic(state)


def set_question(question: str) -> None:
    state = _read()
    state["question"] = question
    _write_atomic(state)


def set_routing(routing: dict[str, Any]) -> None:
    state = _read()
    state["routing"] = routing
    _write_atomic(state)


def set_response(response: str) -> None:
    state = _read()
    state["response"] = response
    _write_atomic(state)


def finish_turn() -> None:
    """Append the current turn to history; mark status=done."""
    state = _read()
    turn_record = {
        "turn_id": state.get("turn_id"),
        "question": state.get("question"),
        "routing": state.get("routing"),
        "response": state.get("response"),
        "ts": time.time(),
    }
    history = state.get("history", [])
    history.append(turn_record)
    state["history"] = history[-_MAX_HISTORY:]
    state["status"] = "done"
    state["stage_label"] = "Turn complete"
    _write_atomic(state)


def reset() -> None:
    """Wipe state — useful when starting a fresh demo."""
    _ensure_dir()
    state = {
        "status": "idle",
        "turn_id": 0,
        "question": None,
        "routing": None,
        "response": None,
        "stage_started_at": time.time(),
        "stage_label": "Waiting for the first turn",
        "history": [],
    }
    _write_atomic(state)
