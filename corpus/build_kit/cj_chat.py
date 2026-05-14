"""
Reference implementation: CJ Panganiban conversation app.

Pipeline: faster-whisper (STT) → Claude Haiku router → Claude Sonnet inference → Piper (TTS)

This is a runnable skeleton. Adapt the audio I/O to your demo environment
(mic + speakers, push-to-talk button, web UI, etc).

DEPENDENCIES:
    pip install anthropic faster-whisper sounddevice numpy webrtcvad

    For Piper TTS, download the binary from:
        https://github.com/rhasspy/piper/releases
    And the voice model (suggest en_US-ryan-high) from:
        https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/ryan/high

ENVIRONMENT:
    export ANTHROPIC_API_KEY="sk-ant-..."

ARTIFACTS (place these in ./artifacts/):
    - topic_map.json
    - topic_graph.json
    - frameworks.json
    - signature_library.json
    - entity_index.json
    - voice_card.md
    - router_prompt.md
    - topics/    (the 89 raw extractions from Layer A)

USAGE:
    python cj_chat.py                  # interactive mode (push-to-talk)
    python cj_chat.py --text "..."     # text-only test (skip STT/TTS)
"""

import os
import json
import sys
import subprocess
import tempfile
import argparse
import re
from pathlib import Path
from anthropic import Anthropic

# ============================================================
# Configuration
# ============================================================
ARTIFACTS_DIR = Path("./artifacts")
TOPICS_DIR = ARTIFACTS_DIR / "topics"
ROUTER_MODEL = "claude-haiku-4-5-20251001"
INFERENCE_MODEL = "claude-sonnet-4-6"  # use sonnet-4-6 or opus-4-7 if budget permits

# Piper paths — set these to wherever you installed piper and the voice model
PIPER_BIN = os.environ.get("PIPER_BIN", "piper")
PIPER_VOICE = os.environ.get("PIPER_VOICE", "./voices/en_US-ryan-high.onnx")

# Whisper model size — "small" works for English; use "medium" if Filipino mix
WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL", "medium")

# Audio
SAMPLE_RATE = 16000
RECORD_SECONDS_MAX = 30  # max utterance length before auto-cutoff

# ============================================================
# Load all artifacts at startup (one-shot)
# ============================================================
class CorpusArtifacts:
    def __init__(self, base_dir: Path):
        self.base = base_dir
        with open(base_dir / "topic_map.json") as f:
            self.topic_map = json.load(f)
        with open(base_dir / "topic_graph.json") as f:
            self.topic_graph = json.load(f)
        with open(base_dir / "entity_index.json") as f:
            self.entity_index = json.load(f)
        with open(base_dir / "frameworks.json") as f:
            self.frameworks = json.load(f)
        with open(base_dir / "voice_card.md") as f:
            self.voice_card = f.read()
        with open(base_dir / "router_prompt.md") as f:
            # Extract the system-prompt block from the router_prompt.md doc
            raw = f.read()
            # The router prompt's system block is the content between the first
            # triple-backtick block. We extract it; if absent, use the whole doc.
            match = re.search(r"```\s*(.+?)\s*```", raw, re.DOTALL)
            self.router_system = match.group(1) if match else raw
        self.topics = self.topic_map["topics"]
        self.valid_topic_ids = set(self.topics.keys())

    def load_raw_doc(self, doc_id: str) -> dict | None:
        path = self.base / "topics" / f"{doc_id}.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return None


# ============================================================
# Step 1: STT — faster-whisper
# ============================================================
def transcribe_audio(audio_path: str, model) -> str:
    """Returns transcribed text. Expects 16kHz mono wav."""
    segments, info = model.transcribe(
        audio_path,
        beam_size=5,
        language=None,  # auto-detect (English / Tagalog)
        vad_filter=True,  # built-in VAD; prevents hallucinated transcription
        vad_parameters={"min_silence_duration_ms": 500},
    )
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return text


