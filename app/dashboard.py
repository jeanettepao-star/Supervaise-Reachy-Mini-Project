"""Interactive chat dashboard for the CJ Panganiban conversation app.

This is the primary UI: a Streamlit chat app with both inputs (mic +
text) and both outputs (visible transcript + Piper-generated audio),
plus a Sources expander showing which canonical topics the router
matched.

Pipeline:
    faster-whisper (STT) → Claude Haiku (router) → Claude Sonnet (inference) → Piper (TTS)

faster-whisper is loaded lazily — only on the first mic recording, never
on dashboard startup. So opening the page is fast even before the model
is cached locally. Piper is loaded only when the TTS toggle is on AND
the binary is present on PATH (or via PIPER_BIN env var).

Run (from the repo root):
    app/.venv/Scripts/streamlit run app/dashboard.py

Or from the app/ directory:
    .venv/Scripts/streamlit run dashboard.py

Environment overrides (all optional):
    ANTHROPIC_API_KEY — required for router + composer calls.
    WHISPER_MODEL    — model size for faster-whisper (default "medium";
                       "small" is ~470 MB / ~5× faster on cold start,
                       still good for English. Use "medium" for
                       Filipino-mixed audio.)
    HF_HOME          — moves the HuggingFace download cache (where the
                       Whisper model lives) off C: drive.
                       Example: D:\\hf-cache.
    PIPER_BIN        — path to piper.exe if not on PATH.
    PIPER_VOICE      — path to the .onnx voice model.
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path

import streamlit as st

# Importing cj_chat triggers .env loading and Windows UTF-8 setup, so do it
# before any Anthropic / faster-whisper imports below.
sys.path.insert(0, str(Path(__file__).parent))
import cj_chat  # noqa: F401, E402
from cj_chat import (  # noqa: E402
    CorpusArtifacts,
    transcribe_audio,
    route_question,
    generate_response,
    generate_response_stream,
    build_context,
    fidelity_check,
    input_gate,
    force_meta_routing,
    _strip_stage_directions,
    synthesize_speech,
    _prepare_tts_text,
    make_client,
    cache_savings_summary,
    CACHE_STATS,
    TTS_SENTENCE_SILENCE,
    WHISPER_MODEL_SIZE,
    ARTIFACTS_DIR,
)
from anthropic import Anthropic, APIStatusError, APIConnectionError  # noqa: E402


# ----- Page chrome ---------------------------------------------------------
st.set_page_config(
    page_title="With Due Respect — CJ Panganiban",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
      .stApp { background: #0e1117; }
      .stChatMessage { font-size: 1.05rem; line-height: 1.55; }
      .source-meta { color: #9aa4b3; font-size: 0.88rem; }
      .topic-pill {
        display: inline-block; padding: 0.15rem 0.55rem; margin: 0.1rem 0.3rem 0.1rem 0;
        border-radius: 999px; font-size: 0.78rem; font-weight: 500;
      }
      .topic-primary   { background: #2d4ea8; color: #fff; }
      .topic-secondary { background: #2a3144; color: #c5cad6; }
      .conf-high   { color: #4ad295; font-weight: 600; }
      .conf-medium { color: #e6c149; font-weight: 600; }
      .conf-low    { color: #d97f5f; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ----- Cached resources (loaded once per Streamlit session) ----------------
@st.cache_resource(show_spinner="Loading corpus artifacts…")
def get_artifacts() -> CorpusArtifacts:
    return CorpusArtifacts(ARTIFACTS_DIR)


@st.cache_resource(show_spinner="Loading faster-whisper (first time downloads the model)…")
def get_whisper():
    from faster_whisper import WhisperModel
    return WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")


@st.cache_resource(show_spinner="Connecting to Claude…")
def get_client() -> Anthropic:
    # max_retries=4 inside make_client() so transient 529/429 errors get
    # retried automatically with exponential backoff before they bubble up.
    return make_client()


def get_tts_dir() -> Path:
    d = Path(__file__).parent / "state" / "tts"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ----- Session state -------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []  # list of {role, content, audio_path?, routing?}
if "last_audio_hash" not in st.session_state:
    st.session_state.last_audio_hash = None
if "mic_counter" not in st.session_state:
    st.session_state.mic_counter = 0
if "tts_enabled" not in st.session_state:
    st.session_state.tts_enabled = True


# ----- Sidebar -------------------------------------------------------------
with st.sidebar:
    st.markdown("### Settings")
    st.session_state.tts_enabled = st.checkbox(
        "Generate Piper voice", value=st.session_state.tts_enabled,
        help="When on, each response is also synthesized to audio. Adds ~5-10s/turn on CPU.",
    )
    st.session_state.show_tts_debug = st.checkbox(
        "Show TTS chunks (debug)", value=False,
        help="Show the per-line text Piper saw, marked where each "
             f"{TTS_SENTENCE_SILENCE}s pause is inserted.",
    )
    if st.button("🧹 Clear conversation"):
        st.session_state.messages = []
        st.session_state.last_audio_hash = None
        st.session_state.mic_counter += 1
        st.rerun()
    st.markdown("---")
    st.markdown(
        "**Pipeline**: faster-whisper (STT) → "
        "Claude Haiku 4.5 (router) → "
        "Claude Sonnet 4.6 (inference) → "
        "Piper (TTS)."
    )
    st.caption(f"Whisper model: `{WHISPER_MODEL_SIZE}`")
    st.caption(f"Topics loaded: {len(get_artifacts().topics)}")

    # ---- Prompt cache stats panel ----
    inf = CACHE_STATS["inference"]
    rt = CACHE_STATS["router"]
    if inf["calls"] or rt["calls"]:
        st.markdown("---")
        st.markdown("### 💰 Prompt cache (this session)")
        # Compute paid vs baseline cost
        paid = (
            inf["regular_input"]*3 + inf["creation"]*3.75 + inf["read"]*0.30 + inf["output"]*15
            + rt["regular_input"]*1 + rt["creation"]*1.25 + rt["read"]*0.10 + rt["output"]*5
        ) / 1e6
        baseline = (
            (inf["regular_input"]+inf["creation"]+inf["read"])*3 + inf["output"]*15
            + (rt["regular_input"]+rt["creation"]+rt["read"])*1 + rt["output"]*5
        ) / 1e6
        saved_pct = (100*(baseline-paid)/baseline) if baseline > 0 else 0
        col_l, col_r = st.columns(2)
        col_l.metric("Paid", f"${paid:.4f}")
        col_r.metric("Saved", f"${baseline-paid:.4f}", f"{saved_pct:.0f}%")
        st.caption(
            f"Inference: {inf['calls']} calls · "
            f"{inf['read']:,} cached-read tok · {inf['creation']:,} cache-write tok"
        )
        st.caption(
            f"Router: {rt['calls']} calls · "
            f"caching not honored on Haiku 4.5 in this SDK version"
        )


# ----- Header — Reachy Mini avatar + title --------------------------------
# A stylised SVG approximation of the Reachy Mini robot. The two
# `<animate>` tags drive a subtle "breathing" pulse on the eyes; that
# keeps the avatar visibly alive between turns without animating during
# active rendering (Streamlit re-runs would restart any session-state-
# driven animation each turn anyway). When TTS audio plays below, the
# visible audio waveform serves as the "speaking" affordance.
REACHY_HEADER_HTML = """
<div style='display:flex; align-items:center; gap:1.2rem;
            padding:0.6rem 0 0.8rem;'>
  <svg width='96' height='96' viewBox='0 0 200 200'
       xmlns='http://www.w3.org/2000/svg'
       aria-label='Reachy Mini avatar'>
    <!-- side cups / ear-microphones -->
    <ellipse cx='42' cy='105' rx='14' ry='28'
             fill='#3a4255' stroke='#9aa4b3' stroke-width='2'/>
    <ellipse cx='158' cy='105' rx='14' ry='28'
             fill='#3a4255' stroke='#9aa4b3' stroke-width='2'/>
    <!-- body / head shell -->
    <rect x='58' y='52' width='84' height='118' rx='20'
          fill='#2a3144' stroke='#9aa4b3' stroke-width='2'/>
    <!-- top cap -->
    <ellipse cx='100' cy='52' rx='42' ry='14'
             fill='#3a4255' stroke='#9aa4b3' stroke-width='2'/>
    <!-- mic dome on top -->
    <circle cx='100' cy='32' r='6' fill='#4ad295'>
      <animate attributeName='opacity'
               values='1;0.55;1' dur='2.4s' repeatCount='indefinite'/>
    </circle>
    <line x1='100' y1='38' x2='100' y2='52'
          stroke='#9aa4b3' stroke-width='2'/>
    <!-- screen / face -->
    <rect x='70' y='72' width='60' height='52' rx='8'
          fill='#0e1117' stroke='#2d4ea8' stroke-width='1'/>
    <!-- eyes -->
    <circle cx='85' cy='96' r='6' fill='#4ad295'>
      <animate attributeName='r'
               values='6;5.4;6' dur='3s' repeatCount='indefinite'/>
    </circle>
    <circle cx='115' cy='96' r='6' fill='#4ad295'>
      <animate attributeName='r'
               values='6;5.4;6' dur='3s' repeatCount='indefinite'/>
    </circle>
    <!-- speaker grille -->
    <line x1='78' y1='144' x2='122' y2='144'
          stroke='#9aa4b3' stroke-width='2'/>
    <line x1='78' y1='150' x2='122' y2='150'
          stroke='#9aa4b3' stroke-width='2'/>
    <line x1='78' y1='156' x2='122' y2='156'
          stroke='#9aa4b3' stroke-width='2'/>
  </svg>
  <div>
    <h1 style='margin:0; color:#f6f1e1; font-size:1.9rem;'>
      ⚖️ With Due Respect
    </h1>
    <p style='color:#9aa4b3; margin:0.25rem 0 0; font-size:0.97rem;'>
      Reachy Mini × retired Chief Justice Artemio V. Panganiban
    </p>
  </div>
