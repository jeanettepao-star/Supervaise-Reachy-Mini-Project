"""
⚖️ With Due Respect — museum-kiosk Streamlit app.

A single-file, voice-only kiosk experience for visitors to converse with
the AI rendering of retired Chief Justice Artemio V. Panganiban. This
file is deliberately UI-heavy; the chat / voice pipeline itself lives
in `cj_chat.py` (Anthropic chat) and `voice_io.py` (OpenAI STT/TTS) and
is imported here so the kiosk and the developer dashboard share a single
source of truth.

Launch (PowerShell, from the repo root):

    cd C:\\Users\\ASUS\\Projects\\Supervaise-Reachy-Mini-Project\\app
    .\\.venv\\Scripts\\Activate.ps1
    streamlit run app.py

Asset overrides (drop your own JPG/PNG to swap them in):

    app/assets/reachy_curious.png   — main robot portrait
    app/assets/museum_bg.jpg        — full-screen gallery background

If those files don't exist, the app falls back to:
  • a polished inline SVG of the Reachy Mini "Curious" pose,
  • a CSS-only gallery backdrop (vertical gradient + soft uplighting).

State machine
=============
              ┌───────────────────────────────────────────┐
              │                                           ▼
   IDLE  ── press RECORD ──▶  RECORDING  ── stop ──▶  PROCESSING
     ▲                          │                        │
     │                       cancel                    pipeline OK
     │                          ▼                        │
     └──────────────────────  IDLE  ◀── PLAY done ──── READY
                                         (or auto-play timeout)

Pipeline (PROCESSING):
   recorded WAV bytes
     → OpenAI Whisper (STT)             → user transcript
     → Haiku Input Gate                 → scope: in_corpus / OOC / META
     → Haiku Router (or META override)  → topic_paths
     → Sonnet Composer (streamed)       → CJ response text
     → Haiku Fidelity Check             → advisory flags
     → OpenAI TTS (parallel per sent.)  → MP3 bytes ready for PLAY
"""

from __future__ import annotations

import base64
import os
import sys
import tempfile
import time
from pathlib import Path

# ─── Streamlit & in-repo modules (lazy-tolerant imports) ──────────────────
import streamlit as st

_APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_APP_DIR))

# All chat / STT / TTS logic lives in two modules. If they're not
# importable (broken venv, etc.), `app.py` still renders a clear
# remediation banner instead of crashing.
_IMPORT_ERROR: str | None = None
try:
    import cj_chat  # noqa: F401
    from cj_chat import (
        CorpusArtifacts,
        build_context,
        fidelity_check,
        force_meta_routing,
        generate_response_stream,
        input_gate,
        loaded_env_summary,
        make_client,
        route_question,
        _strip_stage_directions,
    )
    from voice_io import (
        estimate_voice_cost,
        sentence_chunks,
        transcribe_openai,
        tts_concatenate_parallel,
        voice_io_summary,
    )
except Exception as e:  # pragma: no cover — surfaced in the banner below
    _IMPORT_ERROR = f"{type(e).__name__}: {e}"


