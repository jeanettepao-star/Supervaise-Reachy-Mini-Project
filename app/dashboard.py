"""Audience-facing dashboard for the CJ Panganiban conversation app.

The CLI (cj_chat.py) drives audio I/O and writes its state to
`state/current.json` after each pipeline stage. This dashboard reads that file
on a 1-second refresh and shows the audience what's happening — the question,
which corpus topics matched, CJ's response, and a history of past turns.

Run alongside the CLI:
    streamlit run dashboard.py

Then open the URL Streamlit prints (default: http://localhost:8501).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from datetime import datetime

import streamlit as st

STATE_FILE = Path(__file__).parent / "state" / "current.json"
REFRESH_SECONDS = 1.0

# ----- Page chrome ---------------------------------------------------------
st.set_page_config(
    page_title="With Due Respect — CJ Panganiban",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Tasteful CSS — single-column dark feel, generous spacing.
st.markdown(
    """
    <style>
      .stApp { background: #0e1117; }
      .big-question {
        font-size: 1.6rem; line-height: 1.4;
        color: #e6e6e6; font-style: italic;
        padding: 1rem 1.2rem; border-left: 4px solid #6c8eef;
        background: #1a1f2e; border-radius: 6px;
      }
      .cj-response {
        font-size: 1.25rem; line-height: 1.6;
        color: #f6f1e1; padding: 1.4rem 1.6rem;
        background: #1a1812; border-left: 4px solid #c4a747;
        border-radius: 6px; white-space: pre-wrap;
      }
      .stage-label { color: #9aa4b3; font-size: 0.95rem; }
      .topic-pill {
        display: inline-block; padding: 0.25rem 0.7rem; margin: 0.15rem 0.3rem 0.15rem 0;
        border-radius: 999px; font-size: 0.85rem; font-weight: 500;
      }
      .topic-primary { background: #2d4ea8; color: #fff; }
      .topic-secondary { background: #2a3144; color: #c5cad6; }
      .conf-high { color: #4ad295; }
      .conf-medium { color: #e6c149; }
      .conf-low { color: #d97f5f; }
      .turn-card {
        padding: 0.9rem 1.1rem; margin-bottom: 0.6rem;
        background: #161a23; border-radius: 6px; border: 1px solid #232936;
      }
      .turn-card-question { color: #c5cad6; font-style: italic; margin-bottom: 0.3rem; }
      .turn-card-response { color: #d8d3c3; font-size: 0.92rem; }
      .turn-meta { color: #6f7889; font-size: 0.78rem; margin-bottom: 0.25rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ----- State load ----------------------------------------------------------
def load_state() -> dict:
    if not STATE_FILE.exists():
        return {
            "status": "idle",
            "turn_id": 0,
            "question": None,
            "routing": None,
            "response": None,
            "stage_label": "Waiting for the CLI to start a turn",
            "history": [],
        }
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        # tear between writer's rename and our read — show last known state
        return st.session_state.get("_last_state", {
            "status": "idle", "turn_id": 0, "stage_label": "Reading state…",
            "question": None, "routing": None, "response": None, "history": [],
        })


state = load_state()
st.session_state["_last_state"] = state


# ----- Header --------------------------------------------------------------
left, right = st.columns([4, 1])
with left:
    st.markdown(
        "<h1 style='margin-bottom:0; color:#f6f1e1;'>⚖️ With Due Respect</h1>"
        "<p style='color:#9aa4b3; margin-top:0.2rem;'>"
        "A conversation with retired Chief Justice Artemio V. Panganiban"
        "</p>",
        unsafe_allow_html=True,
    )
with right:
    # Status indicator
    status = state.get("status", "idle")
    label = state.get("stage_label") or status.title()
    color = {
        "idle": "#6f7889",
        "listening": "#4ad295",
        "transcribing": "#6c8eef",
        "routing": "#9b6ce6",
        "thinking": "#e6c149",
        "speaking": "#d97f5f",
        "done": "#4ad295",
    }.get(status, "#6f7889")
    pulsing = status in {"listening", "transcribing", "routing", "thinking", "speaking"}
    dot = (
        f"<span style='display:inline-block; width:12px; height:12px; "
        f"background:{color}; border-radius:50%; margin-right:0.5rem; "
        f"{'animation: pulse 1.2s infinite;' if pulsing else ''}'></span>"
    )
    st.markdown(
        f"<div style='text-align:right; padding-top:1.4rem;'>{dot}"
        f"<span class='stage-label'>{label}</span></div>"
        "<style>@keyframes pulse {0%,100%{opacity:1}50%{opacity:0.3}}</style>",
        unsafe_allow_html=True,
    )

st.markdown("<div style='margin: 1.2rem 0; border-top:1px solid #232936;'></div>",
            unsafe_allow_html=True)


# ----- Current turn --------------------------------------------------------
turn_id = state.get("turn_id", 0)
if turn_id == 0:
    st.info(
        "No turns yet. Start the CLI in a separate terminal:\n\n"
        "```\n.venv\\Scripts\\python.exe cj_chat.py\n```\n\n"
        "Press Enter, speak your question, and watch this page."
    )
else:
    st.markdown(f"<div class='stage-label'>Turn {turn_id}</div>",
                unsafe_allow_html=True)

    # Question
    question = state.get("question")
    if question:
        st.markdown(
            f"<div class='big-question'>{question}</div>",
            unsafe_allow_html=True,
        )
    elif status == "listening":
        st.markdown(
            "<div class='big-question' style='color:#6f7889;'>"
            "<em>Listening for the question…</em></div>",
            unsafe_allow_html=True,
        )

    # Routing
    routing = state.get("routing")
    if routing:
        st.markdown("<div style='margin-top:1rem;'></div>", unsafe_allow_html=True)
        primary = routing.get("primary_topic", "—")
        secondary = routing.get("secondary_topics", []) or []
        confidence = routing.get("confidence", "—")
        reasoning = routing.get("reasoning", "")

        pills = [f"<span class='topic-pill topic-primary'>{primary}</span>"]
        for t in secondary:
            pills.append(f"<span class='topic-pill topic-secondary'>{t}</span>")

        conf_class = f"conf-{confidence}" if confidence in {"high", "medium", "low"} else ""
        st.markdown(
            "<div class='stage-label'>Routed to</div>"
            f"<div style='margin-top:0.3rem;'>{''.join(pills)}</div>"
            f"<div class='stage-label' style='margin-top:0.5rem;'>"
            f"confidence: <span class='{conf_class}'>{confidence}</span>"
            f"{(' — ' + reasoning) if reasoning else ''}</div>",
            unsafe_allow_html=True,
        )

    # Response
    response = state.get("response")
    if response:
        st.markdown("<div style='margin-top:1.4rem;'></div>", unsafe_allow_html=True)
        st.markdown(f"<div class='cj-response'>{response}</div>",
                    unsafe_allow_html=True)
    elif status == "thinking":
        st.markdown(
            "<div class='cj-response' style='color:#9aa4b3;'>"
            "<em>CJ is composing his answer…</em></div>",
            unsafe_allow_html=True,
        )


# ----- History (past turns) ------------------------------------------------
history = state.get("history", []) or []
# Don't double-show the current turn if it's already in history
past = [h for h in history if h.get("turn_id") != turn_id]
if past:
    st.markdown("<div style='margin-top: 2.5rem;'></div>", unsafe_allow_html=True)
    with st.expander(f"📜 Earlier turns ({len(past)})", expanded=False):
        for h in reversed(past[-10:]):  # most recent first, cap at 10 for screen real estate
            q = h.get("question") or "—"
            r = h.get("response") or "—"
            rt = h.get("routing") or {}
            primary = rt.get("primary_topic", "—")
            ts = h.get("ts")
            time_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else ""
            st.markdown(
                f"<div class='turn-card'>"
                f"<div class='turn-meta'>Turn {h.get('turn_id')} · {time_str} · "
                f"→ <span style='color:#8aa0d8;'>{primary}</span></div>"
                f"<div class='turn-card-question'>“{q}”</div>"
                f"<div class='turn-card-response'>{r}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )


# ----- Auto-refresh --------------------------------------------------------
# Built-in approach — sleep then rerun. Avoids the streamlit-autorefresh dep.
time.sleep(REFRESH_SECONDS)
st.rerun()
