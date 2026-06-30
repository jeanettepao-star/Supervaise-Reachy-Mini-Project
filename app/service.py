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
    """theme_anchor for a (possibly merged 'a+b') topic id."""
    global _THEME_OF
    if _THEME_OF is None:
        meta = json.loads(Path(config.CENTROIDS_META_PATH).read_text(encoding="utf-8"))
        _THEME_OF = {r["topic_id"]: r["theme_anchor"] for r in meta.get("topics", [])}
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


def _messages(system_text: str, user_text: str) -> str:
    """Anthropic messages call via the resolved transport (native_sdk preferred;
    schannel_curl fallback where Python HTTPS is shadow-aborted)."""
    body = {
        "model": config.COMPOSER_MODEL_ID, "max_tokens": config.MAX_TOKENS,
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


def build_payload(query: str, selected, directives: dict) -> str:
    """Assemble the SLIM user payload (top-k chunks + lean directives). Exposed
    so the W1.9 latency harness can stream the same payload for TTFT."""
    txt = _chunk_text()
    blocks = "\n\n".join(f"[{cid}]\n{txt.get(cid, '')}" for cid, _, _ in selected)
    dlines = [f"- register: {directives['register']}"]
    if directives["disclaimer"]:
        dlines.append(f"- {directives['disclaimer']}")
    if directives["date_note"]:
        dlines.append(f"- {directives['date_note']}")
    return (f"<source_chunks>\n{blocks}\n</source_chunks>\n\n"
            f"<directives>\n" + "\n".join(dlines) + "\n</directives>\n\n"
            f"Answer in your own voice, grounded ONLY in the source chunks above. "
            f"Do not invent specifics.\n\n<question>\n{query}\n</question>")


def _compose(query: str, selected, directives: dict) -> str:
    """Grounded Sonnet call over a SLIM payload (top-k chunks, not whole docs)."""
    return _messages(_voice_card(), build_payload(query, selected, directives))


def answer(query_text: str, allowlist_version: str = "v4") -> dict:
    """Service entry point. Returns {answer, envelope} per the v1.0 contract."""
    allow = _allowlist(allowlist_version)
    r = retrieval.run(query_text, allow)
    ri, rr, timing = r["route"], r["retrieval"], r["timing"]
    directives = _directives(query_text, ri)

    t0 = time.perf_counter()
    ans = _compose(query_text, rr["selected"], directives)
    timing["compose_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    timing["total_ms"] = round(sum(timing.values()), 1)

    return {
        "answer": ans,
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