</div>
"""
st.markdown(REACHY_HEADER_HTML, unsafe_allow_html=True)
st.markdown("<div style='margin: 0.4rem 0 1rem; border-top:1px solid #232936;'></div>",
            unsafe_allow_html=True)


# ----- Source-rendering helper --------------------------------------------
def render_sources(routing: dict, artifacts: CorpusArtifacts) -> None:
    """Render an expander showing the routed topics and the raw docs the
    inference call would have seen (the top 3 doc_ids of the primary topic)."""
    primary = routing.get("primary_topic", "—")
    secondary = routing.get("secondary_topics", []) or []
    confidence = routing.get("confidence", "—")
    reasoning = routing.get("reasoning", "")

    primary_topic_obj = artifacts.topics.get(primary, {})
    doc_ids = primary_topic_obj.get("doc_ids", [])[:3]
    primary_display = primary_topic_obj.get("display_name", primary)

    with st.expander(f"📚 Sources — {primary_display} ({confidence})"):
        # Topic pills
        pills = [f"<span class='topic-pill topic-primary'>{primary}</span>"]
        for t in secondary:
            pills.append(f"<span class='topic-pill topic-secondary'>{t}</span>")
        st.markdown("**Routed topics:** " + " ".join(pills), unsafe_allow_html=True)

        conf_class = f"conf-{confidence}" if confidence in {"high", "medium", "low"} else ""
        st.markdown(
            f"**Confidence:** <span class='{conf_class}'>{confidence}</span>",
            unsafe_allow_html=True,
        )
        if reasoning:
            st.markdown(f"**Router reasoning:** *{reasoning}*")

        if doc_ids:
            st.markdown("**Source documents (top 3 of primary topic):**")
            for did in doc_ids:
                raw = artifacts.load_raw_doc(did)
                if not raw:
                    st.markdown(f"- `{did}`")
                    continue
                title = raw.get("title", did)
                date = raw.get("date", "")
                meta = f" · {date}" if date else ""
                st.markdown(f"- **{title}**<span class='source-meta'>  ·  `{did}`{meta}</span>",
                            unsafe_allow_html=True)


# ----- Render conversation history ----------------------------------------
artifacts = get_artifacts()
USER_AVATAR = "👤"
CJ_AVATAR = "⚖️"

for msg in st.session_state.messages:
    avatar = USER_AVATAR if msg["role"] == "user" else CJ_AVATAR
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])
        ap = msg.get("audio_path")
        if ap and Path(ap).exists():
            st.audio(ap)
        if msg.get("routing"):
            render_sources(msg["routing"], artifacts)


# ----- Input row: mic + text fallback -------------------------------------
mic_col, _ = st.columns([1, 1])
with mic_col:
    audio_in = st.audio_input(
        "🎤 Press to record your question",
        key=f"mic_{st.session_state.mic_counter}",
    )

text_in = st.chat_input("…or type it (fallback)")


# ----- Resolve the new input to a question string -------------------------
question: str | None = None

if audio_in is not None:
    audio_bytes = audio_in.getvalue()
    audio_hash = hashlib.md5(audio_bytes).hexdigest()
    if audio_hash != st.session_state.last_audio_hash:
        st.session_state.last_audio_hash = audio_hash
        with st.status("Transcribing your question…", expanded=False):
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_bytes)
                wav_path = tmp.name
            try:
                question = transcribe_audio(wav_path, get_whisper())
            finally:
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass
        if not question or not question.strip():
            st.warning("No speech detected — please try again.")
            question = None
        else:
            # bump mic key so the widget resets for the next question
            st.session_state.mic_counter += 1

if text_in:
    question = text_in


# ----- Run the turn --------------------------------------------------------
if question:
    # 1. Render the user's message immediately, append to history
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user", avatar=USER_AVATAR):
        st.markdown(question)

    # Conversation history for the inference call (last 10 turns = 20 messages)
    inference_history = [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.messages[:-1]
        if m["role"] in ("user", "assistant")
    ][-20:]

    # 2. Render the assistant's response stage by stage
    with st.chat_message("assistant", avatar=CJ_AVATAR):
        client = get_client()

        # The SDK already retries 5xx/429 with exponential backoff
        # (ANTHROPIC_MAX_RETRIES = 4 in cj_chat.py). If we still get an error
        # after that, show a friendly message and persist a marker turn so
        # the user's question stays in history.
        routing = None
        response = None
        fidelity = None
        api_error: str | None = None
        try:
            # 2a. Input Gate — catches identity probes before they hit
            # the topic router (PLAN-0001 §D).
            with st.status("🚪 Checking question scope…", expanded=False) as status:
                gate = input_gate(client, question)
                status.update(
                    label=f"🚪 Scope: {gate['scope']}",
                    state="complete",
                )

            # 2b. Topic routing (or META override if the gate fired)
            with st.status("🧭 Picking relevant corpus topics…", expanded=False) as status:
                if gate["scope"] == "identity_probe":
                    routing = force_meta_routing(gate["reasoning"])
                    status.update(
                        label="🧭 Identity probe → META path",
                        state="complete",
                    )
                else:
                    routing = route_question(client, question, artifacts)
                    status.update(
                        label=(f"🧭 Routed to {routing['primary_topic']} "
                               f"({routing['confidence']})"),
                        state="complete",
                    )

            # 2c. Build context once so both the streamer and the
            # fidelity check see the same prompt material.
            context = build_context(routing, artifacts)

            # 2d. Stream Sonnet's response token-by-token. The UI
            # renders text as it arrives — no waiting for the full
            # composition before the user sees anything.
            st.markdown("**💭 CJ:**")
            response_raw = st.write_stream(
                generate_response_stream(
                    client, question, routing, artifacts, inference_history
                )
            )
            response = _strip_stage_directions(response_raw)

            # 2e. Fidelity check (advisory). The response is already
            # visible to the user; flags surface as a non-blocking
            # warning rather than a retry. This trades guardrail
            # strictness for streaming UX — matches dashboard
            # ergonomics; the headless CLI keeps the strict retry path.
            fidelity = fidelity_check(client, context, response)
            flags = [
                k for k in ("hallucination", "voice_drift", "guardrail_violation")
                if fidelity.get(k)
            ]
            if flags:
                st.warning(
                    f"⚠ Fidelity flagged: {', '.join(flags)} — "
                    f"{fidelity.get('reasoning', '')}",
                    icon="⚠️",
                )
        except APIStatusError as e:
            # 529 = Anthropic overloaded; 429 = rate-limited; 5xx = upstream error.
            # The SDK already retried ANTHROPIC_MAX_RETRIES times; if we're here
            # the issue outlasted that window.
            if e.status_code == 529:
                api_error = (
                    "Claude's servers are overloaded right now (HTTP 529). The app "
                    "already retried automatically — please try the same question "
                    "again in a few seconds. Your message is still in the conversation."
                )
            elif e.status_code == 429:
                api_error = (
                    "Hit Claude's rate limit (HTTP 429). Wait a few seconds and try again."
                )
            else:
                api_error = (
                    f"Claude API returned HTTP {e.status_code}: {e.message}. "
                    f"Try again in a moment."
                )
        except APIConnectionError as e:
            api_error = (
                f"Couldn't reach Claude's API ({e}). Check your network connection "
                f"and try again."
            )
        except Exception as e:
            api_error = f"Unexpected error contacting Claude: {type(e).__name__}: {e}"

        if api_error:
            st.error("⚠️  " + api_error)
            st.session_state.messages.append({
                "role": "assistant",
                "content": "⚠️ " + api_error,
                "audio_path": None,
                "routing": None,
                "is_error": True,
            })
            st.stop()

        # Note: response already rendered via st.write_stream() above —
        # no extra st.markdown(response) needed.

        # 3. TTS (optional, never blocks the turn — TTS errors are local)
        audio_path = None
        if st.session_state.tts_enabled:
            with st.status("🔊 Synthesizing voice…", expanded=False) as status:
                audio_path = str(get_tts_dir() / f"resp_{int(time.time()*1000)}.wav")
                try:
                    synthesize_speech(response, audio_path)
                    status.update(label="🔊 Voice ready", state="complete")
                except Exception as e:
                    status.update(label=f"TTS failed: {e}", state="error")
                    audio_path = None
            if audio_path and Path(audio_path).exists():
                st.audio(audio_path, autoplay=True)

        # 4. Sources
        render_sources(routing, artifacts)

        # 5. TTS debug — show the chunks Piper actually saw (collapsed by default)
        if st.session_state.get("show_tts_debug"):
            with st.expander(f"🔊 TTS chunks ({TTS_SENTENCE_SILENCE}s pause between)"):
                chunks = _prepare_tts_text(response)
                for i, c in enumerate(chunks, 1):
                    marker = " ⏸" if i > 1 else ""
                    st.markdown(f"`[{i}]` {c}{marker}")
                st.caption(
                    f"Each `⏸` = {TTS_SENTENCE_SILENCE}s sentence-end pause. "
                    "Em-dashes (—) and other long dashes were substituted with "
                    "commas in the TTS path — those become Piper's native "
                    "comma pauses (~150-300ms), which you'll hear *inside* each "
                    "line above wherever the original text had an em-dash."
                )

    # 5. Persist the assistant turn so it survives the next rerun
    st.session_state.messages.append({
        "role": "assistant",
        "content": response,
        "audio_path": audio_path,
        "routing": routing,
    })

    # Trigger one rerun so the mic widget resets cleanly via the bumped key
    st.rerun()
