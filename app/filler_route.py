"""FILLER v5 — routing + text data for the two-part theme+topic filler.

Pure $0 logic (no network, no model load): maps a retrieval route dict to a filler
decision (THEME or NEUTRAL + optional TOPIC sentence), and holds the LOCKED clip
text (theme variants, neutral pool, topic templates). Imported by:
  - scripts/gen_v5_theme_clips.py  (pre-synthesis of the 50+3 theme/neutral clips)
  - app/voice_job.py               (runtime sequencer)
  - scripts/verify_filler_v5.py    (the $0 stubbed-route harness)

Thresholds live in config (THEME_CONF_THRESHOLD, TOPIC_MARGIN_THRESHOLD), derived in
eval/results/filler_v5_thresholds.md from the frozen-40 route-score bands.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import config

# ---------------------------------------------------------------- subject-free mode (Option D)
# The named theme/topic fillers are UNSAFE at the router's real top-1 accuracy
# (~35% topic / ~41% theme on the frozen-40 gold set — see
# eval/results/filler_v5_phase2_STOP_2026-07-24.md). SUBJECT_FREE_MODE forces the
# filler to speak a characterful hedge that names NOTHING, removing the routing
# dependency entirely. The theme/topic decision code below is preserved, inert, so a
# future routing-accuracy track (Option C) can flip this off and restore named fillers.
# Env override: CJ_FILLER_SUBJECT_FREE_MODE (default ON). Lives here (not config.py) so
# the flag ships in the filler-logic module; move to config.py when convenient.
SUBJECT_FREE_MODE: bool = os.environ.get("CJ_FILLER_SUBJECT_FREE_MODE", "1") \
    not in ("0", "false", "False", "no")

# ---------------------------------------------------------------- LOCKED text data
THEMES = ("A", "B", "C", "D", "E")

# Theme spoken-names (LOCKED, Dev0-approved) substituted for {T} in the variants.
THEME_SPOKEN = {
    "A": "liberty and the rule of law",
    "B": "prosperity and the economy",
    "C": "my own life and journey",
    "D": "the Foundation and its mission",
    "E": "current affairs and my commentary",
}

# 10 theme variants (Sheena-final, English-only). {T} = THEME_SPOKEN. Full sentences.
THEME_VARIANTS = [
    "Ah — your question lies in {T}. Allow me to gather what my record holds.",
    "Yes — that one belongs to {T}. Permit me a brief moment with it.",
    "I see — you bring me to {T}. Let me consult my recollections.",
    "A question of {T}, then. Give me just a moment.",
    "Ah, {T} — a subject close to my work. One moment, please.",
    "You ask about {T}. Let me bring my thoughts together properly.",
    "So — {T} it is. A proper answer deserves a proper moment.",
    "Your question falls under {T}. Allow me to reflect on what I know.",
    "Mm — {T}. Very well; you deserve more than a quick reply.",
    "{T} — a fine territory. Bear with me a moment.",
]

# NEUTRAL / SUBJECT-FREE pool — the ONLY pool spoken in SUBJECT_FREE_MODE (Option D),
# and the low-confidence/GAP/META/late-route fallback otherwise. Every line is a
# characterful, in-voice hedge that NAMES NOTHING (no theme, no topic) — safe at any
# routing accuracy. Two clauses each (acknowledge + buy-the-moment) so the clip runs
# ~4-4.8s at FILLER_TTS_SPEED (1.25x), masking the content compose the way the theme
# clips did. Keep each ≲ 18 words so synth stays under the 5.0s hard cap. Regenerate
# the clips with scripts/gen_v5_subject_free_clips.py after editing this list.
NEUTRAL_TEXTS = [
    "Ah — a fine question. Allow me a moment to consult what my record holds.",
    "Yes; let me give that the consideration it deserves — a moment, if you please.",
    "A thoughtful question. Permit me to gather my recollections properly.",
    "Let me reflect on that for a moment; a proper answer deserves a proper pause.",
    "Hmm — allow me to draw the threads together before I speak.",
    "Well now, that is worth answering with care. Bear with me a moment.",
    "I should like to answer this properly, so let me consult my record first.",
    "A moment, if you would — I prefer to weigh my words before I offer them.",
    "Let me think this through as it deserves; I shall be with you shortly.",
    "Ah — give me just a moment to marshal my thoughts on this.",
]

# 10 TOPIC templates (Filler 2). {TOPIC} = spoken_name from topic_display_names.json.
TOPIC_TEMPLATES = [
    "And you speak of {TOPIC}.",
    "You ask, in particular, about {TOPIC}.",
    "More precisely — {TOPIC}.",
    "Your question touches {TOPIC}, in particular.",
    "Specifically, {TOPIC}.",
    "And the matter at hand is {TOPIC}.",
    "In particular, you raise {TOPIC}.",
    "The heart of it, I take it, is {TOPIC}.",
    "And within that, {TOPIC}.",
    "Which brings us to {TOPIC}.",
]


# ---------------------------------------------------------------- mappings (cached)
_THEME_OF: dict | None = None
_FALLBACK: set | None = None
_DISPLAY: dict | None = None


def theme_of_topic() -> dict:
    """topic_id -> theme_anchor (A..E or 'META'). Fused msme id -> B (11-vs-5 doc
    dominance, task A.2). Sourced from topic_map.json theme_anchor."""
    global _THEME_OF
    if _THEME_OF is None:
        tm = json.loads(Path(config.TOPIC_MAP_PATH).read_text(encoding="utf-8"))
        m = {tid: t.get("theme_anchor") for tid, t in tm["topics"].items()}
        m["msme_and_entrepreneurship+prosperity_fund_msme"] = "B"   # fused canonical id
        _THEME_OF = m
    return _THEME_OF


_TOPIC_IDS: list | None = None


def fallback_topics() -> set:
    """gmean-fallback centroids (corpus-mean; honors_received, robot_identity_meta).
    Excluded from the CLEAN runner-up so the topic margin is not degenerate."""
    global _FALLBACK
    if _FALLBACK is None:
        meta = json.loads(Path(config.CENTROIDS_META_PATH).read_text(encoding="utf-8"))
        _FALLBACK = set(meta.get("gmean_fallback_topics", []))
    return _FALLBACK


def topic_ids() -> list:
    """Centroid topic_ids in matrix order — aligns a route's full `cos` vector to ids."""
    global _TOPIC_IDS
    if _TOPIC_IDS is None:
        meta = json.loads(Path(config.CENTROIDS_META_PATH).read_text(encoding="utf-8"))
        _TOPIC_IDS = list(meta["topic_ids"])
    return _TOPIC_IDS