# ============================================================
# Step 2: Router — Claude Haiku
# ============================================================
def route_question(client: Anthropic, question: str, artifacts: CorpusArtifacts) -> dict:
    """Returns the parsed router output dict, with validated topic IDs."""
    resp = client.messages.create(
        model=ROUTER_MODEL,
        max_tokens=300,
        system=artifacts.router_system,
        messages=[{"role": "user", "content": question}],
    )
    raw = resp.content[0].text.strip()
    # Strip code fences if Haiku added them
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback to safe default
        return {
            "primary_topic": "rule_of_law",
            "secondary_topics": [],
            "confidence": "low",
            "reasoning": "Router output unparseable; falling back to anchor topic.",
        }

    # Validate topic IDs against the actual topic_map
    if parsed.get("primary_topic") not in artifacts.valid_topic_ids:
        parsed["primary_topic"] = "rule_of_law"
        parsed["confidence"] = "low"
    parsed["secondary_topics"] = [
        t for t in parsed.get("secondary_topics", [])
        if t in artifacts.valid_topic_ids and t != parsed["primary_topic"]
    ][:2]

    return parsed


# ============================================================
# Step 3: Build context block for the inference call
# ============================================================
def build_context(routing: dict, artifacts: CorpusArtifacts) -> str:
    """Assemble the structured context block per the voice card's convention."""
    primary = routing["primary_topic"]
    secondary = routing.get("secondary_topics", [])
    all_topic_ids = [primary] + secondary

    # Topic data block
    topic_data = {}
    for tid in all_topic_ids:
        if tid in artifacts.topics:
            topic_data[tid] = artifacts.topics[tid]

    # Pull raw source docs — limit to 3 most-shared docs from the primary topic
    primary_topic = artifacts.topics.get(primary, {})
    primary_doc_ids = primary_topic.get("doc_ids", [])[:3]

    source_docs = []
    for did in primary_doc_ids:
        raw = artifacts.load_raw_doc(did)
        if raw:
            # Trim raw doc to essentials to keep token cost low
            trimmed = {
                "doc_id": raw.get("doc_id"),
                "title": raw.get("title"),
                "date": raw.get("date"),
                "voice_register": raw.get("voice_register"),
                "primary_topics": raw.get("primary_topics"),
                "stances": raw.get("stances", [])[:4],
                "signature_phrases": raw.get("signature_phrases", [])[:8],
                "notable_anecdotes": raw.get("notable_anecdotes", [])[:3],
            }
            source_docs.append(trimmed)

    # Format the context block
    parts = []

    parts.append("<routed_topics>")
    for tid in all_topic_ids:
        t = artifacts.topics.get(tid)
        if t:
            parts.append(f"  - {tid} ({t['tier']}): {t['display_name']}")
    parts.append(f"  confidence: {routing.get('confidence', 'unknown')}")
    parts.append("</routed_topics>")
    parts.append("")

    parts.append("<topic_data>")
    parts.append(json.dumps(topic_data, ensure_ascii=False, indent=2))
    parts.append("</topic_data>")
    parts.append("")

    parts.append("<source_documents>")
    parts.append(json.dumps(source_docs, ensure_ascii=False, indent=2))
    parts.append("</source_documents>")

    return "\n".join(parts)


# ============================================================
# Step 4: Inference — Claude Sonnet
# ============================================================
def generate_response(
    client: Anthropic,
    question: str,
    routing: dict,
    artifacts: CorpusArtifacts,
    conversation_history: list = None,
) -> str:
    context = build_context(routing, artifacts)

    # Adjust grounding instructions based on confidence
    confidence_note = {
        "high": "The routed topics map directly to the user's question. Answer in voice, citing topic data and source documents where it strengthens the response.",
        "medium": "The routed topics are adjacent to the user's question. Reason from the available material; mark out-of-corpus extensions softly.",
        "low": "The user's question is largely out-of-corpus. Use the out-of-corpus reasoning policy from the voice card — reason from nearest principles, mark the move softly, do not invent facts.",
    }.get(routing.get("confidence", "low"), "")

    user_content = f"""{context}

<grounding_note>
{confidence_note}
</grounding_note>

<user_question>
{question}
</user_question>"""

    messages = []
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_content})

    resp = client.messages.create(
        model=INFERENCE_MODEL,
        max_tokens=600,  # spoken responses ~80-250 words = ~120-350 tokens
        system=artifacts.voice_card,
        messages=messages,
    )
    return resp.content[0].text.strip()


