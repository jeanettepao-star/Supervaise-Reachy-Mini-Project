"""Standalone Streamlit dev page for PLAN-0008 Task 0.

This page exists to PROVE the wake-word plumbing works end-to-end on
the laptop before any of it is wired into the real kiosk
(`app/app.py`). Per PLAN-0008 §5 guardrail "do not break the
existing browser-record path while developing", this file deliberately
imports neither `app.py` nor `cj_chat.py`.

Run it:

    cd C:\\Users\\ASUS\\Projects\\Supervaise-Reachy-Mini-Project\\app
    .\\.venv\\Scripts\\Activate.ps1
    streamlit run wake_test.py

Acceptance (verbatim from PLAN-0008 §6 Task 0 check):
  - Press Start, pick a stock model
  - Speak the word into the laptop mic
  - The "WAKE DETECTED" banner appears within ~500 ms
  - Stats panel shows frames being processed and predictions running
  - Press Stop — engine winds down cleanly
  - Repeat several Start/Stop cycles; engine.stats()['start_count']
    matches the cycle count (no duplicate engines spawned by reruns).

What this page does NOT do:
  - Talk to the chat/router/composer/TTS pipeline (Task 3).
  - Train any custom "hey cj" model (Task 1).
  - Implement the kiosk state machine (Task 2).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import streamlit as st


# ── Set up sys.path so the in-repo `wake/` package is importable ──
_APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_APP_DIR))


# ── Lazy-tolerant imports — surface install errors clearly ────────
_IMPORT_ERROR: str | None = None
try:
    from wake.engine import WakeWordEngine, AVAILABLE_STOCK_MODELS
except Exception as e:  # broad: pip install missing, native lib missing, etc.
    _IMPORT_ERROR = f"{type(e).__name__}: {e}"

try:
    from streamlit_autorefresh import st_autorefresh
except Exception as e:
    if _IMPORT_ERROR is None:
        _IMPORT_ERROR = f"streamlit-autorefresh missing — {type(e).__name__}: {e}"


# ── Page config ────────────────────────────────────────────────────
st.set_page_config(
    page_title="Wake-word test · PLAN-0008 Task 0",
    page_icon="🎤",
    layout="centered",
)


def _surface_import_error() -> None:
    st.error(
        "Wake-word dependencies aren't importable in this venv:\n\n"
        f"`{_IMPORT_ERROR}`\n\n"
        "From the repo root:\n\n"
        "```powershell\n"
        f'& "{sys.executable}" -m pip install -r app/requirements.txt\n'
        "```\n\n"
        "The new pins for Task 0 are `openwakeword`, `sounddevice`, "
        "and `streamlit-autorefresh`."
    )
    st.stop()


def main() -> None:
    if _IMPORT_ERROR:
        _surface_import_error()

    st.title("🎤 Wake-word test")
    st.caption(
        "PLAN-0008 Task 0 · Standalone dev page · "
        "Proves sounddevice → openWakeWord → Streamlit signal works "
        "across reruns. Does not touch `app.py`."
    )

    ss = st.session_state
    ss.setdefault("wake_engine", None)
    ss.setdefault("engine_running", False)
    ss.setdefault("detections", [])
    ss.setdefault("start_error", None)

    # ── Controls ─────────────────────────────────────────────────
    st.subheader("Controls")

    cfg_col1, cfg_col2 = st.columns(2)
    with cfg_col1:
        model_name = st.selectbox(
            "Stock wake-word model",
            options=list(AVAILABLE_STOCK_MODELS),
            index=0,  # hey_jarvis
            disabled=ss.engine_running,
            help="From the openWakeWord MODELS dict. "
                 "Default `hey_jarvis` is less common in incidental speech.",
        )
    with cfg_col2:
        threshold = st.slider(
            "Detection threshold",
            min_value=0.10, max_value=0.95, value=0.50, step=0.05,
            disabled=ss.engine_running,
            help="Higher = fewer false positives but harder to trigger.",
        )

    btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 2])
    with btn_col1:
        start_clicked = st.button(
            "▶ Start", type="primary",
            disabled=ss.engine_running, use_container_width=True,
        )
    with btn_col2:
        stop_clicked = st.button(
            "⏹ Stop",
            disabled=not ss.engine_running, use_container_width=True,
        )
    with btn_col3:
        clear_log_clicked = st.button(
            "🗑 Clear detection log", use_container_width=True,
        )

    # ── State transitions ────────────────────────────────────────
    if start_clicked:
        ss.start_error = None
        # st.status renders a collapsible status block that the
        # engine can write phase messages into via the callback.
        # First-run model download lands as its own visible step so
        # the user knows the few-second pause isn't a hang.
        with st.status(
            "Starting wake-word engine…", expanded=True,
        ) as status_block:

            def _on_phase(msg: str) -> None:
                # st.write inside an open st.status appends a row,
                # status_block.update changes the header label —
                # together they give a live phase log.
                status_block.update(label=f"⏳ {msg}")
                st.write(f"• {msg}")

            try:
                # Explicit download-then-load: lets the UI distinguish
                # "downloading models" from "loading model into ORT" so
                # the (potentially 10-30 s) network-fetch step is
                # clearly visible.
                WakeWordEngine.ensure_models_downloaded(
                    [model_name], progress_cb=_on_phase
                )
                eng = WakeWordEngine(
                    model_name=model_name, threshold=threshold
                )
                eng.start(progress_cb=_on_phase)
            except Exception as e:
                ss.start_error = f"{type(e).__name__}: {e}"
                status_block.update(
                    label=f"✗ Start failed: {type(e).__name__}",
                    state="error",
                    expanded=True,
                )
                st.write(f"`{ss.start_error}`")
            else:
                ss.wake_engine = eng
                ss.engine_running = True
                status_block.update(
                    label="✓ Engine running — say the wake word",
                    state="complete",
                    expanded=False,
                )

        # Re-render the page in running state once the status block
        # has finished its update cycle. Skipped if start failed —
        # the visitor reads the error before the page changes.
        if ss.engine_running:
            st.rerun()

    if stop_clicked and ss.wake_engine is not None:
        try:
            ss.wake_engine.stop()
        finally:
            ss.engine_running = False
            st.rerun()

    if clear_log_clicked:
        ss.detections = []

    # ── Error from a failed start ────────────────────────────────
    if ss.start_error:
        st.error(f"Engine failed to start: `{ss.start_error}`")

    # ── Running state: poll for detections + repaint banner ──────
    if ss.engine_running and ss.wake_engine is not None:
        eng = ss.wake_engine

        # Autorefresh every 500 ms while engine is running. When the
        # engine is stopped we render this branch's `else` and skip
        # the autorefresh entirely — zero idle CPU.
        st_autorefresh(interval=500, limit=None, key="wake_test_autorefresh")

        # poll_detection() returns the most recent detection since
        # last poll, and clears the flag.
        det = eng.poll_detection()
        if det is not None:
            ss.detections.insert(0, det)
            ss.detections = ss.detections[:50]  # cap history

        st.subheader("Engine state")
        if det is not None:
            st.success(
                f"🎯 **WAKE DETECTED** — `{det['model_name']}` "
                f"· score `{det['score']:.3f}` "
                f"· at `{time.strftime('%H:%M:%S', time.localtime(det['ts']))}`"
            )
        else:
            st.info(
                f"😴 SLEEPING — listening for `{eng.model_name}` "
                f"(threshold {eng.threshold})"
            )

        # Diagnostics — useful for verifying the threading model
        # behaves under Streamlit reruns. start_count must NOT
        # climb without each manual Start; thread_alive must be
        # True while running and False after Stop.
        with st.expander("Engine diagnostics", expanded=False):
            st.json(eng.stats())

        # Detection log
        st.subheader(f"Detection log ({len(ss.detections)})")
        if not ss.detections:
            st.caption(
                "Nothing yet. Say the wake word toward your default mic — "
                "the diagnostics panel above shows whether frames are "
                "being processed even if the threshold hasn't been crossed."
            )
        else:
            for d in ss.detections:
                ts_str = time.strftime("%H:%M:%S", time.localtime(d["ts"]))
                st.write(
                    f"`{ts_str}` · **{d['model_name']}** · "
                    f"score `{d['score']:.3f}`"
                )
    else:
        st.subheader("Engine state")
        st.info(
            "Engine not running. Pick a model + threshold, then click "
            "**Start**. Allow microphone access if your OS prompts."
        )


if __name__ == "__main__":
    main()
else:
    # Streamlit imports this module rather than running it as
    # __main__; we have to call main() ourselves.
    main()