def display_names() -> dict:
    """topic_id -> {spoken, speakable} from topic_display_names.json (Part D)."""
    global _DISPLAY
    if _DISPLAY is None:
        d = json.loads(Path(config.TOPIC_DISPLAY_NAMES_PATH).read_text(encoding="utf-8"))
        _DISPLAY = {r["topic_id"]: {"spoken": r["spoken_name"], "speakable": r["speakable"]}
                    for r in d["topics"]}
    return _DISPLAY


def clean_margin(route: dict) -> tuple[float, str | None]:
    """Top-topic cosine minus the best NON-fallback runner-up cosine, using the full
    per-topic cosine vector in the route dict. Returns (margin, runner_up_topic)."""
    import numpy as np
    cos = route.get("cos")
    top = route["top_topic"]
    meta_ids = route.get("topic_ids") or (topic_ids() if cos is not None else None)
    if cos is None or meta_ids is None:            # harness may pass a lean route
        rt = route.get("routed_topics") or []
        for tid, c in rt:
            if tid != top and tid not in fallback_topics():
                return round(route["top_cosine"] - float(c), 4), tid
        return 0.0, None
    fb = fallback_topics()
    order = list(np.argsort(-np.asarray(cos)))
    for i in order:
        tid = meta_ids[i]
        if tid == top or tid in fb:
            continue
        return round(float(route["top_cosine"]) - float(cos[i]), 4), tid
    return 0.0, None