# ─── Page config — kiosk first ────────────────────────────────────────────
st.set_page_config(
    page_title="With Due Respect — A Reachy Mini × CJP Exhibit",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ─── Asset resolution (image overrides) ───────────────────────────────────
ASSETS_DIR = _APP_DIR / "assets"
ROBOT_PNG = ASSETS_DIR / "reachy_curious.png"
BG_JPG = ASSETS_DIR / "museum_bg.jpg"


def _file_to_data_url(path: Path, mime: str) -> str | None:
    """Return a data:URL for an on-disk asset, or None if absent."""
    try:
        if path.exists():
            return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
    except Exception:
        pass
    return None


_ROBOT_DATA_URL = _file_to_data_url(ROBOT_PNG, "image/png")
_BG_DATA_URL = _file_to_data_url(BG_JPG, "image/jpeg")


# ─── Embedded Reachy Mini SVG (fallback when no PNG override) ─────────────
# The user referenced a clean white minimalist robot with twin antennas and
# dual camera eyes (the "Curious" pose). This SVG approximates that look in
# a single inline string — operator can drop their own PNG into
# `app/assets/reachy_curious.png` to override.
REACHY_CURIOUS_SVG = """
<svg viewBox='0 0 360 420' xmlns='http://www.w3.org/2000/svg'
     aria-label='Reachy Mini robot in the Curious pose'>
  <defs>
    <linearGradient id='bodyGrad' x1='0' y1='0' x2='0' y2='1'>
      <stop offset='0%'   stop-color='#fdfdfd'/>
      <stop offset='100%' stop-color='#c8ccd6'/>
    </linearGradient>
    <radialGradient id='cheekGlow' cx='50%' cy='50%' r='50%'>
      <stop offset='0%'   stop-color='#ffd86c' stop-opacity='0.35'/>
      <stop offset='100%' stop-color='#ffd86c' stop-opacity='0'/>
    </radialGradient>
    <filter id='softShadow' x='-20%' y='-20%' width='140%' height='140%'>
      <feGaussianBlur stdDeviation='8' in='SourceAlpha'/>
      <feOffset dy='10'/>
      <feComponentTransfer><feFuncA type='linear' slope='0.45'/></feComponentTransfer>
      <feMerge><feMergeNode/><feMergeNode in='SourceGraphic'/></feMerge>
    </filter>
  </defs>

  <!-- Antennae — gentle sway -->
  <g filter='url(#softShadow)'>
    <line x1='130' y1='80' x2='105' y2='25' stroke='#1f2533' stroke-width='5' stroke-linecap='round'>
      <animateTransform attributeName='transform' type='rotate'
                       values='0 130 80; -3 130 80; 0 130 80; 3 130 80; 0 130 80'
                       dur='6s' repeatCount='indefinite'/>
    </line>
    <circle cx='105' cy='25' r='12' fill='#f2c44e'/>
    <line x1='230' y1='80' x2='255' y2='25' stroke='#1f2533' stroke-width='5' stroke-linecap='round'>
      <animateTransform attributeName='transform' type='rotate'
                       values='0 230 80; 3 230 80; 0 230 80; -3 230 80; 0 230 80'
                       dur='6s' repeatCount='indefinite'/>
    </line>
    <circle cx='255' cy='25' r='12' fill='#f2c44e'/>
  </g>

  <!-- Body shell with subtle float -->
  <g filter='url(#softShadow)'>
    <animateTransform attributeName='transform' type='translate'
                     values='0 0; 0 -4; 0 0' dur='5.5s' repeatCount='indefinite'/>

    <!-- Side ear-cups -->
    <ellipse cx='65' cy='240' rx='28' ry='52' fill='#e6e9ef' stroke='#9aa0b0' stroke-width='2'/>
    <ellipse cx='295' cy='240' rx='28' ry='52' fill='#e6e9ef' stroke='#9aa0b0' stroke-width='2'/>
    <circle cx='65'  cy='240' r='14' fill='#1f2533'/>
    <circle cx='295' cy='240' r='14' fill='#1f2533'/>

    <!-- Main body / head shell — rounded pill -->
    <rect x='100' y='80' width='160' height='280' rx='40'
          fill='url(#bodyGrad)' stroke='#9aa0b0' stroke-width='2'/>

    <!-- Face panel — dark glass, holds the eyes -->
    <rect x='128' y='150' width='104' height='90' rx='14'
          fill='#0f1320' stroke='#2a3144' stroke-width='1.5'/>

    <!-- Eyes — dual camera lenses with breath + occasional blink -->
    <ellipse cx='160' cy='195' rx='15' ry='15' fill='#1c2334'>
      <animate attributeName='rx' values='15;13.5;15' dur='3.5s' repeatCount='indefinite'/>
      <animate attributeName='ry'
               values='15;15;1.5;15;15'
               keyTimes='0;0.46;0.5;0.54;1'
               dur='5.8s' repeatCount='indefinite'/>
    </ellipse>
    <ellipse cx='200' cy='195' rx='15' ry='15' fill='#1c2334'>
      <animate attributeName='rx' values='15;13.5;15' dur='3.5s' repeatCount='indefinite'/>
      <animate attributeName='ry'
               values='15;15;1.5;15;15'
               keyTimes='0;0.46;0.5;0.54;1'
               dur='5.8s' repeatCount='indefinite'/>
    </ellipse>
    <!-- Catch-light highlights on each eye -->
    <circle cx='156' cy='190' r='3.5' fill='#f6f1e1' opacity='0.92'/>
    <circle cx='196' cy='190' r='3.5' fill='#f6f1e1' opacity='0.92'/>

    <!-- Cheek glow accent -->
    <circle cx='180' cy='200' r='80' fill='url(#cheekGlow)'/>

    <!-- Subtle mouth / neutral curve -->
    <path d='M 152 268 Q 180 276 208 268'
          stroke='#2a3144' stroke-width='2.5' fill='none' stroke-linecap='round'/>

    <!-- Body badge / chest plate -->
    <rect x='150' y='300' width='60' height='28' rx='6'
          fill='#1f2533' stroke='#9aa0b0' stroke-width='1.2'/>
    <text x='180' y='319' fill='#f2c44e' font-size='11'
          font-family='Cormorant Garamond, Georgia, serif'
          text-anchor='middle' font-weight='600' letter-spacing='2'>FLP</text>
  </g>
</svg>
"""


# ─── Pre-flight checks ────────────────────────────────────────────────────
def _preflight() -> None:
    """Bail out at page-load with a clear remediation banner if any
    dependency is missing — beats a cryptic mid-turn error."""
    if _IMPORT_ERROR:
        st.error(
            "Module import failed:\n\n"
            f"`{_IMPORT_ERROR}`\n\n"
            "Install the requirements into the same venv Streamlit is "
            "running from. From the repo root:\n\n"
            "```powershell\n"
            f'& "{sys.executable}" -m pip install -r app/requirements.txt\n'
            "```"
        )
        st.stop()

    env = loaded_env_summary()
    voice = voice_io_summary()
    missing = []
    if not env.get("api_key_present"):
        missing.append("ANTHROPIC_API_KEY")
    if not voice.get("openai_key_present"):
        missing.append("OPENAI_API_KEY")
    if missing:
        st.error(
            "Missing API key(s): " + ", ".join(f"`{k}`" for k in missing) +
            ". Add them to `app/.env` and restart Streamlit. The kiosk "
            "needs both — Anthropic for the chat pipeline, OpenAI for "
            "STT (Whisper) and TTS."
        )
        st.stop()


# ─── Session state ────────────────────────────────────────────────────────
def _init_state() -> None:
    ss = st.session_state
    ss.setdefault("kiosk_state", "IDLE")          # IDLE / RECORDING / PROCESSING / READY
    ss.setdefault("mic_key", 0)                   # bump to force audio_input reset
    ss.setdefault("transcript", "")               # last user query (Whisper)
    ss.setdefault("response", "")                 # last CJ text response
    ss.setdefault("audio_bytes", None)            # last TTS MP3 blob
    ss.setdefault("routing", None)                # last router output dict
    ss.setdefault("gate", None)                   # last gate result
    ss.setdefault("fidelity", None)               # last fidelity check
    ss.setdefault("tts_meta", None)               # cost / chunk count
    ss.setdefault("error", None)                  # last pipeline error string
    ss.setdefault("show_drawer", False)           # diagnostics drawer visible
    ss.setdefault("autoplay_pending", False)      # play once when entering READY


# ─── Custom CSS — museum dark theme + glass panel + button styles ─────────
def _bg_layer() -> str:
    """Build the .stApp background layer. If the operator dropped a
    real museum-gallery JPG into `app/assets/museum_bg.jpg`, we use
    that with a darkening overlay. Otherwise we fall back to a
    CSS-only gallery look (radial uplighting + vertical gradient)."""
    if _BG_DATA_URL:
        return (
            f"background:"
            f" linear-gradient(180deg, rgba(8,11,20,0.78) 0%, "
            f"   rgba(8,11,20,0.55) 50%, rgba(8,11,20,0.85) 100%),"
            f" url('{_BG_DATA_URL}') center/cover no-repeat fixed;"
        )
    # CSS-only gallery atmosphere
    return (
        "background:"
        "  radial-gradient(1100px 480px at 50% 0%,"
        "    rgba(212, 180, 110, 0.20), transparent 65%),"
        "  radial-gradient(900px 600px at 50% 100%,"
        "    rgba(28, 35, 52, 0.55), transparent 55%),"
        "  linear-gradient(180deg,"
        "    #0a0f1c 0%, #0e1424 35%, #14182a 70%, #0a0f1c 100%);"
    )


def _inject_css() -> None:
    css = """
    @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600;700&family=Inter:wght@300;400;500;600&display=swap');

    /* ── Reset Streamlit chrome for a kiosk feel ─────────────────── */
    #MainMenu, header, footer { visibility: hidden; height: 0; }
    .stDeployButton, [data-testid='stToolbar'], [data-testid='stDecoration'] {
        display: none !important;
    }
    [data-testid='stHeader'] { background: transparent; height: 0; }
    .block-container {
        padding-top: 1.2rem !important;
        padding-bottom: 1.2rem !important;
        max-width: 1280px;
    }

    /* ── Full-screen gallery background ──────────────────────────── */
    .stApp { __BG_LAYER__ color: #e6e9ef; }

    /* ── Central glass panel ─────────────────────────────────────── */
    .museum-glass {
        position: relative;
        margin: 1.4rem auto 0.6rem;
        padding: 2.0rem 2.4rem 1.6rem;
        max-width: 980px;
        border-radius: 28px;
        background: rgba(255, 255, 255, 0.05);
        backdrop-filter: blur(14px) saturate(140%);
        -webkit-backdrop-filter: blur(14px) saturate(140%);
        border: 1px solid rgba(255, 255, 255, 0.14);
        box-shadow:
            0 30px 70px -30px rgba(0, 0, 0, 0.75),
            inset 0 1px 0 rgba(255, 255, 255, 0.06);
        overflow: hidden;
    }
    /* Soft top sheen */
    .museum-glass::before {
        content: '';
        position: absolute; left: 0; right: 0; top: 0; height: 70px;
        background: linear-gradient(180deg,
            rgba(255,255,255,0.10), rgba(255,255,255,0.0));
        pointer-events: none;
    }

    /* ── Title typography ────────────────────────────────────────── */
    .museum-title {
        font-family: 'Cormorant Garamond', Georgia, serif;
        font-size: 3.4rem; line-height: 1.0;
        font-weight: 600; letter-spacing: 0.5px;
        color: #f6f1e1; margin: 0;
    }
    .museum-subtitle {
        font-family: 'Inter', sans-serif;
        font-size: 1.0rem; color: #c1c7d6; font-style: italic;
        margin: 0.5rem 0 0; letter-spacing: 0.2px;
    }
    .museum-blurb {
        font-family: 'Inter', sans-serif;
        font-size: 0.95rem; color: #b5bbcb;
        margin: 0.6rem 0 0; max-width: 540px; line-height: 1.5;
    }

    /* ── Status pill, top-right of glass panel ───────────────────── */
    .status-pill {
        position: absolute; top: 18px; right: 22px;
        display: inline-flex; align-items: center; gap: 0.4rem;
        padding: 0.34rem 0.85rem; border-radius: 999px;
        font-family: 'Inter', sans-serif;
        font-size: 0.78rem; font-weight: 600; letter-spacing: 1.3px;
        text-transform: uppercase;
        background: rgba(15, 19, 32, 0.55); border: 1px solid;
    }
    .status-pill .dot {
        width: 8px; height: 8px; border-radius: 50%;
    }
    .status-pill.IDLE       { color: #f2c44e; border-color: rgba(242,196,78,0.55); }
    .status-pill.IDLE .dot  { background: #f2c44e; }
    .status-pill.RECORDING  { color: #4ad295; border-color: rgba(74,210,149,0.55);
                              animation: pulse-glow 1.4s ease-in-out infinite; }
    .status-pill.RECORDING .dot { background: #4ad295;
                                   box-shadow: 0 0 10px #4ad295; }
    .status-pill.PROCESSING { color: #66b3ff; border-color: rgba(102,179,255,0.55); }
    .status-pill.PROCESSING .dot { background: #66b3ff;
                                    animation: pulse-glow 0.9s ease-in-out infinite; }
    .status-pill.READY      { color: #f2c44e; border-color: rgba(242,196,78,0.65);
                              background: rgba(242, 196, 78, 0.10); }
    .status-pill.READY .dot { background: #f2c44e;
                               box-shadow: 0 0 12px #f2c44e; }
    @keyframes pulse-glow {
        0%, 100% { opacity: 1.0; }
        50%      { opacity: 0.45; }
    }

    /* ── Robot framing inside glass panel ────────────────────────── */
    .robot-frame {
        display: flex; justify-content: center; align-items: center;
        padding: 0.6rem 0 0.4rem;
    }
    .robot-frame svg, .robot-frame img {
        height: 360px; width: auto;
        filter: drop-shadow(0 18px 24px rgba(0,0,0,0.45));
    }
    /* When recording, give the robot a green glow */
    .museum-glass.recording .robot-frame svg,
    .museum-glass.recording .robot-frame img {
        filter: drop-shadow(0 0 24px rgba(74, 210, 149, 0.55))
                drop-shadow(0 18px 24px rgba(0,0,0,0.45));
    }
    .museum-glass.processing .robot-frame svg,
    .museum-glass.processing .robot-frame img {
        filter: drop-shadow(0 0 22px rgba(102, 179, 255, 0.55))
                drop-shadow(0 18px 24px rgba(0,0,0,0.45));
    }
    .museum-glass.ready .robot-frame svg,
    .museum-glass.ready .robot-frame img {
        filter: drop-shadow(0 0 22px rgba(242, 196, 78, 0.50))
                drop-shadow(0 18px 24px rgba(0,0,0,0.45));
    }

    /* ── Physical console — button bar below the glass panel ──── */
    .console-row { margin-top: 1.0rem; }
    .console-row [data-testid='stHorizontalBlock'] {
        gap: 1.2rem !important;
    }

    /* Streamlit buttons by column index — first column = RECORD,
       second = STOP, third = PLAY. We use nth-of-type so the styling
       stays attached to the layout slot, not to the button label. */
    .console-row [data-testid='column']:nth-of-type(1) button {
        background: linear-gradient(180deg, #c43e30 0%, #8c2419 100%);
        color: #fff8ec; border: none;
        height: 86px; font-size: 1.25rem; font-weight: 700;
        letter-spacing: 1.5px; font-family: 'Inter', sans-serif;
        border-radius: 16px;
        box-shadow:
            0 12px 28px -12px rgba(196, 62, 48, 0.65),
            inset 0 1px 0 rgba(255,255,255,0.18);
        transition: transform 0.12s ease, box-shadow 0.12s ease, opacity 0.15s ease;
    }
    .console-row [data-testid='column']:nth-of-type(2) button {
        background: linear-gradient(180deg, #4d5468 0%, #2c3142 100%);
        color: #f0f2f6; border: 1px solid rgba(255,255,255,0.08);
        height: 86px; font-size: 1.15rem; font-weight: 600;
        letter-spacing: 1.5px; font-family: 'Inter', sans-serif;
        border-radius: 16px;
        box-shadow: 0 8px 22px -10px rgba(0,0,0,0.6);
    }
    .console-row [data-testid='column']:nth-of-type(3) button {
        background: linear-gradient(180deg, #f0c453 0%, #c89427 100%);
        color: #1a1410; border: none;
        height: 110px; font-size: 1.55rem; font-weight: 700;
        letter-spacing: 2.0px; font-family: 'Inter', sans-serif;
        border-radius: 22px;
        box-shadow:
            0 18px 38px -16px rgba(242, 196, 78, 0.65),
            inset 0 1px 0 rgba(255,255,255,0.25);
    }
    .console-row button:hover:not(:disabled) {
        transform: translateY(-2px);
    }
    .console-row button:disabled {
        opacity: 0.32; cursor: not-allowed; transform: none !important;
    }
    .console-row button:active:not(:disabled) {
        transform: translateY(1px);
    }
    /* Button caption under each console button */
    .btn-caption {
        text-align: center; margin-top: 0.5rem;
        color: #9aa0b0; font-family: 'Inter', sans-serif;
        font-size: 0.78rem; letter-spacing: 1.2px;
        text-transform: uppercase;
    }

    /* Hide the audio_input widget visually but keep it interactive when
       RECORDING — we use it for the actual capture; the user-facing
       affordances are our styled RECORD / STOP buttons. */
    .compact-mic { opacity: 0.85; margin: 0.6rem auto 0; max-width: 520px; }
    .compact-mic [data-testid='stAudioInputDeleteBtn'] { display: none; }

    /* ── Floating diagnostics toggle (right edge) ────────────────── */
    .diag-toggle {
        position: fixed; right: 18px; top: 50%;
        transform: translateY(-50%); z-index: 1000;
        width: 56px; height: 56px; border-radius: 50%;
        background: rgba(28, 35, 52, 0.85);
        backdrop-filter: blur(6px);
        border: 1px solid rgba(242,196,78,0.45);
        display: flex; align-items: center; justify-content: center;
        cursor: pointer; transition: transform 0.18s, box-shadow 0.18s;
        box-shadow: 0 10px 24px -8px rgba(0,0,0,0.6);
    }
    .diag-toggle:hover {
        transform: translateY(-50%) scale(1.06);
        box-shadow: 0 12px 28px -8px rgba(242,196,78,0.45);
    }
    .diag-toggle svg { width: 28px; height: 28px; }
    .diag-label {
        position: fixed; right: 84px; top: 50%;
        transform: translateY(-50%); z-index: 1000;
        color: #f2c44e; font-family: 'Inter', sans-serif;
        font-size: 0.72rem; letter-spacing: 2px;
        text-transform: uppercase; pointer-events: none;
        opacity: 0.7;
    }

    /* ── Sidebar styled as a diagnostics drawer ──────────────────── */
    [data-testid='stSidebar'] {
        background: rgba(8, 11, 20, 0.92) !important;
        backdrop-filter: blur(16px);
        border-left: 1px solid rgba(242,196,78,0.18);
    }
    [data-testid='stSidebar'] .drawer-title {
        font-family: 'Cormorant Garamond', Georgia, serif;
        font-size: 1.5rem; color: #f6f1e1; font-weight: 600;
        margin: 0.4rem 0 0.8rem;
    }
    .drawer-card {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 0.7rem 0.9rem; margin-bottom: 0.6rem;
        font-family: 'Inter', sans-serif; font-size: 0.88rem;
        color: #d5dae6;
    }
    .drawer-card.success {
        border-color: rgba(74,210,149,0.35);
        background: rgba(74,210,149,0.06);
    }
    .drawer-card.routing {
        border-color: rgba(102,179,255,0.35);
        background: rgba(102,179,255,0.06);
    }
    .drawer-card .label {
        color: #9aa0b0; font-size: 0.72rem; letter-spacing: 1.5px;
        text-transform: uppercase; margin-bottom: 0.25rem; display: block;
    }
    .drawer-response {
        background: rgba(255, 255, 255, 0.025);
        border-left: 3px solid rgba(242,196,78,0.45);
        padding: 0.9rem 1.1rem; border-radius: 8px;
        font-family: 'Inter', sans-serif; font-size: 0.93rem;
        color: #e6e9ef; line-height: 1.55;
    }
    .drawer-empty {
        color: #6c7080; font-style: italic; padding: 1.2rem 0;
        text-align: center; font-family: 'Inter', sans-serif;
    }
    """
    css = css.replace("__BG_LAYER__", _bg_layer())
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


# ─── Status pill / glass panel ────────────────────────────────────────────
def _status_label(state: str) -> str:
    return {
        "IDLE":       "Ready",
        "RECORDING":  "Listening…",
        "PROCESSING": "Processing…",
        "READY":      "Response ready",
    }.get(state, state)


def _render_glass_panel(state: str) -> None:
    """Render the central glass panel: status pill, robot, title block."""
    if _ROBOT_DATA_URL:
        robot_html = f"<img src='{_ROBOT_DATA_URL}' alt='Reachy Mini Curious'/>"
    else:
        # Flatten the SVG to one line so Streamlit's markdown processor
        # doesn't treat its indentation as a code block.
        robot_html = " ".join(
            line.strip() for line in REACHY_CURIOUS_SVG.splitlines() if line.strip()
        )

    panel = (
        f"<div class='museum-glass {state.lower()}'>"
        f"  <span class='status-pill {state}'>"
        f"    <span class='dot'></span>{_status_label(state)}"
        f"  </span>"
        f"  <div class='robot-frame'>{robot_html}</div>"
        f"  <div style='text-align:center; margin-top:0.6rem;'>"
        f"    <h1 class='museum-title'>⚖️ With Due Respect</h1>"
        f"    <p class='museum-subtitle'>Reachy Mini × retired Chief Justice "
        f"      Artemio V. Panganiban</p>"
        f"    <p class='museum-blurb'>"
        f"      Ask the Chief Justice a question. Press <b>RECORD</b> when you "
        f"      are ready to speak, <b>STOP</b> when you are finished, and "
        f"      <b>PLAY</b> to hear his answer."
        f"    </p>"
        f"  </div>"
        f"</div>"
    )
    # Single-line, no leading whitespace per line — bypasses Streamlit's
    # indented-code-block treatment.
    panel = " ".join(line.strip() for line in panel.splitlines() if line.strip())
    st.markdown(panel, unsafe_allow_html=True)


# ─── Diagnostics drawer (sidebar) ─────────────────────────────────────────
def _render_drawer() -> None:
    """Populate the sidebar with the diagnostics drawer. The sidebar is
    Streamlit's native slide-out panel; we style it to feel like a
    floating drawer per the reference image."""
    ss = st.session_state
    with st.sidebar:
        st.markdown(
            "<p class='drawer-title'>🔍 Pipeline details</p>",
            unsafe_allow_html=True,
        )

        if not ss.transcript and ss.kiosk_state == "IDLE":
            st.markdown(
                "<p class='drawer-empty'>No turn yet. Record a question to "
                "populate this panel.</p>",
                unsafe_allow_html=True,
            )
            return

        # Transcription card
        if ss.transcript:
            st.markdown(
                "<div class='drawer-card success'>"
                "<span class='label'>✓ 🎧 Transcribed</span>"
                f"<div>{_safe_html(ss.transcript)}</div>"
                "</div>",
                unsafe_allow_html=True,
            )

        # Scope card
        if ss.gate:
            scope = ss.gate.get("scope", "—")
            st.markdown(
                "<div class='drawer-card success'>"
                f"<span class='label'>✓ 🚪 Scope: {_safe_html(scope)}</span>"
                f"<div>{_safe_html(ss.gate.get('reasoning', ''))}</div>"
                "</div>",
                unsafe_allow_html=True,
            )

        # Routing card
        if ss.routing:
            primary = ss.routing.get("primary_topic", "—")
            conf = ss.routing.get("confidence", "—")
            secs = ss.routing.get("secondary_topics", []) or []
            sec_html = (
                "<div style='margin-top:0.3rem; color:#9aa0b0;'>Secondary: " +
                ", ".join(f"<code>{_safe_html(t)}</code>" for t in secs) +
                "</div>"
            ) if secs else ""
            st.markdown(
                "<div class='drawer-card routing'>"
                f"<span class='label'>✓ 🧭 Routed to {_safe_html(primary)} "
                f"({_safe_html(conf)})</span>"
                f"<div style='color:#c1c7d6; font-style:italic;'>"
                f"{_safe_html(ss.routing.get('reasoning', ''))}</div>"
                f"{sec_html}"
                "</div>",
                unsafe_allow_html=True,
            )

        # Fidelity card
        if ss.fidelity:
            flags = [k for k in ("hallucination", "voice_drift", "guardrail_violation")
                     if ss.fidelity.get(k)]
            if flags:
                st.markdown(
                    "<div class='drawer-card' style='border-color:rgba(217,127,95,0.45); "
                    "background:rgba(217,127,95,0.06);'>"
                    f"<span class='label'>⚠ Fidelity: {', '.join(flags)}</span>"
                    f"<div style='color:#d5dae6;'>{_safe_html(ss.fidelity.get('reasoning', ''))}</div>"
                    "</div>",
                    unsafe_allow_html=True,
                )

        # TTS card
        if ss.tts_meta:
            if ss.tts_meta.get("ok"):
                st.markdown(
                    "<div class='drawer-card'>"
                    "<span class='label'>🔊 TTS</span>"
                    f"<div>{ss.tts_meta.get('chunks', '?')} sentence chunk(s) · "
                    f"~${ss.tts_meta.get('cost_usd', 0):.4f}</div>"
                    "</div>",
                    unsafe_allow_html=True,
                )

        # Full response card
        if ss.response:
            st.markdown(
                "<p style='color:#9aa0b0; font-family:Inter; font-size:0.78rem; "
                "letter-spacing:1.5px; text-transform:uppercase; margin:1.2rem 0 0.4rem;'>"
                "💬 CJ"
                "</p>"
                "<div class='drawer-response'>" + _safe_html(ss.response) + "</div>",
                unsafe_allow_html=True,
            )

        # Errors
        if ss.error:
            st.markdown(
                "<div class='drawer-card' style='border-color:#d97f5f; "
                "background:rgba(217,127,95,0.08); color:#d97f5f;'>"
                "<span class='label'>⚠ Error</span>"
                f"<div>{_safe_html(ss.error)}</div>"
                "</div>",
                unsafe_allow_html=True,
            )


def _safe_html(s: str) -> str:
    """Minimal HTML escape so model text doesn't break the drawer."""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ─── Diagnostic toggle icon ───────────────────────────────────────────────
def _render_diag_toggle() -> None:
    """Floating round button on the right edge. Clicking it expands the
    Streamlit sidebar (drawer) by flipping a session_state flag. The
    sidebar's visual open/close is handled by Streamlit; we just write
    a hint label next to the icon."""
    # The icon is a stylised legal-document with a magnifying glass.
    icon_svg = """
    <svg viewBox='0 0 64 64' xmlns='http://www.w3.org/2000/svg'>
      <rect x='14' y='10' width='28' height='38' rx='3'
            fill='#f2c44e' stroke='#1a1410' stroke-width='2'/>
      <line x1='18' y1='20' x2='38' y2='20' stroke='#1a1410' stroke-width='1.5'/>
      <line x1='18' y1='26' x2='38' y2='26' stroke='#1a1410' stroke-width='1.5'/>
      <line x1='18' y1='32' x2='32' y2='32' stroke='#1a1410' stroke-width='1.5'/>
      <circle cx='42' cy='42' r='10' fill='none'
              stroke='#f6f1e1' stroke-width='3'/>
      <line x1='49' y1='49' x2='56' y2='56'
            stroke='#f6f1e1' stroke-width='3' stroke-linecap='round'/>
    </svg>
    """
    icon_svg = " ".join(line.strip() for line in icon_svg.splitlines() if line.strip())
    st.markdown(
        f"<div class='diag-toggle' title='Open pipeline diagnostics'>{icon_svg}</div>"
        "<div class='diag-label'>↳ open the<br/>sidebar</div>",
        unsafe_allow_html=True,
    )


# ─── Pipeline ─────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _get_artifacts() -> "CorpusArtifacts":
    return CorpusArtifacts()


@st.cache_resource(show_spinner=False)
def _get_client():
    return make_client()


def _run_pipeline(audio_bytes: bytes) -> None:
    """Full PROCESSING path. Mutates st.session_state with results."""
    ss = st.session_state
    ss.error = None
    ss.transcript = ""
    ss.response = ""
    ss.audio_bytes = None
    ss.routing = None
    ss.gate = None
    ss.fidelity = None
    ss.tts_meta = None

    # 1. Persist audio to a temp WAV the OpenAI SDK can open.
    wav_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            wav_path = tmp.name

        # 2. STT (one Whisper call).
        try:
            transcript = transcribe_openai(wav_path)
        except Exception as e:
            ss.error = f"Transcription failed: {type(e).__name__}: {e}"
            return
        if not transcript.strip():
            ss.error = "No speech detected — please try again."
            return
        ss.transcript = transcript.strip()

        # 3. Input gate + routing.
        artifacts = _get_artifacts()
        client = _get_client()
        try:
            gate = input_gate(client, ss.transcript)
        except Exception as e:
            ss.error = f"Input gate failed: {type(e).__name__}: {e}"
            return
        ss.gate = gate

        if gate.get("scope") == "identity_probe":
            routing = force_meta_routing(gate.get("reasoning", ""))
        else:
            try:
                routing = route_question(client, ss.transcript, artifacts)
            except Exception as e:
                ss.error = f"Routing failed: {type(e).__name__}: {e}"
                return
        ss.routing = routing

        # 4. Compose (streamed but accumulated server-side — we don't
        # progressively reveal text in the kiosk view; the response is
        # spoken when the user presses PLAY).
        try:
            context = build_context(routing, artifacts)
            chunks = []
            for piece in generate_response_stream(
                client, ss.transcript, routing, artifacts, conversation_history=None
            ):
                chunks.append(piece)
            response_raw = "".join(chunks)
        except Exception as e:
            ss.error = f"Composer failed: {type(e).__name__}: {e}"
            return
        ss.response = _strip_stage_directions(response_raw)

        # 5. Fidelity (advisory).
        try:
            ss.fidelity = fidelity_check(client, context, ss.response)
        except Exception:
            ss.fidelity = None  # non-fatal

        # 6. TTS (per-sentence parallel; one autoplay MP3 ready to play).
        try:
            ss.audio_bytes = tts_concatenate_parallel(ss.response)
            cost = estimate_voice_cost(ss.response)
            ss.tts_meta = {
                "ok": True,
                "chunks": len(sentence_chunks(ss.response)),
                "cost_usd": cost["tts_usd"],
            }
        except Exception as e:
            ss.tts_meta = {"ok": False, "error": str(e)[:200]}

        ss.kiosk_state = "READY"
        ss.autoplay_pending = True
    finally:
        if wav_path:
            try:
                os.unlink(wav_path)
            except OSError:
                pass


# ─── Console (button row) ─────────────────────────────────────────────────
def _render_console(state: str) -> tuple[bool, bool, bool]:
    """Three-column physical console. Returns (record, stop, play) click flags."""
    st.markdown("<div class='console-row'>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1, 1.4], gap="large")

    with col1:
        record_clicked = st.button(
            "⏺  RECORD",
            key="btn_record",
            disabled=state in {"RECORDING", "PROCESSING"},
            use_container_width=True,
        )
        st.markdown("<div class='btn-caption'>start your question</div>",
                    unsafe_allow_html=True)

    with col2:
        stop_clicked = st.button(
            "⏹  STOP",
            key="btn_stop",
            disabled=state != "RECORDING",
            use_container_width=True,
        )
        st.markdown("<div class='btn-caption'>cancel recording</div>",
                    unsafe_allow_html=True)

    with col3:
        play_clicked = st.button(
            "▶  PLAY",
            key="btn_play",
            disabled=state != "READY",
            use_container_width=True,
        )
        st.markdown("<div class='btn-caption'>🎧 hear the response</div>",
                    unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)
    return record_clicked, stop_clicked, play_clicked


def _autoplay_audio(audio_bytes: bytes) -> None:
    """Iframe-embedded HTML5 audio element with autoplay + a JS shim
    that calls .play() on `loadeddata` for browsers with strict
    autoplay policies. Sandbox iframe also bypasses Streamlit's
    Markdown sanitizer (which strips <script> tags)."""
    import streamlit.components.v1 as components
    b64 = base64.b64encode(audio_bytes).decode("ascii")
    components.html(
        (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<style>html,body{margin:0;padding:0;background:transparent;}"
            "audio{width:100%;max-width:560px;display:block;margin:0.4rem auto;}"
            "</style></head><body>"
            f"<audio id='a' autoplay controls src='data:audio/mp3;base64,{b64}'></audio>"
            "<script>(function(){"
            " const a=document.getElementById('a'); if(!a) return;"
            " const tryPlay=()=>{a.play().catch(()=>{});};"
            " if(a.readyState>=2) tryPlay();"
            " else a.addEventListener('loadeddata',tryPlay,{once:true});"
            "})();</script></body></html>"
        ),
        height=80,
    )


# ─── Main flow ────────────────────────────────────────────────────────────
def main() -> None:
    _inject_css()
    _preflight()
    _init_state()
    ss = st.session_state

    # Glass panel (header + robot + status pill)
    _render_glass_panel(ss.kiosk_state)

    # Three-button console
    record_clicked, stop_clicked, play_clicked = _render_console(ss.kiosk_state)

    # The audio_input widget is the actual mic capture surface. We show
    # it only while RECORDING so visitors aren't confused by an extra
    # control in the IDLE state.
    if ss.kiosk_state == "RECORDING":
        st.markdown("<div class='compact-mic'>", unsafe_allow_html=True)
        audio_in = st.audio_input(
            "Speak now — press the stop button on the recorder when done.",
            key=f"mic_{ss.mic_key}",
        )
        st.markdown("</div>", unsafe_allow_html=True)
        if audio_in is not None:
            audio_bytes = audio_in.getvalue()
            if audio_bytes and len(audio_bytes) > 1024:
                ss.kiosk_state = "PROCESSING"
                ss._pending_audio = audio_bytes
                st.rerun()

    # PROCESSING — run the pipeline once, then transition to READY.
    if ss.kiosk_state == "PROCESSING":
        pending = ss.pop("_pending_audio", None) if "_pending_audio" in ss else None
        if pending is None:
            # Defensive: nothing to process; bounce back to IDLE.
            ss.kiosk_state = "IDLE"
            st.rerun()
        with st.spinner("✨ The Chief Justice is composing his answer…"):
            _run_pipeline(pending)
        if ss.error:
            # On hard error, surface it and reset.
            st.error(ss.error)
            ss.kiosk_state = "IDLE"
        st.rerun()

    # READY — auto-play once, then keep PLAY button available for replay.
    if ss.kiosk_state == "READY" and ss.audio_bytes:
        if ss.autoplay_pending:
            _autoplay_audio(ss.audio_bytes)
            ss.autoplay_pending = False

    # Button transitions
    if record_clicked:
        # Bump the mic key so the audio_input widget renders fresh.
        ss.mic_key += 1
        ss.kiosk_state = "RECORDING"
        st.rerun()
    if stop_clicked:
        ss.kiosk_state = "IDLE"
        ss.mic_key += 1
        st.rerun()
    if play_clicked and ss.audio_bytes:
        _autoplay_audio(ss.audio_bytes)

    # Floating diagnostics icon (visual cue; the sidebar is the actual
    # drawer — Streamlit's collapse / expand arrow on the top-left).
    _render_diag_toggle()

    # Sidebar always holds the current diagnostic state; visitors leave
    # it collapsed, curators expand it via Streamlit's `>>` toggle.
    _render_drawer()


if __name__ == "__main__":
    main()
