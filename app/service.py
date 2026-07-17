"""
W1.8 — service API seam (versioned) over the deterministic retrieval path.

SERVICE CONTRACT (v1.0) — a stable boundary for the Track-B robot front-end:

  request  = {"query_text": str}
  response = {
      "answer": str,                       # composed in-voice answer
      "envelope": {
          "service_version": str,
          "retrieval_arch": str,
          "query": str,
          "route":   {top_topic, top_cosine, in_scope, routed_topics, fallback_global},
          "retrieval": {universe_size, dense_n, sparse_n, aligned, selected_chunk_ids, scores},
          "directives": {register, theme, disclaimer, date_note},
          "timing_ms": {embed_query, route_centroids, retrieve_rrf_cutoff, compose, total},
          "llm_calls_before_composition": int,   # MUST be 0
          "composer_model": str,
      }
  }

This is the W1.8 boundary + a working grounded Sonnet call ONLY. Streaming,
full ENVELOPE discipline, max_tokens governance, timeouts/retries = W2.1.
Every knob from config.py; no new literals.

CLI:  python app/service.py --query "..." [--allowlist v4]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
import config
sys.path.insert(0, str(_REPO_ROOT / "app"))
import retrieval  # noqa: E402

# Route Python TLS through the Windows cert store (schannel) so the native
# anthropic SDK works on hosts where Python's OpenSSL TLS is intact. MUST run
# before any anthropic/httpx use. (On THIS build laptop a security product
# injects an applink-less OpenSSL that hard-aborts ALL outbound Python HTTPS
# below this layer, so truststore can't help here — the transport falls back to
# schannel_curl; see config.COMPOSER_HTTP_TRANSPORT.) Does NOT disable verification.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

_CHUNK_TEXT = None
_VOICE_CARD = None
_THEME_OF = None

# theme_anchor -> spoken register cue (from PROJECT.md §9 / build_topic_map)
_REGISTER = {
    "A": "ceremonial, doctrinal; sparing wit",
    "B": "case-analytical with warm openers",
    "C": "testimonial, gentle and self-deprecating",
    "D": "ceremonial with head-table humor",
    "E": "reflective, pedagogical, warm",
    "META": "transparent, self-aware",
}
_THEME_A_DISCLAIMER = ("Speak to the principle, not to any matter still pending before the "
                       "courts; mark out-of-record extensions softly.")
_TEMPORAL = re.compile(r"\b(today|now|current(ly)?|this year|recent(ly)?|latest|nowadays|"
                       r"these days|as of|when did|what year)\b", re.I)


def _chunk_text():
    global _CHUNK_TEXT
    if _CHUNK_TEXT is None:
        _CHUNK_TEXT = {}
        for line in (_REPO_ROOT / "corpus" / "index" / "chunks.jsonl").read_text(
                encoding=config.FILE_ENCODING).splitlines():
            c = json.loads(line)
            _CHUNK_TEXT[c["chunk_id"]] = c["text"]
    return _CHUNK_TEXT


def _voice_card():
    global _VOICE_CARD
    if _VOICE_CARD is None:
        _VOICE_CARD = (config.REPO_ROOT / "corpus" / "voice" / "voice_card.md").read_text(
            encoding=config.FILE_ENCODING)
    return _VOICE_CARD


def _theme_of(topic_id: str) -> str:
    """theme_anchor (A/B/C/D/E/META) for a (possibly merged 'a+b') topic id.

    Sourced from the AUTHORITATIVE taxonomy (corpus/voice/topic_map.json). theme_anchor
    is a taxonomy property, NOT a centroid-artifact field — the OPS-2 full-corpus centroid
    meta legitimately omits it (build_centroids_fullcorpus.py), which used to raise
    KeyError here. Falls back to the centroids meta iff it still carries theme_anchor
    (older pilot-slice metas did), then to '' (neutral register). KeyError-proof."""
    global _THEME_OF
    if _THEME_OF is None:
        m: dict[str, str] = {}
        try:
            tmap = json.loads((_REPO_ROOT / "corpus" / "voice" / "topic_map.json")
                              .read_text(encoding="utf-8")).get("topics", [])
            for t in (tmap.values() if isinstance(tmap, dict) else tmap):
                if isinstance(t, dict) and t.get("id") and t.get("theme_anchor"):
                    m[t["id"]] = t["theme_anchor"]
        except Exception:
            pass
        try:   # back-compat: older centroid metas embedded theme_anchor
            meta = json.loads(Path(config.CENTROIDS_META_PATH).read_text(encoding="utf-8"))
            for r in meta.get("topics", []):
                if r.get("theme_anchor") and r.get("topic_id") not in m:
                    m[r["topic_id"]] = r["theme_anchor"]
        except Exception:
            pass
        _THEME_OF = m
    return _THEME_OF.get(topic_id.split("+")[0], "")


def _allowlist(version: str) -> set:
    return set(l.split(",")[0].strip() for l in
               (_REPO_ROOT / "reports" / "pilot-eval subset" / f"pilot_subset_frozen_{version}.csv")
               .read_text(encoding="utf-8-sig").splitlines()
               if not l.startswith("#") and not l.startswith("doc_id"))


def _directives(query: str, route_info: dict) -> dict:
    theme = _theme_of(route_info["top_topic"])
    return {
        "register": _REGISTER.get(theme, ""),
        "theme": theme,
        "disclaimer": _THEME_A_DISCLAIMER if theme == "A" else "",
        "date_note": (f"Today is {date.today().isoformat()}; you reason from your published "
                      "record, which may predate the asker's 'now'.") if _TEMPORAL.search(query) else "",
    }


# External tool path (system tool, env-overridable — same pattern as cj_chat PIPER_BIN).
import os
_CURL = os.environ.get("CJ_CURL", r"C:\Windows\System32\curl.exe")


def _api_key() -> str:
    try:
        from dotenv import load_dotenv
        for p in (_REPO_ROOT / "app" / ".env", _REPO_ROOT / ".env"):
            if p.exists():
                load_dotenv(p, override=False)
    except Exception:
        pass
    k = os.environ.get("ANTHROPIC_API_KEY")
    if not k:
        raise RuntimeError("ANTHROPIC_API_KEY not set (looked in app/.env, .env, env).")
    return k


_TRANSPORT = None


def _resolve_transport() -> str:
    """native_sdk | schannel_curl. 'auto' probes native TLS ONCE in an isolated
    subprocess (the failure mode is a hard process abort, so it can't be caught
    in-process) and caches the result: native_sdk if Python HTTPS works, else
    schannel_curl."""
    global _TRANSPORT
    if _TRANSPORT:
        return _TRANSPORT
    t = config.COMPOSER_HTTP_TRANSPORT
    if t in ("native_sdk", "schannel_curl"):
        _TRANSPORT = t
        return t
    import subprocess
    probe = ("import truststore; truststore.inject_into_ssl(); import httpx; "
             "httpx.get('https://api.anthropic.com/', timeout=10)")
    try:
        r = subprocess.run([sys.executable, "-c", probe], capture_output=True, timeout=30)
        _TRANSPORT = "native_sdk" if r.returncode == 0 else "schannel_curl"
    except Exception:
        _TRANSPORT = "schannel_curl"
    print(f"[service] transport auto-resolved to {_TRANSPORT}", file=sys.stderr)
    return _TRANSPORT


def _messages(system_text: str, user_text: str, max_tokens: int | None = None) -> str:
    """Anthropic messages call via the resolved transport (native_sdk preferred;
    schannel_curl fallback where Python HTTPS is shadow-aborted)."""
    body = {
        "model": config.COMPOSER_MODEL_ID, "max_tokens": max_tokens or config.MAX_TOKENS,
        "system": [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user_text}],
    }
    if _resolve_transport() == "schannel_curl":
        import subprocess
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        Path(path).write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        try:
            out = subprocess.run(
                # --ssl-no-revoke skips OCSP/CRL REVOCATION checks only (schannel
                # often can't reach the responder); the cert CHAIN is still fully
                # verified — verification is NOT disabled.
                [_CURL, "-s", "--ssl-no-revoke", "--fail-with-body",
                 "https://api.anthropic.com/v1/messages",
                 "-H", f"x-api-key: {_api_key()}", "-H", "anthropic-version: 2023-06-01",
                 "-H", "content-type: application/json", "-d", f"@{path}"],
                capture_output=True, text=True, encoding="utf-8",
                timeout=config.COMPOSER_TIMEOUT_S)
        finally:
            os.unlink(path)
        if out.returncode != 0 and not out.stdout:
            raise RuntimeError(f"curl transport failed (exit {out.returncode}): {out.stderr[:200]}")
        resp = json.loads(out.stdout)
        if resp.get("type") == "error" or "content" not in resp:
            raise RuntimeError(f"anthropic error: {resp.get('error', resp)}")
        return resp["content"][0]["text"].strip()
    # default SDK path
    from anthropic import Anthropic
    resp = Anthropic(max_retries=config.MAX_RETRIES, api_key=_api_key()).messages.create(**body)
    return resp.content[0].text.strip()


_DOC_JSON = None


def _doc_json():
    """Lazy doc_id -> corpus JSON (for the OPTIONAL signature palette only)."""
    global _DOC_JSON
    if _DOC_JSON is None:
        import glob
        _DOC_JSON = {}
        for p in glob.glob(str(_REPO_ROOT / "corpus" / "**" / "*.json"), recursive=True):
            try:
                d = json.loads(Path(p).read_text(encoding=config.FILE_ENCODING))
            except Exception:
                continue
            if isinstance(d, dict) and "id" in d:
                _DOC_JSON[d["id"]] = d
    return _DOC_JSON


def build_payload(query: str, selected, directives: dict,
                  top_k: int | None = None, char_budget: int | None = None,
                  signature: bool | None = None) -> str:
    """Assemble the SLIM user payload: top-k matched CHUNKS + LEAN directives
    (theme/register + Theme-A compliance) ONLY. Per-doc enrichment (stances,
    decision_framework_signals, target_audience, register_markers, one_paragraph_
    summary) is DIAGNOSTIC-ONLY and NEVER included. signature_phrases enter only
    as an OPTIONAL palette when config.COMPOSER_SIGNATURE_PALETTE is on.

    [W2.2] top_k / char_budget are config-driven (defaults behavior-preserving:
    COMPOSER_TOP_K=MAX_K, COMPOSER_CHUNK_CHAR_BUDGET=0/unlimited). Exposed so the
    latency harness can stream the same payload for TTFT."""
    top_k = config.COMPOSER_TOP_K if top_k is None else top_k
    char_budget = config.COMPOSER_CHUNK_CHAR_BUDGET if char_budget is None else char_budget
    signature = config.COMPOSER_SIGNATURE_PALETTE if signature is None else signature

    txt = _chunk_text()
    chosen = selected[:top_k]                       # top-k lever
    # [ENTITY-RESCUE] additive: guarantee any rescued chunk reaches the payload
    # even if it fell outside top_k. Never removes a normal chunk; a no-op when
    # nothing is flagged rescued (dark default) -> payload byte-identical.
    if len(selected) > top_k:
        seen = {c for c, _s, _d in chosen}
        for item in selected[top_k:]:
            if len(item) > 2 and item[2].get("rescued") and item[0] not in seen:
                chosen.append(item); seen.add(item[0])
    kept, used = [], 0
    for cid, _s, _d in chosen:                       # char-budget lever (rank-priority)
        t = txt.get(cid, "")
        if char_budget and char_budget > 0 and kept and used + len(t) > char_budget:
            break
        kept.append((cid, t)); used += len(t)
    blocks = "\n\n".join(f"[{cid}]\n{t}" for cid, t in kept)

    dlines = [f"- register: {directives['register']}"]
    if directives["disclaimer"]:
        dlines.append(f"- {directives['disclaimer']}")
    if directives["date_note"]:
        dlines.append(f"- {directives['date_note']}")
    if signature and kept:                            # OPTIONAL signature palette
        phrases = (_doc_json().get(kept[0][0].split("::")[0], {}) or {}).get("signature_phrases") or []
        if phrases:
            dlines.append("- signature phrases (use ONLY when natural): "
                          + "; ".join(phrases[:3]))
    return (f"<source_chunks>\n{blocks}\n</source_chunks>\n\n"
            f"<directives>\n" + "\n".join(dlines) + "\n</directives>\n\n"
            f"Answer in your own voice, grounded ONLY in the source chunks above. "
            f"Do not invent specifics.\n\n<question>\n{query}\n</question>")


def _compose(query: str, selected, directives: dict) -> str:
    """Grounded Sonnet call over a SLIM payload (top-k chunks, not whole docs)."""
    return _messages(_voice_card(), build_payload(query, selected, directives))


# ===========================================================================
# [W2.1] Production composer: stream PROSE first (TTFT preserved); carry the
# ENVELOPE metadata as a SEPARATE TRAILING block after a sentinel — the visible
# answer is NEVER wrapped in JSON that must fully arrive before rendering.

def _composer_system() -> str:
    """Voice Card + W2.1 composer directives (length discipline + envelope
    contract). Assembled into ONE cached system block."""
    s = config.COMPOSER_ENVELOPE_SENTINEL
    directives = (
        "\n\n=== COMPOSER DIRECTIVES (W2.1) ===\n"
        f"- Length discipline: answer in {config.COMPOSER_TARGET_PARAGRAPHS} short paragraphs "
        "unless the asker explicitly requests more. Be complete but disciplined; never pad.\n"
        f"- After the prose answer, on a NEW LINE output this sentinel EXACTLY:\n{s}\n"
        "- Immediately after the sentinel, output ONE line of JSON metadata and nothing else:\n"
        '  {"doc_ids_cited": [...], "register_used": "...", "anecdotes_deployed": [...], '
        '"signature_phrases_used": [...]}\n'
        '  doc_ids_cited = the source doc_ids you actually drew on (e.g. "CA242"; strip ::cNNN).\n'
        "- The sentinel line and the JSON are SYSTEM METADATA, not part of the spoken answer; "
        "write no prose after the JSON.")
    if config.COMPOSER_OOS_DECLINE_ENABLED:            # [W3.7] designed OOS backstop
        directives += "\n" + config.COMPOSER_OOS_DECLINE_TEXT
    return _voice_card() + directives


def _split_envelope(raw: str) -> tuple:
    """Split raw composer output into (prose, envelope_dict) on the sentinel.
    Tolerant: missing/garbled envelope -> {} (prose is never lost)."""
    s = config.COMPOSER_ENVELOPE_SENTINEL
    idx = raw.find(s)
    if idx < 0:
        return raw.strip(), {}
    prose = raw[:idx].strip()
    tail = raw[idx + len(s):]
    a, b = tail.find("{"), tail.rfind("}")
    if a >= 0 and b > a:
        try:
            return prose, json.loads(tail[a:b + 1])
        except Exception:
            return prose, {"_parse_error": tail[a:b + 1][:200]}
    return prose, {}


_CLIENT = None


def _client():
    global _CLIENT
    if _CLIENT is None:
        from anthropic import Anthropic
        _CLIENT = Anthropic(max_retries=config.MAX_RETRIES, api_key=_api_key())
    return _CLIENT


def _stream_native(client, system: str, payload: str, on_text) -> dict:
    """One streamed composition. PROSE chunks go to on_text as they arrive (a
    partial-sentinel tail is held back so the sentinel never leaks to the user);
    the ENVELOPE after the sentinel is parsed, not spoken."""
    s = config.COMPOSER_ENVELOPE_SENTINEL
    buf = []
    emitted = 0
    ttft = None
    t0 = time.perf_counter()
    with client.messages.stream(
            model=config.COMPOSER_MODEL_ID, max_tokens=config.COMPOSER_MAX_TOKENS,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": payload}]) as st:
        for piece in st.text_stream:
            if ttft is None:
                ttft = round((time.perf_counter() - t0) * 1000, 1)
            buf.append(piece)
            if on_text:
                whole = "".join(buf)
                cut = whole.find(s)
                safe = cut if cut >= 0 else max(0, len(whole) - len(s))
                if safe > emitted:
                    on_text(whole[emitted:safe])
                    emitted = safe
        final = st.get_final_message()
    raw = "".join(buf)
    if on_text:  # flush any held-back prose tail (when no sentinel was emitted)
        cut = raw.find(s)
        end = cut if cut >= 0 else len(raw)
        if end > emitted:
            on_text(raw[emitted:end])
    prose, env = _split_envelope(raw)
    return {"answer": prose, "envelope": env, "raw": raw, "ttft_ms": ttft,
            "stop_reason": final.stop_reason, "degraded": False, "usage": final.usage}


def compose_streamed(query: str, selected, directives: dict, client=None, on_text=None,
                     top_k=None) -> dict:
    """Production composer with bounded retries + backoff + graceful in-voice
    degradation. Returns {answer, envelope, raw, ttft_ms, stop_reason, degraded,
    usage}. KEEPS Sonnet; the router stays zero-LLM (this is the only round-trip).
    top_k overrides the payload chunk cap (used by the W2.6 expand retry)."""
    system = _composer_system()
    payload = build_payload(query, selected, directives, top_k=top_k)
    native = _resolve_transport() == "native_sdk"
    last = None
    for attempt in range(config.COMPOSER_MAX_RETRIES + 1):
        try:
            if native:
                return _stream_native(client or _client(), system, payload, on_text)
            # curl fallback (no true streaming): one-shot, then split the envelope
            raw = _messages(system, payload, max_tokens=config.COMPOSER_MAX_TOKENS)
            prose, env = _split_envelope(raw)
            return {"answer": prose, "envelope": env, "raw": raw, "ttft_ms": None,
                    "stop_reason": None, "degraded": False, "usage": None}
        except Exception as e:
            last = e
            if attempt < config.COMPOSER_MAX_RETRIES:
                time.sleep(config.COMPOSER_BACKOFF_BASE_S * (2 ** attempt))
    return {"answer": config.COMPOSER_FALLBACK_MESSAGE, "envelope": {}, "raw": "",
            "ttft_ms": None, "stop_reason": "error_fallback", "degraded": True,
            "usage": None, "error": f"{type(last).__name__}: {last}"}


# ===========================================================================
# [W2.6] Expand-on-demand fallback — COMPOSE-SIDE, DARK by default. On a weakly-
# grounded first compose, do ONE bounded retry with fuller parent-doc context and
# recompose. HARD-CAPPED at 1 retry (no loop). With the flag OFF this is a
# verbatim pass-through of compose_streamed (byte-identical, no added keys).
_DOC_CHUNKS = None


def _doc_chunk_ids():
    """Lazy doc_id -> [chunk_ids] (in order) from the chunk store."""
    global _DOC_CHUNKS
    if _DOC_CHUNKS is None:
        _DOC_CHUNKS = {}
        for line in (_REPO_ROOT / "corpus" / "index" / "chunks.jsonl").read_text(
                encoding=config.FILE_ENCODING).splitlines():
            if not line.strip():
                continue
            c = json.loads(line)
            _DOC_CHUNKS.setdefault(c["doc_id"], []).append(c["chunk_id"])
    return _DOC_CHUNKS


def _weak_grounding(comp: dict) -> bool:
    """Deterministic weak-grounding trigger (NO LLM): degraded, or cites fewer
    than the config floor (floor=1 -> fire only on empty citations)."""
    if comp.get("degraded"):
        return True
    cited = (comp.get("envelope") or {}).get("doc_ids_cited") or []
    return len(cited) < config.EXPAND_TRIGGER_MIN_CITATIONS


def _expand_context(selected):
    """Fuller context for the retry: the WHOLE parent doc of the top chunk +
    the original nucleus, deduped, capped at EXPAND_MAX_CHUNKS. build_payload uses
    only the chunk_id, so score/detail are placeholders."""
    if not selected:
        return selected
    top_doc = selected[0][0].split("::")[0]
    doc_chunks = _doc_chunk_ids().get(top_doc, [])
    existing = [c for c, _s, _d in selected]
    merged = list(dict.fromkeys(doc_chunks + existing))[:config.EXPAND_MAX_CHUNKS]
    return [(c, 0.0, {}) for c in merged]


def compose_with_expand(query: str, selected, directives: dict, client=None, on_text=None) -> dict:
    """compose_streamed + optional ONE-shot expand retry. DARK by default: when
    EXPAND_ON_DEMAND_ENABLED is False, returns compose_streamed's result VERBATIM
    (no retry, no added keys) — behavior is byte-identical to pre-W2.6."""
    comp = compose_streamed(query, selected, directives, client=client, on_text=on_text)
    if not config.EXPAND_ON_DEMAND_ENABLED:
        return comp                                   # ← no-regression: verbatim pass-through

    comp["triggered"] = _weak_grounding(comp)
    comp["expanded"] = False
    if not comp["triggered"]:
        return comp
    # ONE bounded retry — structural hard cap = 1 (no loop): compose_streamed is
    # called at most twice total (first pass + this single retry).
    exp_selected = _expand_context(selected)
    comp2 = compose_streamed(query, exp_selected, directives, client=client,
                             on_text=None, top_k=config.EXPAND_MAX_CHUNKS)
    comp2["triggered"] = True
    comp2["expanded"] = True
    comp2["first_pass"] = {"answer": comp["answer"], "envelope": comp["envelope"]}
    if isinstance(comp2.get("envelope"), dict):
        comp2["envelope"]["expanded"] = True          # auditable in the ENVELOPE
    return comp2


def answer(query_text: str, allowlist_version: str = "v4", on_text=None) -> dict:
    """Service entry point. Returns {answer, envelope} per the v1.0 contract,
    now with the W2.1 streamed composer + trailing composer_envelope. Pass
    on_text to consume the PROSE as it streams (TTFT preserved)."""
    allow = _allowlist(allowlist_version)
    r = retrieval.run(query_text, allow)
    ri, rr, timing = r["route"], r["retrieval"], r["timing"]
    directives = _directives(query_text, ri)

    t0 = time.perf_counter()
    # W2.6 expand wrapper — verbatim compose_streamed when EXPAND_ON_DEMAND_ENABLED
    # is False (dark default), so answer() is unchanged unless the flag is set.
    comp = compose_with_expand(query_text, rr["selected"], directives, on_text=on_text)
    timing["compose_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    timing["total_ms"] = round(sum(timing.values()), 1)

    return {
        "answer": comp["answer"],
        "envelope": {
            "service_version": config.SERVICE_VERSION,
            "retrieval_arch": config.RETRIEVAL_ARCH_VERSION,
            "query": query_text,
            "route": {"top_topic": ri["top_topic"], "top_cosine": ri["top_cosine"],
                      "in_scope": ri["in_scope"], "routed_topics": ri["routed_topics"],
                      "fallback_global": rr["fallback_global"]},
            "retrieval": {"universe_size": rr["universe_size"], "dense_n": rr["dense_n"],
                          "sparse_n": rr["sparse_n"], "aligned": rr["aligned"],
                          "selected_chunk_ids": [c for c, _, _ in rr["selected"]],
                          "scores": [{"chunk_id": c, "score": s, **d} for c, s, d in rr["selected"]]},
            "directives": directives,
            "timing_ms": timing,
            "llm_calls_before_composition": r["llm_calls_before_composition"],
            "composer_model": config.COMPOSER_MODEL_ID,
            "composer_transport": _resolve_transport(),
            # W2.1 trailing composer metadata (self-reported by the composer)
            "composer_envelope": comp["envelope"],
            "composer_stop_reason": comp["stop_reason"],
            "composer_ttft_ms": comp["ttft_ms"],
            "composer_degraded": comp["degraded"],
            "composer_max_tokens": config.COMPOSER_MAX_TOKENS,
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True)
    ap.add_argument("--allowlist", default="v4")
    args = ap.parse_args(argv)
    out = answer(args.query, args.allowlist)
    env = out["envelope"]
    print("=== ROUTE ===")
    print(f"  top_topic={env['route']['top_topic']} cos={env['route']['top_cosine']} "
          f"in_scope={env['route']['in_scope']} fallback_global={env['route']['fallback_global']}")
    print(f"  routed_topics={env['route']['routed_topics']}")
    print("=== RETRIEVAL (universe %d; dense=%d sparse=%d aligned=%s) ==="
          % (env['retrieval']['universe_size'], env['retrieval']['dense_n'],
             env['retrieval']['sparse_n'], env['retrieval']['aligned']))
    for s in env["retrieval"]["scores"]:
        print(f"  {s['chunk_id']:16} score={s['score']} (passage={s['passage']} "
              f"affinity={s['affinity']} d_rank={s['dense_rank']} s_rank={s['sparse_rank']})")
    print("=== DIRECTIVES ===", env["directives"])
    print("=== PER-STAGE TIMING (ms) ===", env["timing_ms"])
    print(f"  >>> llm_calls_before_composition = {env['llm_calls_before_composition']} "
          f"(compose is the ONLY LLM round-trip)")
    print("=== ANSWER ===")
    print(out["answer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