# ============================================================
# Step 5: TTS — Piper
# ============================================================
def synthesize_speech(text: str, output_wav: str):
    """Pipe text to Piper, write wav. Returns path."""
    # Clean text for TTS — strip markdown markers, normalize whitespace
    text = re.sub(r"[*_`]", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    cmd = [PIPER_BIN, "--model", PIPER_VOICE, "--output_file", output_wav]
    try:
        subprocess.run(cmd, input=text, text=True, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"Piper failed: {e.stderr}", file=sys.stderr)
        raise
    return output_wav


def play_wav(path: str):
    """Cross-platform wav playback."""
    if sys.platform == "darwin":
        subprocess.run(["afplay", path])
    elif sys.platform == "linux":
        subprocess.run(["aplay", path], capture_output=True)
    elif sys.platform == "win32":
        import winsound
        winsound.PlaySound(path, winsound.SND_FILENAME)


# ============================================================
# Step 6: Audio input — push-to-talk
# ============================================================
def record_until_silence(seconds_max: int = RECORD_SECONDS_MAX) -> str:
    """Record audio with VAD-based silence detection. Returns path to wav file."""
    import sounddevice as sd
    import numpy as np
    from scipy.io import wavfile

    print("🎤 Listening... (press Ctrl+C to stop)")
    audio = sd.rec(int(seconds_max * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
    try:
        sd.wait()
    except KeyboardInterrupt:
        sd.stop()
    audio = np.squeeze(audio)

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    wavfile.write(tmp.name, SAMPLE_RATE, audio)
    return tmp.name


# ============================================================
# Main turn loop
# ============================================================
def run_turn(
    client: Anthropic,
    artifacts: CorpusArtifacts,
    whisper_model,
    question_text: str = None,
    conversation_history: list = None,
    skip_audio: bool = False,
) -> tuple[str, str, dict]:
    """One conversation turn. Returns (question, response, routing_info)."""

    # Step 1: Get the question
    if question_text:
        question = question_text
    else:
        audio_path = record_until_silence()
        print("📝 Transcribing...")
        question = transcribe_audio(audio_path, whisper_model)
        os.unlink(audio_path)

    if not question.strip():
        print("(no speech detected)")
        return "", "", {}

    print(f"\n👤 You: {question}\n")

    # Step 2: Route
    print("🧭 Routing...")
    routing = route_question(client, question, artifacts)
    print(f"   primary: {routing['primary_topic']}")
    print(f"   secondary: {routing.get('secondary_topics', [])}")
    print(f"   confidence: {routing['confidence']}")

    # Step 3: Generate
    print("💭 Thinking...")
    response = generate_response(client, question, routing, artifacts, conversation_history)
    print(f"\n⚖️  CJ: {response}\n")

    # Step 4: Speak (unless text-only mode)
    if not skip_audio:
        print("🔊 Speaking...")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            synthesize_speech(response, tmp.name)
            play_wav(tmp.name)
            os.unlink(tmp.name)

    return question, response, routing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", type=str, help="Text-only mode: ask one question and exit")
    parser.add_argument("--artifacts", type=str, default="./artifacts", help="Path to artifacts dir")
    args = parser.parse_args()

    print("Loading artifacts...")
    artifacts = CorpusArtifacts(Path(args.artifacts))
    print(f"  ✓ {len(artifacts.topics)} topics loaded")

    client = Anthropic()  # uses ANTHROPIC_API_KEY env var

    if args.text:
        # Text-only single-turn test
        run_turn(client, artifacts, None, question_text=args.text, skip_audio=True)
        return

    # Voice mode: load whisper, push-to-talk loop
    print(f"Loading faster-whisper ({WHISPER_MODEL_SIZE})...")
    from faster_whisper import WhisperModel
    whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    print("Ready. Press Enter to start a turn, Ctrl+C to exit.\n")

    conversation_history = []
    try:
        while True:
            input("Press Enter to speak...")
            question, response, _ = run_turn(client, artifacts, whisper_model,
                                             conversation_history=conversation_history)
            if question and response:
                conversation_history.append({"role": "user", "content": question})
                conversation_history.append({"role": "assistant", "content": response})
                # Trim history to last 10 turns to keep context manageable
                conversation_history = conversation_history[-20:]
    except KeyboardInterrupt:
        print("\nGoodbye. Maraming salamat po.")


if __name__ == "__main__":
    main()