# ---------------------------------------------------------------- the decision
def decide(route: dict, gate: dict | None = None, late_route: bool = False) -> dict:
    """Map a route (+ input gate) to a filler decision. Pure, $0.

    Returns {theme, use_neutral, reason, topic_id, topic_spoken, topic_gated,
             theme_conf, topic_margin}. Gates (task A.2/A.3, C.7a-c):
      - late route (route didn't resolve in the wait window)   -> NEUTRAL
      - input gate not in_corpus (empty / identity probe)      -> NEUTRAL
      - theme_anchor == META                                   -> NEUTRAL (always)
      - not in_scope (top_cosine < OUT_OF_SCOPE_THRESHOLD)     -> NEUTRAL
      - top_cosine < THEME_CONF_THRESHOLD (GAP-leaning/low)    -> NEUTRAL
    TOPIC (Filler 2) additionally requires clean margin >= TOPIC_MARGIN_THRESHOLD
    AND the topic's speakable == YES (content-timing gate d is enforced at runtime).

    SUBJECT_FREE_MODE (Option D) short-circuits ALL of the below to a subject-free
    NEUTRAL decision — no theme, no topic — because the router's real top-1 accuracy
    is too low to name a subject safely (Phase-2 STOP). The gating code is kept intact
    for a future routing-accuracy track that would flip SUBJECT_FREE_MODE off.
    """
    if SUBJECT_FREE_MODE:
        return {"theme": None, "use_neutral": True, "reason": "subject_free_mode",
                "topic_id": None, "topic_spoken": None, "topic_gated": False,
                "theme_conf": None, "topic_margin": None, "runner_up": None}
    top = route["top_topic"]
    conf = float(route["top_cosine"])
    theme = theme_of_topic().get(top)
    margin, ru = clean_margin(route)

    def neutral(reason):
        return {"theme": None, "use_neutral": True, "reason": reason,
                "topic_id": None, "topic_spoken": None, "topic_gated": False,
                "theme_conf": round(conf, 4), "topic_margin": margin, "runner_up": ru}

    if late_route:
        return neutral("late_route")
    if gate and gate.get("scope") not in (None, "in_corpus"):
        return neutral(f"input_gate:{gate.get('scope')}")
    if theme == "META":
        return neutral("theme_meta")
    if not route.get("in_scope", True):
        return neutral("out_of_scope")
    if conf < config.THEME_CONF_THRESHOLD:
        return neutral(f"low_confidence({conf:.4f}<{config.THEME_CONF_THRESHOLD})")
    if theme not in THEMES:
        return neutral(f"no_theme_anchor({theme})")

    # THEME clip fires. Now the TOPIC gate (a: theme passed; b: margin; c: speakable).
    dn = display_names().get(top, {})
    speakable = dn.get("speakable") == "YES"
    spoken = dn.get("spoken")
    topic_gated = bool(margin >= config.TOPIC_MARGIN_THRESHOLD and speakable and spoken)
    return {"theme": theme, "use_neutral": False,
            "reason": "theme" + ("+topic" if topic_gated else "_only"),
            "topic_id": top if topic_gated else None,
            "topic_spoken": spoken if topic_gated else None,
            "topic_gated": topic_gated,
            "theme_conf": round(conf, 4), "topic_margin": margin, "runner_up": ru,
            "topic_speakable": speakable, "topic_margin_pass": margin >= config.TOPIC_MARGIN_THRESHOLD}


# ---------------------------------------------------------------- grammar check (C.9)
# Documented, reproducible rules. Drop a template x spoken-name pairing (rather than
# mangle a spoken sentence) when:
#   R1 PLURAL-COPULA : templates framed "... is {TOPIC}." (idx 5,7 = #6,#8) clash with
#                      a PLURAL-headed name ("is my recognitions / Judicial Appointments").
#   R2 POSSESSIVE-RAISE: template "... you raise {TOPIC}." (idx 6 = #7) clashes with a
#                      first-person possessive name ("you raise my recognitions/my book").
#   R3 COMMA-PILEUP  : template "... {TOPIC}, in particular." (idx 3 = #4) clashes with a
#                      name that already contains a comma (trailing clause -> comma run-on).
_COPULA_TEMPLATES = {5, 7}     # 0-based indices of "#6" and "#8"
_RAISE_TEMPLATE = 6            # 0-based index of "#7"
_COMMA_TEMPLATE = 3            # 0-based index of "#4"
_SINGULAR_S = {"geopolitics", "politics", "ethics", "news", "sampaloc",
               "process", "business", "consensus"}  # end in s but singular


def is_plural_headed(spoken: str) -> bool:
    last = re.sub(r"[^A-Za-z]", "", spoken.split()[-1]).lower()
    return last.endswith("s") and last not in _SINGULAR_S


def grammar_ok(template_idx: int, spoken: str) -> tuple[bool, str]:
    """(ok, rule) — False + the rule id when the pairing must be dropped."""
    first_person = spoken.lower().startswith("my ")
    if template_idx in _COPULA_TEMPLATES and is_plural_headed(spoken):
        return False, "R1_plural_copula"
    if template_idx == _RAISE_TEMPLATE and first_person:
        return False, "R2_possessive_raise"
    if template_idx == _COMMA_TEMPLATE and "," in spoken:
        return False, "R3_comma_pileup"
    return True, ""


def allowed_templates(spoken: str) -> list[int]:
    """Template indices that pass the grammar check for this spoken name."""
    return [i for i in range(len(TOPIC_TEMPLATES)) if grammar_ok(i, spoken)[0]]


def render_topic(template_idx: int, spoken: str) -> str:
    return TOPIC_TEMPLATES[template_idx].replace("{TOPIC}", spoken)


def render_theme(theme: str, variant_idx: int) -> str:
    return THEME_VARIANTS[variant_idx].replace("{T}", THEME_SPOKEN[theme])
