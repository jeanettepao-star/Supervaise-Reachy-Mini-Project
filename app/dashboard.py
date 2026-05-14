"""Interactive chat dashboard for the CJ Panganiban conversation app.

This is the primary UI: a Streamlit chat app with a mic input (record in the
browser), a text-input fallback, inline playback of CJ's spoken response, and
a Sources expander showing which canonical topics the router matched.

Drives the same pipeline as the CLI (`cj_chat.py`):
    faster-whisper (STT) → Claude Haiku (router) → Claude Sonnet (inference) → Piper (TTS)

Run:
    .venv/Scripts/streamlit run dashboard.py
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
    synthesize_speech,
    make_client,
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


# ----- Header --------------------------------------------------------------
st.markdown(
    "<h1 style='margin-bottom:0; color:#f6f1e1;'>⚖️ With Due Respect</h1>"
    "<p style='color:#9aa4b3; margin-top:0.2rem;'>"
    "A conversation with retired Chief Justice Artemio V. Panganiban"
    "</p>",
    unsafe_allow_html=True,
)
st.markdown("<div style='margin: 0.6rem 0 1rem; border-top:1px solid #232936;'></div>",
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
        api_error: str | None = None
        try:
            with st.status("🧭 Picking relevant corpus topics…", expanded=False) as status:
                routing = route_question(client, question, artifacts)
                status.update(
                    label=(f"🧭 Routed to {routing['primary_topic']} "
                           f"({routing['confidence']})"),
                    state="complete",
                )

            with st.status("💭 CJ is composing his answer…", expanded=False) as status:
                response = generate_response(
                    client, question, routing, artifacts, inference_history
                )
                status.update(label="💭 Response ready", state="complete")
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

        st.markdown(response)

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

    # 5. Persist the assistant turn so it survives the next rerun
    st.session_state.messages.append({
        "role": "assistant",
        "content": response,
        "audio_path": audio_path,
        "routing": routing,
    })

    # Trigger one rerun so the mic widget resets cleanly via the bumped key
    st.rerun()
