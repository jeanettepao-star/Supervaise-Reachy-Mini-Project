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
    # Running API cost (USD) — updated after every successful turn
    ss.setdefault("session_cost", 0.0)
    ss.setdefault("last_turn_cost", 0.0)
    ss.setdefault("turn_count", 0)


# Anthropic per-token prices, $/MTok — mirrors cj_chat.cache_savings_summary
_ANTHROPIC_PRICES = {
    # (regular_input, cache_write_1.25x, cache_read_0.1x, output)
    "router":    (1.00, 1.25, 0.10, 5.00),   # Haiku 4.5
    "inference": (3.00, 3.75, 0.30, 15.00),  # Sonnet 4.6
}


def _snapshot_cache_stats() -> dict:
    """Deep-copy CACHE_STATS so we can diff before / after the pipeline."""
    from cj_chat import CACHE_STATS
    return {label: dict(stats) for label, stats in CACHE_STATS.items()}


def _anthropic_cost_since(before: dict) -> float:
    """Total Anthropic spend (USD) since the `before` snapshot."""
    from cj_chat import CACHE_STATS
    cost = 0.0
    for label, after in CACHE_STATS.items():
        p_in, p_w, p_r, p_out = _ANTHROPIC_PRICES[label]
        b = before.get(label, {})
        delta_in    = after["regular_input"] - b.get("regular_input", 0)
        delta_w     = after["creation"]      - b.get("creation", 0)
        delta_r     = after["read"]          - b.get("read", 0)
        delta_o     = after["output"]        - b.get("output", 0)
        cost += (delta_in * p_in + delta_w * p_w
                 + delta_r * p_r + delta_o * p_out) / 1e6
    return cost


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
        padding-top: 0.6rem !important;
        padding-bottom: 0.8rem !important;
        max-width: 1280px;
    }

    /* ── Full-screen gallery background ──────────────────────────── */
    .stApp { __BG_LAYER__ color: #e6e9ef; }

    /* ── Central glass panel ─────────────────────────────────────── */
    .museum-glass {
        position: relative;
        margin: 0.6rem auto 0.4rem;
        padding: 1.0rem 1.8rem 1.0rem;
        max-width: 960px;
        border-radius: 24px;
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
        position: absolute; left: 0; right: 0; top: 0; height: 55px;
        background: linear-gradient(180deg,
            rgba(255,255,255,0.10), rgba(255,255,255,0.0));
        pointer-events: none;
    }

    /* ── Title typography ────────────────────────────────────────── */
    .museum-title {
        font-family: 'Cormorant Garamond', Georgia, serif;
        font-size: 2.2rem; line-height: 1.0;
        font-weight: 600; letter-spacing: 0.5px;
        color: #f6f1e1; margin: 0;
    }
    .museum-subtitle {
        font-family: 'Inter', sans-serif;
        font-size: 0.88rem; color: #c1c7d6; font-style: italic;
        margin: 0.3rem 0 0; letter-spacing: 0.2px;
    }
    .museum-blurb {
        font-family: 'Inter', sans-serif;
        font-size: 0.78rem; color: #b5bbcb;
        margin: 0.6rem auto 0;
        line-height: 1.4;
        letter-spacing: 0.2px;
        white-space: nowrap;       /* keep on a single line */
        overflow: hidden;          /* never wrap onto a 2nd line on narrow viewports */
        text-overflow: ellipsis;
    }
    /* Running cost pill — bottom-right corner of glass panel */
    .cost-pill {
        position: absolute; bottom: 14px; right: 22px;
        display: inline-flex; align-items: center; gap: 0.45rem;
        padding: 0.32rem 0.8rem; border-radius: 999px;
        background: rgba(15, 19, 32, 0.65);
        border: 1px solid rgba(242, 196, 78, 0.35);
        color: #f2c44e; font-family: 'Inter', sans-serif;
        font-size: 0.72rem; font-weight: 600; letter-spacing: 1.0px;
    }
    .cost-pill .cost-sep {
        opacity: 0.45; margin: 0 0.05rem;
    }
    .cost-pill .cost-label {
        color: #9aa0b0; font-weight: 500;
        text-transform: uppercase; letter-spacing: 1.5px;
        font-size: 0.66rem;
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
        padding: 0.2rem 0 0.2rem;
    }
    .robot-frame svg, .robot-frame img {
        height: 200px; width: auto;
        filter: drop-shadow(0 14px 20px rgba(0,0,0,0.45));
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
        height: 64px; font-size: 1.05rem; font-weight: 700;
        letter-spacing: 1.5px; font-family: 'Inter', sans-serif;
        border-radius: 14px;
        box-shadow:
            0 10px 22px -10px rgba(196, 62, 48, 0.65),
            inset 0 1px 0 rgba(255,255,255,0.18);
        transition: transform 0.12s ease, box-shadow 0.12s ease, opacity 0.15s ease;
    }
    .console-row [data-testid='column']:nth-of-type(2) button {
        background: linear-gradient(180deg, #4d5468 0%, #2c3142 100%);
        color: #f0f2f6; border: 1px solid rgba(255,255,255,0.08);
        height: 64px; font-size: 1.0rem; font-weight: 600;
        letter-spacing: 1.5px; font-family: 'Inter', sans-serif;
        border-radius: 14px;
        box-shadow: 0 8px 20px -10px rgba(0,0,0,0.6);
    }
    .console-row [data-testid='column']:nth-of-type(3) button {
        background: linear-gradient(180deg, #f0c453 0%, #c89427 100%);
        color: #1a1410; border: none;
        height: 78px; font-size: 1.25rem; font-weight: 700;
        letter-spacing: 2.0px; font-family: 'Inter', sans-serif;
        border-radius: 18px;
        box-shadow:
            0 14px 30px -14px rgba(242, 196, 78, 0.65),
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

    /* ── Hide Streamlit's native sidebar entirely. ───────────────── */
    [data-testid='stSidebar'],
    [data-testid='collapsedControl'],
    [data-testid='stSidebarCollapsedControl'] {
        display: none !important;
    }

    /* ── Inline progress dropdown — st.status + st.expander styling
       so the live progress block looks part of the museum console
       (dark glass, gold-accented border, Inter body type). ────── */
    .progress-shell {
        max-width: 820px; margin: 1.0rem auto 0;
        font-family: 'Inter', sans-serif;
    }
    /* st.status / st.expander wrappers — Streamlit renders both
       through the StatusWidget / Expander testids. */
    [data-testid='stStatusWidget'],
    [data-testid='stExpander'] {
        background: rgba(255, 255, 255, 0.04) !important;
        backdrop-filter: blur(10px) saturate(130%);
        border: 1px solid rgba(255, 255, 255, 0.10) !important;
        border-radius: 14px !important;
        box-shadow: 0 10px 28px -16px rgba(0, 0, 0, 0.55);
    }
    /* Expander header — slightly gold-tinted to flag it as the
       diagnostic surface. */
    [data-testid='stExpander'] summary {
        font-family: 'Inter', sans-serif;
        font-weight: 600; color: #f2c44e !important;
        letter-spacing: 0.6px;
    }
    /* Inline progress cards rendered by st.markdown inside the
       status block. */
    .progress-card {
        display: flex; align-items: flex-start; gap: 0.55rem;
        padding: 0.55rem 0.8rem; margin: 0.35rem 0;
        background: rgba(255,255,255,0.025);
        border: 1px solid rgba(255,255,255,0.07);
        border-radius: 10px;
        font-size: 0.9rem; color: #d5dae6;
    }
    .progress-card.success {
        border-color: rgba(74,210,149,0.35);
        background: rgba(74,210,149,0.05);
    }
    .progress-card.routing {
        border-color: rgba(102,179,255,0.35);
        background: rgba(102,179,255,0.05);
    }
    .progress-card .pc-check {
        color: #4ad295; font-weight: 600; flex-shrink: 0;
    }
    .progress-card .pc-label {
        color: #9aa0b0; font-size: 0.72rem; letter-spacing: 1.2px;
        text-transform: uppercase; margin-right: 0.4rem;
    }
    .progress-card .pc-body {
        flex: 1; line-height: 1.5;
    }
    .progress-response {
        margin-top: 0.5rem; padding: 0.85rem 1.05rem;
        background: rgba(255,255,255,0.02);
        border-left: 3px solid rgba(242, 196, 78, 0.55);
        border-radius: 8px;
        font-size: 0.93rem; color: #e6e9ef; line-height: 1.6;
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
    """Render the central glass panel: status pill, robot, title block,
    + running-cost pill in the bottom-right corner."""
    ss = st.session_state
    if _ROBOT_DATA_URL:
        robot_html = f"<img src='{_ROBOT_DATA_URL}' alt='Reachy Mini Curious'/>"
    else:
        # Flatten the SVG to one line so Streamlit's markdown processor
        # doesn't treat its indentation as a code block.
        robot_html = " ".join(
            line.strip() for line in REACHY_CURIOUS_SVG.splitlines() if line.strip()
        )

    # Cost pill HTML — only rendered after the first turn so the IDLE
    # surface stays clean for the first visitor.
    cost_html = ""
    if ss.get("turn_count", 0) > 0:
        cost_html = (
            f"<span class='cost-pill' title='Estimated API spend "
            f"(Anthropic chat + OpenAI STT + OpenAI TTS)'>"
            f"<span class='cost-label'>Turn</span>"
            f"${ss.last_turn_cost:.4f}"
            f"<span class='cost-sep'>·</span>"
            f"<span class='cost-label'>Session</span>"
            f"${ss.session_cost:.4f}"
            f"</span>"
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
        f"      Ask the Chief Justice a question. Press <b>START</b> to "
        f"speak, <b>STOP</b> when finished."
        f"    </p>"
        f"  </div>"
        f"  {cost_html}"
        f"</div>"
    )
    # Single-line, no leading whitespace per line — bypasses Streamlit's
    # indented-code-block treatment.
    panel = " ".join(line.strip() for line in panel.splitlines() if line.strip())
    st.markdown(panel, unsafe_allow_html=True)


# ─── Inline progress dropdown (replaces the slide-in drawer) ─────────────
# Two surfaces share the same dataset:
#   • during PROCESSING: a st.status() block opens auto-expanded and
#     receives a step-by-step .update(label=…) + st.markdown lines as
#     the pipeline runs — the visitor watches each ✓ land live.
#   • during READY (and beyond): a st.expander() that's collapsed by
#     default, holding the cached cards for inspection on the visitor's
#     terms.
# Both consume the same _render_cards(ss) helper so the cards look
# identical whether they're rendering live or from cached state.

# ── Per-card renderers ────────────────────────────────────────────────────
# Each card has its OWN render function. During the live pipeline run
# we call only the card that just became available, so the dropdown
# stacks cleanly (no duplicates). The aggregate `_render_cards()`
# wrapper calls them all in order for the post-completion expander.

def _card_transcribed(ss) -> None:
    if not ss.transcript:
        return
    st.markdown(
        "<div class='progress-card success'>"
        "<span class='pc-check'>✓</span>"
        "<div class='pc-body'>"
        "<span class='pc-label'>🎧 Transcribed</span>"
        f"{_safe_html(ss.transcript)}"
        "</div></div>",
        unsafe_allow_html=True,
    )


def _card_scope(ss) -> None:
    if not ss.gate:
        return
    reason = ss.gate.get("reasoning", "")
    st.markdown(
        "<div class='progress-card success'>"
        "<span class='pc-check'>✓</span>"
        "<div class='pc-body'>"
        f"<span class='pc-label'>🚪 Scope</span>"
        f"<code>{_safe_html(ss.gate.get('scope', '—'))}</code>"
        + (f" — <span style='color:#9aa0b0;'>"
           f"{_safe_html(reason)}</span>" if reason else "")
        + "</div></div>",
        unsafe_allow_html=True,
    )


def _card_routing(ss) -> None:
    if not ss.routing:
        return
    primary = ss.routing.get("primary_topic", "—")
    conf = ss.routing.get("confidence", "—")
    reason = ss.routing.get("reasoning", "")
    st.markdown(
        "<div class='progress-card routing'>"
        "<span class='pc-check'>✓</span>"
        "<div class='pc-body'>"
        f"<span class='pc-label'>🧭 Routed</span>"
        f"<code>{_safe_html(primary)}</code> "
        f"<span style='color:#66b3ff;'>({_safe_html(conf)})</span>"
        + (f"<div style='color:#9aa0b0; font-size:0.82rem; "
           f"margin-top:0.2rem;'>{_safe_html(reason)}</div>"
           if reason else "")
        + "</div></div>",
        unsafe_allow_html=True,
    )


def _card_fidelity(ss) -> None:
    if not ss.fidelity:
        return
    flags = [k for k in ("hallucination", "voice_drift", "guardrail_violation")
             if ss.fidelity.get(k)]
    if not flags:
        return
    st.markdown(
        "<div class='progress-card' style='border-color:rgba(217,127,95,0.45); "
        "background:rgba(217,127,95,0.05);'>"
        "<span class='pc-check' style='color:#d97f5f;'>⚠</span>"
        "<div class='pc-body'>"
        f"<span class='pc-label'>🛡️ Fidelity</span>"
        f"{', '.join(flags)} — "
        f"<span style='color:#f2c4ad;'>"
        f"{_safe_html(ss.fidelity.get('reasoning', ''))}</span>"
        "</div></div>",
        unsafe_allow_html=True,
    )


def _card_response(ss) -> None:
    if not ss.response:
        return
    st.markdown(
        "<div style='color:#9aa0b0; font-size:0.72rem; "
        "letter-spacing:1.5px; text-transform:uppercase; "
        "margin: 0.9rem 0 0.4rem;'>💬 CJ</div>"
        f"<div class='progress-response'>{_safe_html(ss.response)}</div>",
        unsafe_allow_html=True,
    )


def _card_spend(ss) -> None:
    if ss.get("turn_count", 0) <= 0:
        return
    br = (ss.tts_meta or {}).get("breakdown", {})
    st.markdown(
        "<div class='progress-card' style='margin-top:0.7rem;'>"
        "<span class='pc-check' style='color:#f2c44e;'>💰</span>"
        "<div class='pc-body'>"
        "<span class='pc-label'>API spend</span>"
        "<div style='display:grid; grid-template-columns:auto auto; "
        "gap:0.15rem 0.9rem; font-size:0.85rem; margin-top:0.25rem;'>"
        f"<span style='color:#9aa0b0;'>Anthropic chat</span>"
        f"<span>${br.get('anthropic_usd', 0):.5f}</span>"
        f"<span style='color:#9aa0b0;'>OpenAI Whisper STT</span>"
        f"<span>${br.get('stt_usd', 0):.5f}</span>"
        f"<span style='color:#9aa0b0;'>OpenAI TTS</span>"
        f"<span>${br.get('tts_usd', 0):.5f}</span>"
        f"<span style='color:#f2c44e; font-weight:600; "
        f"padding-top:0.25rem; "
        f"border-top:1px solid rgba(242,196,78,0.25);'>This turn</span>"
        f"<span style='color:#f2c44e; font-weight:600; "
        f"padding-top:0.25rem; "
        f"border-top:1px solid rgba(242,196,78,0.25);'>"
        f"${ss.last_turn_cost:.5f}</span>"
        f"<span style='color:#f2c44e; font-weight:600;'>Session</span>"
        f"<span style='color:#f2c44e; font-weight:600;'>"
        f"${ss.session_cost:.4f}</span>"
        "</div></div></div>",
        unsafe_allow_html=True,
    )


def _card_error(ss) -> None:
    if not ss.error:
        return
    st.markdown(
        "<div class='progress-card' style='border-color:#d97f5f; "
        "background:rgba(217,127,95,0.08);'>"
        "<span class='pc-check' style='color:#d97f5f;'>⚠</span>"
        "<div class='pc-body'>"
        "<span class='pc-label'>Error</span>"
        f"<span style='color:#f2c4ad;'>{_safe_html(ss.error)}</span>"
        "</div></div>",
        unsafe_allow_html=True,
    )


def _render_cards(ss) -> None:
    """Aggregate renderer — calls every per-card helper in order. Used by
    the READY-state expander so the cached state of the last turn is
    visible the moment a visitor expands it. NOT used during PROCESSING
    (the live pipeline calls each _card_* once at the point its data
    becomes available — calling _render_cards() repeatedly mid-pipeline
    would render each card multiple times in the status block)."""
    _card_transcribed(ss)
    _card_scope(ss)
    _card_routing(ss)
    _card_fidelity(ss)
    _card_response(ss)
    _card_spend(ss)
    _card_error(ss)


def _safe_html(s: str) -> str:
    """Minimal HTML escape so model text doesn't break the drawer."""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ─── Pipeline ─────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _get_artifacts() -> "CorpusArtifacts":
    return CorpusArtifacts()


@st.cache_resource(show_spinner=False)
def _get_client():
    return make_client()


def _run_pipeline(audio_bytes: bytes) -> None:
    """Full PROCESSING path with LIVE progress updates.

    The pipeline runs inside a st.status() block opened by the caller's
    progress dropdown. Between each stage we call `status.update(label=…)`
    to advance the dropdown header AND call the matching per-card
    helper (`_card_transcribed`, `_card_scope`, `_card_routing`, …) so
    each completed step's card appears beneath the spinner immediately —
    visitors literally watch the checkmarks land. We never call
    `_render_cards()` mid-pipeline; that would re-render every card
    already on screen.

    Tracks per-turn API spend in `last_turn_cost` and accumulates into
    `session_cost`. The cost includes:
      • Anthropic (router + gate + composer + fidelity) — computed from
        CACHE_STATS diff with the published $/MTok rates.
      • OpenAI Whisper STT — estimated at $0.006/min × audio duration.
      • OpenAI TTS — actual chars × tts-1 rate (from estimate_voice_cost).
    """
    ss = st.session_state
    ss.error = None
    ss.transcript = ""
    ss.response = ""
    ss.audio_bytes = None
    ss.routing = None
    ss.gate = None
    ss.fidelity = None
    ss.tts_meta = None

    cache_before = _snapshot_cache_stats()
    audio_seconds_est = max(1, len(audio_bytes) // 32000)  # ≈ 16 kHz × 2 bytes
    stt_cost = (audio_seconds_est / 60.0) * 0.006

    # Open the live progress dropdown. The status block is the
    # "drop-down area" the user wanted: auto-expanded during work,
    # each step lands as a checkmark card the moment the underlying
    # API returns, then collapses to a single "✓ Response ready" line
    # when done. Streamlit flushes each st.markdown call inside this
    # block immediately to the browser, so progress is genuinely live.
    status_ctx = st.status(
        "✨ The Chief Justice is preparing his answer…",
        expanded=True,
    )

    wav_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            wav_path = tmp.name

        with status_ctx as status:
            # ── 1. STT ──
            status.update(label="🎧 Transcribing your question…")
            try:
                transcript = transcribe_openai(wav_path)
            except Exception as e:
                ss.error = f"Transcription failed: {type(e).__name__}: {e}"
                _card_error(ss)
                status.update(label="✗ Transcription failed", state="error",
                              expanded=True)
                return
            if not transcript.strip():
                ss.error = "No speech detected — please try again."
                _card_error(ss)
                status.update(label="✗ No speech detected", state="error",
                              expanded=True)
                return
            ss.transcript = transcript.strip()
            _card_transcribed(ss)   # render JUST the new card

            # ── 2. Input gate ──
            status.update(label="🚪 Checking question scope…")
            artifacts = _get_artifacts()
            client = _get_client()
            try:
                ss.gate = input_gate(client, ss.transcript)
            except Exception as e:
                ss.error = f"Input gate failed: {type(e).__name__}: {e}"
                _card_error(ss)
                status.update(label="✗ Input gate failed", state="error",
                              expanded=True)
                return
            _card_scope(ss)         # render JUST the new card

            # ── 3. Topic routing ──
            status.update(label="🧭 Routing to corpus topic…")
            if ss.gate.get("scope") == "identity_probe":
                ss.routing = force_meta_routing(ss.gate.get("reasoning", ""))
            else:
                try:
                    ss.routing = route_question(client, ss.transcript, artifacts)
                except Exception as e:
                    ss.error = f"Routing failed: {type(e).__name__}: {e}"
                    _card_error(ss)
                    status.update(label="✗ Routing failed", state="error",
                                  expanded=True)
                    return
            _card_routing(ss)       # render JUST the new card

            # ── 4. Compose ──
            status.update(label="💭 Composing the Chief Justice's reply…")
            try:
                context = build_context(ss.routing, artifacts)
                response_raw = "".join(
                    generate_response_stream(
                        client, ss.transcript, ss.routing, artifacts,
                        conversation_history=None,
                    )
                )
            except Exception as e:
                ss.error = f"Composer failed: {type(e).__name__}: {e}"
                _card_error(ss)
                status.update(label="✗ Composer failed", state="error",
                              expanded=True)
                return
            ss.response = _strip_stage_directions(response_raw)

            # ── 5. Fidelity (advisory) ──
            try:
                ss.fidelity = fidelity_check(client, context, ss.response)
            except Exception:
                ss.fidelity = None
            _card_fidelity(ss)      # only renders if a flag fired
            _card_response(ss)      # full CJ response text card

            # ── 6. TTS ──
            status.update(label="🔊 Generating the spoken response…")
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

            # ── 7. Cost rollup ──
            anthropic_cost = _anthropic_cost_since(cache_before)
            tts_cost = ss.tts_meta.get("cost_usd", 0.0) \
                       if ss.tts_meta and ss.tts_meta.get("ok") else 0.0
            turn_cost = anthropic_cost + stt_cost + tts_cost
            ss.last_turn_cost = turn_cost
            ss.session_cost += turn_cost
            ss.turn_count += 1
            if isinstance(ss.tts_meta, dict):
                ss.tts_meta["breakdown"] = {
                    "anthropic_usd": round(anthropic_cost, 5),
                    "stt_usd": round(stt_cost, 5),
                    "tts_usd": round(tts_cost, 5),
                    "turn_usd": round(turn_cost, 5),
                }

            _card_spend(ss)         # API spend breakdown

            # Keep the dropdown EXPANDED so cards stay visible after
            # completion. The visitor can collapse manually if they
            # want a clean canvas before the next turn.
            status.update(
                label=f"✓ Response ready — turn ${turn_cost:.4f} · "
                      f"session ${ss.session_cost:.4f}",
                state="complete",
                expanded=True,
            )

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
            "⏺  START",
            key="btn_record",
            disabled=state in {"RECORDING", "PROCESSING"},
            use_container_width=True,
        )
        st.markdown("<div class='btn-caption'>begin your question</div>",
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
    """Render an HTML5 audio element directly in the parent page so the
    browser's autoplay policy uses the parent's user-interaction
    context — by the time we get here, the visitor has clicked the
    START button and the audio_input's stop control, so autoplay is
    permitted.

    We use st.markdown (NOT st.components.v1.html) deliberately:
    components.html spawns a sandboxed iframe, and the autoplay
    permission doesn't propagate from the parent into a fresh iframe
    on every rerun. Putting the <audio autoplay> in the parent DOM
    inherits the visitor's interaction history and fires reliably.

    A small JS fallback is appended as a defensive .play() retry —
    Streamlit's HTML sanitiser strips <script> tags but DOES allow
    <audio> attributes through, so the autoplay attribute alone is
    typically enough.
    """
    b64 = base64.b64encode(audio_bytes).decode("ascii")
    st.markdown(
        f"<audio autoplay controls preload='auto' playsinline "
        f"style='width:100%; max-width:560px; display:block; "
        f"margin:0.6rem auto; outline:none; border-radius:8px;' "
        f"src='data:audio/mp3;base64,{b64}'></audio>",
        unsafe_allow_html=True,
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

    # PROCESSING — run the pipeline. _run_pipeline() now opens its
    # own st.status() block (the "live drop-down") and writes each
    # step's card into it the moment that step completes. The visitor
    # watches each ✓ land in real time; no spinner needed.
    if ss.kiosk_state == "PROCESSING":
        pending = ss.pop("_pending_audio", None) if "_pending_audio" in ss else None
        if pending is None:
            ss.kiosk_state = "IDLE"
            st.rerun()
        st.markdown("<div class='progress-shell'>", unsafe_allow_html=True)
        _run_pipeline(pending)
        st.markdown("</div>", unsafe_allow_html=True)
        if ss.error:
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

    # Inline pipeline-details dropdown. During PROCESSING the
    # st.status() inside _run_pipeline() is the live drop-down.
    # During READY (and onwards), a regular st.expander() carries
    # the cached cards. We default to expanded=True so the visitor
    # sees the full pipeline result on the screen they arrive at
    # after pressing STOP — same view they saw inside the live
    # status block, just persisted across the rerun.
    if ss.kiosk_state == "READY" and ss.transcript:
        st.markdown("<div class='progress-shell'>", unsafe_allow_html=True)
        with st.expander(
            f"🔍 Pipeline details — turn ${ss.last_turn_cost:.4f} · "
            f"session ${ss.session_cost:.4f}",
            expanded=True,
        ):
            _render_cards(ss)
        st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
