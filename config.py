"""
config.py — single source of truth for every tunable knob in the
CJ Panganiban pilot.

Design contract (W1.1 / W3.3):
  * ONE file holds every knob. Code reads from here; it never hard-codes a
    literal that belongs in a sweep. W3.3 sweeps *this file* (or the matching
    env var) and never edits the code.
  * Every knob is overridable at runtime via an environment variable (and
    therefore via a `.env` file or a CLI `--set KEY=VALUE` wrapper) so a sweep
    can vary values WITHOUT editing code. Precedence: env var > default here.
  * Importing this module has no side effects beyond reading the environment —
    no network, no file I/O, no model loads. `import config` is always cheap.
  * One-line comment per knob states the trade-off it controls
    (cost / latency / recall / fidelity).

ARCHITECTURE NOTE — two generations of knob live here on purpose:
  [BASELINE]  knobs consumed by the *current* pipeline that ships today:
              Haiku router/gate → curated 35-topic map → Sonnet composer →
              Haiku fidelity check. No embeddings, no numpy retrieval, no RRF.
  [NEW-ARCH]  knobs for the LOCKED target architecture (dimensional/centroid
              topic model, in-memory numpy retrieval, RRF hybrid fusion,
              soft-prior topic bias). These are NOT yet wired into runtime code
              — they exist so W1.4–W1.7 can switch the engine on by reading
              config, not by re-plumbing literals. They are inert until then.

Usage:
    import config
    config.COMPOSER_MODEL_ID          # any knob, directly
    config.summary()                  # dict snapshot for logging / sweep manifests
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths — repo-root anchored so the same config works from repo root, app/,
# or scripts/. Override the root with CJ_REPO_ROOT if the tree is relocated.
# ---------------------------------------------------------------------------
REPO_ROOT: Path = Path(
    os.environ.get("CJ_REPO_ROOT", Path(__file__).resolve().parent)
).resolve()


# ---------------------------------------------------------------------------
# Typed env-override helpers. Each knob below is `_envX("ENV_NAME", default)`
# so a sweep can set the env var OR edit the default literal in place.
# ---------------------------------------------------------------------------
def _env_str(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v if v is not None and v != "" else default


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    try:
        return int(v) if v not in (None, "") else default
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    try:
        return float(v) if v not in (None, "") else default
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "on", "y", "t"}


def _env_list(name: str, default: list[str]) -> list[str]:
    """Comma-separated env override, e.g. CJ_CENTROID_FIELDS=label,description."""
    v = os.environ.get(name)
    if v is None or v == "":
        return list(default)
    return [item.strip() for item in v.split(",") if item.strip()]


def _env_path(name: str, default: Path) -> Path:
    v = os.environ.get(name)
    return Path(v).expanduser().resolve() if v else default


# ===========================================================================
# 1. RETRIEVAL CUTOFF                                            [NEW-ARCH]
#    How many passages survive to the composer. Higher recall ⇄ more tokens.
# ===========================================================================
# Keep a chunk iff score >= TAU * top_score. Lower TAU → more chunks kept
# (↑recall, ↑cost/latency); higher TAU → tighter, cheaper context (↓recall).
TAU: float = _env_float("CJ_TAU", 0.30)
# Floor on chunks kept regardless of TAU — guards against an empty context
# when the top score is an outlier (↑recall floor, small ↑cost).
MIN_K: int = _env_int("CJ_MIN_K", 3)
# Ceiling on chunks kept regardless of TAU — hard cap on context size
# (caps cost/latency; too low ↓recall on broad questions).
MAX_K: int = _env_int("CJ_MAX_K", 12)


# ===========================================================================
# 2. FUSION                                                     [NEW-ARCH]
#    Hybrid lexical+dense fusion and the topic-affinity prior.
# ===========================================================================
# Reciprocal-Rank-Fusion constant: rank score = 1/(RRF_K + rank). Larger
# RRF_K flattens the rank advantage (more democratic fusion, ↓precision@1);
# smaller sharpens it (↑precision, more brittle).
RRF_K: int = _env_int("CJ_RRF_K", 60)
# Topic-affinity weight: final = passage_sim + LAMBDA * topic_affinity.
# Higher LAMBDA trusts the topic prior more (↑on-topic, risks ↓recall on
# cross-topic questions); 0 disables the prior (pure passage similarity).
LAMBDA: float = _env_float("CJ_LAMBDA", 0.25)


# ===========================================================================
# 3. ROUTING / SCOPE                                  [BASELINE + NEW-ARCH]
#    When to declare a question out-of-corpus, and how soft the topic prior is.
# ===========================================================================
# Below this top-affinity score the question is treated as out-of-scope and
# the OOC reasoning policy fires. Higher → stricter scope (more "I haven't
# written on that"); lower → more answers attempted (risks ungrounded ones).
OUT_OF_SCOPE_THRESHOLD: float = _env_float("CJ_OUT_OF_SCOPE_THRESHOLD", 0.15)
# Softmax temperature over topic affinities → soft prior (not a hard pick).
# Higher temperature = flatter prior (more topics contribute, ↑recall);
# lower = peakier (commits to the top topic, ↑precision).
TOPIC_SOFTMAX_TEMPERATURE: float = _env_float("CJ_TOPIC_SOFTMAX_TEMPERATURE", 0.7)


# ===========================================================================
# 4. TOPIC MODEL                                                [NEW-ARCH]
#    Drives the W1.7 centroid regeneration. Must be fully config-driven so the
#    regen is reproducible from this file alone.
# ===========================================================================
# Where the curated/centroid topic map is read from and written to.
TOPIC_MAP_PATH: Path = _env_path(
    "CJ_TOPIC_MAP_PATH", REPO_ROOT / "corpus" / "voice" / "topic_map.json"
)
# Schema/version stamp written into the regenerated map; bump on format change
# so consumers can detect a stale on-disk map (no runtime trade-off, hygiene).
TOPIC_MAP_VERSION: str = _env_str("CJ_TOPIC_MAP_VERSION", "2.0")
# Independence check: two topics whose centroids exceed this cosine are flagged
# as non-independent (merge candidates). Lower → more merges (fewer, broader
# topics, ↓precision); higher → keeps near-duplicates apart (↑precision, risk
# of redundant topics). Default 0.85 per W1.1 brief.
TOPIC_MERGE_COSINE: float = _env_float("CJ_TOPIC_MERGE_COSINE", 0.85)
# Max topic tags (primary + secondary) attached to a question/doc, clamped to
# 1–3. More tags → broader context pulled (↑recall, ↑cost); fewer → tighter.
MAX_TOPIC_TAGS: int = max(1, min(3, _env_int("CJ_MAX_TOPIC_TAGS", 3)))
# Which per-topic fields are embedded and averaged into the topic centroid.
# More fields → richer, more stable centroid (↑recall, slower regen); fewer →
# sharper but noisier centroid.
CENTROID_SOURCE_FIELDS: list[str] = _env_list(
    "CJ_CENTROID_SOURCE_FIELDS",
    ["label", "description", "signature_phrases", "exemplar_chunks"],
)
# Per-doc topic_paths derivation (consumed today by build_topic_map.py):
# how many topics become a doc's primary vs secondary routes. More primaries
# → broader routing (↑recall, ↓precision).
TOPIC_PRIMARY_N: int = _env_int("CJ_TOPIC_PRIMARY_N", 2)
TOPIC_SECONDARY_N: int = _env_int("CJ_TOPIC_SECONDARY_N", 3)
# Matcher-health thresholds used by build_topic_map.py's curator warnings
# (taxonomy hygiene only; no inference-time trade-off).
TOPIC_OVER_BROAD_FRAC: float = _env_float("CJ_TOPIC_OVER_BROAD_FRAC", 0.25)
TOPIC_NEAR_DUP_JACCARD: float = _env_float("CJ_TOPIC_NEAR_DUP_JACCARD", 0.50)
TOPIC_DOMINANT_TERM_FRAC: float = _env_float("CJ_TOPIC_DOMINANT_TERM_FRAC", 0.80)


# ===========================================================================
# 5. COMPOSITION                                                [BASELINE]
#    The Sonnet composer call and its retry/guardrail envelope.
# ===========================================================================
# Max output tokens for a spoken response (~20-150 words post-compression).
# Higher → longer answers (↑cost, ↑latency, risk of rambling); lower → terser.
MAX_TOKENS: int = _env_int("CJ_MAX_TOKENS", 300)
# Wall-clock budget for one composer call before giving up (latency guard).
COMPOSER_TIMEOUT_S: float = _env_float("CJ_COMPOSER_TIMEOUT_S", 30.0)
# SDK-level retries on transient 429/5xx (exponential backoff). Higher →
# more resilient to overload (↑tail latency); lower → fails faster.
MAX_RETRIES: int = _env_int("CJ_MAX_RETRIES", 4)
# Composer fidelity-recompose retries on a flagged draft before the safe
# OOC fallback. Higher → more salvage attempts (↑cost/latency); 0 → fallback
# immediately on first flag.
FIDELITY_MAX_RETRIES: int = _env_int("CJ_FIDELITY_MAX_RETRIES", 1)
# [NEW-ARCH] Expand-on-demand gate: if a turn's retrieval would fire (need
# more context) on more than this fraction of turns, escalate to a wider
# pull. ~0.10 keeps expansion rare (↓cost) while catching genuine gaps.
EXPAND_ON_DEMAND_FIRE_RATE_GATE: float = _env_float(
    "CJ_EXPAND_ON_DEMAND_FIRE_RATE_GATE", 0.10
)
# Soft token budget for the assembled context block (baseline composer).
# Higher → more source docs survive (↑recall, ↑cost); lower → tighter context.
CONTEXT_TOKEN_BUDGET: int = _env_int("CJ_CONTEXT_TOKEN_BUDGET", 12_000)
# Approx chars-per-token used to estimate the budget above (tokeniser proxy).
CHARS_PER_TOKEN_APPROX: int = _env_int("CJ_CHARS_PER_TOKEN_APPROX", 4)
# Max source docs pulled into one context block (baseline retrieval).
# Higher → broader grounding (↑recall, ↑cost); lower → sharper, cheaper.
MAX_SOURCE_DOCS: int = _env_int("CJ_MAX_SOURCE_DOCS", 3)


# ===========================================================================
# 6. MODELS                                           [BASELINE + NEW-ARCH]
# ===========================================================================
# [NEW-ARCH] Local sentence-embedding model for the centroid/retrieval engine.
# all-MiniLM-L6-v2 is the validated choice: 384-dim, fast on CPU (latency),
# cheap (runs locally, no API cost).
EMBEDDING_MODEL_ID: str = _env_str("CJ_EMBEDDING_MODEL_ID", "all-MiniLM-L6-v2")
# Output dimensionality of EMBEDDING_MODEL_ID; must match the model above or
# the numpy index will mis-shape. Change only with the model id.
EMBEDDING_DIM: int = _env_int("CJ_EMBEDDING_DIM", 384)
# [BASELINE] Composer model (Sonnet) — quality/cost anchor for composition.
COMPOSER_MODEL_ID: str = _env_str(
    "INFERENCE_MODEL", _env_str("CJ_COMPOSER_MODEL_ID", "claude-sonnet-4-6")
)
# [BASELINE] Router / gate / fidelity model (Haiku) — cheap, fast classifier.
ROUTER_MODEL_ID: str = _env_str(
    "ROUTER_MODEL", _env_str("CJ_ROUTER_MODEL_ID", "claude-haiku-4-5-20251001")
)
# [BASELINE] Local STT model size (faster-whisper). Larger → better Tagalog
# mix accuracy (↑latency, ↑memory); smaller → faster.
WHISPER_MODEL_SIZE: str = _env_str("WHISPER_MODEL", "medium")
# [BASELINE] Cloud STT/TTS (voice_io.py OpenAI path).
OPENAI_STT_MODEL: str = _env_str("OPENAI_STT_MODEL", "whisper-1")
OPENAI_TTS_MODEL: str = _env_str("OPENAI_TTS_MODEL", "tts-1")
OPENAI_TTS_VOICE: str = _env_str("OPENAI_TTS_VOICE", "echo")
# TTS speed 0.25–4.0; <1 is slower (CJP's measured judicial pace).
OPENAI_TTS_SPEED: float = _env_float("OPENAI_TTS_SPEED", 0.98)


# ===========================================================================
# 7. ENCODING                                                   [CONVENTION]
#    Locked project conventions — preserved verbatim per W1.1.
# ===========================================================================
# Read text/CSV as utf-8-sig so a BOM (if present) is stripped transparently;
# harmless on BOM-free files. Locked convention — do not change casually.
FILE_ENCODING: str = _env_str("CJ_FILE_ENCODING", "utf-8-sig")
# Encoding used when *writing* JSON/text outputs (no BOM on write).
OUTPUT_ENCODING: str = _env_str("CJ_OUTPUT_ENCODING", "utf-8")
# JSON writes keep non-ASCII (Tagalog/Spanish/French) intact, never escaped.
JSON_ENSURE_ASCII: bool = _env_bool("CJ_JSON_ENSURE_ASCII", False)


# ===========================================================================
# 8. AUDIO (baseline push-to-talk recorder)                     [BASELINE]
# ===========================================================================
SAMPLE_RATE: int = _env_int("CJ_SAMPLE_RATE", 16000)
RECORD_SECONDS_MAX: int = _env_int("CJ_RECORD_SECONDS_MAX", 30)
# Energy-based silence detection tunables (int16 RMS) — room-dependent.
SILENCE_RMS_THRESHOLD: int = _env_int("CJ_SILENCE_RMS_THRESHOLD", 350)
TRAILING_SILENCE_MS: int = _env_int("CJ_TRAILING_SILENCE_MS", 1200)
# Piper TTS tempo (baseline local voice).
TTS_SENTENCE_SILENCE: str = _env_str("CJ_TTS_SENTENCE_SILENCE", "0.6")
TTS_LENGTH_SCALE: str = _env_str("CJ_TTS_LENGTH_SCALE", "1.05")


# ===========================================================================
# 9. DATA CONVENTIONS                                           [CONVENTION]
#    Locked schema/ID conventions, surfaced so consumers share one definition.
# ===========================================================================
# Curated CSV schema width — the 15-column contract. Validators read this.
CURATED_SCHEMA_COLUMNS: int = _env_int("CJ_CURATED_SCHEMA_COLUMNS", 15)
# Doc-ID regex. NOTE: the W1.1 brief specifies ^[SCGB][A-E]\d+$ (adds 'B' for
# the forthcoming book corpus, PLAN-0005). The shipping code today recognises
# only S/C/G; 'B' is reserved here so the regex is ready when books land.
DOC_ID_REGEX: str = _env_str("CJ_DOC_ID_REGEX", r"^[SCGB][A-E]\d+$")


# ---------------------------------------------------------------------------
# Introspection — single call that surfaces every knob (for logs / sweeps).
# ---------------------------------------------------------------------------
def summary() -> dict[str, object]:
    """Flat snapshot of every knob — for run logs and sweep manifests."""
    return {
        k: (str(v) if isinstance(v, Path) else v)
        for k, v in globals().items()
        if k.isupper() and not k.startswith("_")
    }


if __name__ == "__main__":
    import json

    print(json.dumps(summary(), indent=2, ensure_ascii=JSON_ENSURE_ASCII))
