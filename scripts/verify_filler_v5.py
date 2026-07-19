"""FILLER v5 Part F — $0 verification harness. Stubbed routes + composes + a FakeOAI
(NO network, NO model load, NO paid TTS). Drives voice_job.start_job through the seven
required scenarios and prints every chain verbatim, then lists the 53 pre-synth clip
durations and the grammar-check drops.

Run:  .venv/Scripts/python.exe scripts/verify_filler_v5.py
"""
import json
import sys
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import config
config.FILLER_V5_ENABLED = True
config.STREAM_TTS_ENABLED = False
config.FILLER_ROUTE_WAIT_MS = 300
import filler_route
import voice_job
_ORIG_SYNTH_TOPIC = voice_job.synth_topic       # saved so --smoke can un-monkeypatch to the real path


# ----- fakes ($0; no network) -----
class _Speech:
    def __init__(self, delay, mode="ok"): self._d = delay; self._m = mode; self._n = 0
    def create(self, model, voice, input, speed=None, **kw):
        self._n += 1
        if self._m == "throw" or (self._m == "throw_once" and self._n == 1):
            raise RuntimeError("forced tts-1 synth failure")
        time.sleep(self._d)
        return types.SimpleNamespace(content=b"\xff\xfb\x90\x00" + b"\x00" * 128)


class FakeOAI:
    def __init__(self, content_synth_delay=0.05, mode="ok"):
        self.audio = types.SimpleNamespace(speech=_Speech(content_synth_delay, mode))


def fake_theme_decks(theme_dur=4.5, neutral_dur=1.2):
    decks = {}
    for t in filler_route.THEMES:
        decks[t] = voice_job.Deck([(f"theme_{t}_{i:02d}", b"x", "mp3", theme_dur) for i in range(1, 11)])
    decks["NEUTRAL"] = voice_job.Deck([(f"neutral_{i:02d}", b"x", "mp3", neutral_dur) for i in range(1, 4)])
    return decks


def stub_route(top_topic, conf, runner=None, runner_cos=None, in_scope=True):
    rt = [(top_topic, conf)]
    if runner is not None:
        rt.append((runner, runner_cos))
    return lambda q: {"top_topic": top_topic, "top_cosine": conf, "in_scope": in_scope,
                      "routed_topics": rt}


def stub_gate(scope="in_corpus"):
    return lambda q: {"scope": scope}


def stub_retrieve():
    return lambda q, allow, ri: {"selected": [("CA001::0", 0.9, {})]}


def stub_compose(ttft_s, sentences=("This is the considered answer.",)):
    def _c(q, selected, directives, client=None, on_text=None, **kw):
        time.sleep(ttft_s)
        for s in sentences:
            if on_text:
                on_text(s + " ")
        return {"answer": " ".join(sentences), "envelope": {"doc_ids_cited": ["CA001"]},
                "stop_reason": "end_turn", "usage": None, "degraded": False}
    return _c


def _no_hole(job):
    """The strict-order invariant: chunk indices contiguous (no permanent hole) AND
    every reservation resolved (reserved == submitted + released)."""
    idxs = sorted(c["i"] for c in job["chunks"])
    contiguous = (not idxs) or idxs == list(range(idxs[0], idxs[-1] + 1))
    balanced = job["queue_reserved"] == job["queue_submitted"] + job["queue_released"]
    no_dup = len(idxs) == len(set(idxs))
    return contiguous and balanced and no_dup


def run_case(name, route_fn, gate_fn, ttft, topic_synth_delay=1.2, cache_hit=False,
             theme_dur=4.5, route_delay=0.0, content_mode="ok", content_delay=0.05,
             topic_mode="ok", watchdog_s=None, n_sentences=1):
    if watchdog_s is not None:
        voice_job.WATCHDOG_S = watchdog_s
    # monkeypatch the topic synth ($0, controlled timing; no disk, no network)
    def fake_synth_topic(oai, voice, topic_id, template_idx, spoken):
        time.sleep(topic_synth_delay)
        if topic_mode == "throw":
            raise RuntimeError("forced topic synth failure")
        return b"x", "mp3", cache_hit, 1.3
    voice_job.synth_topic = fake_synth_topic
    rf = route_fn if route_delay == 0.0 else (lambda q: (time.sleep(route_delay), route_fn(q))[1])
    decks = fake_theme_decks(theme_dur=theme_dur)
    seq_state = {"turn": 0, "topic_template_decks": {}}
    sents = tuple(f"Sentence {k} of the answer." for k in range(1, n_sentences + 1))
    job = voice_job.start_job("Q?", "TEST", 0.5, FakeOAI(content_delay, content_mode), set(),
                              None, "onyx", 0, decks, seq_state, _route_fn=rf, _gate_fn=gate_fn,
                              _retrieve_fn=stub_retrieve(), _compose_fn=stub_compose(ttft, sents))
    while not job["done"]:
        time.sleep(0.02)
    voice_job.WATCHDOG_S = 8.0                          # restore default after the case
    chain = "-".join(job["chain"])
    disp = chain.replace("-C", "-[silence]-C", 1) if job.get("silence_gap_ms") else chain
    return {"case": name, "chain": chain, "chain_annot": disp,
            "theme_used": job["theme_used"], "route_confidence": job["route_confidence"],
            "topic_used": job["topic_used"], "topic_margin": job["topic_margin"],
            "cache_hit": job["cache_hit"], "fallback_used": job["fallback_used"],
            "silence_gap_ms": job["silence_gap_ms"], "topic_skipped": job["topic_skipped"],
            "reason": (job["filler_decision"] or {}).get("reason"), "error": job["error"],
            "queue": f"{job['queue_reserved']}={job['queue_submitted']}+{job['queue_released']}",
            "backfills": len(job["watchdog_backfills"]), "synth_errors": len(job["synth_errors"]),
            "no_hole": _no_hole(job)}


CASES = [
    # 1 confident + separated + slow -> T-P-C
    dict(name="1 confident+separated/slow", ttft=3.5,
         route_fn=stub_route("international_law_disputes", 0.62, "icc_and_duterte", 0.59),
         gate_fn=stub_gate()),
    # 2 confident + near-tie -> T-C (topic silent)
    dict(name="2 confident+near-tie", ttft=1.0,
         route_fn=stub_route("constitutional_doctrine", 0.62, "due_process", 0.617),
         gate_fn=stub_gate()),
    # 3 low-confidence -> N-C
    dict(name="3 low-confidence", ttft=1.0,
         route_fn=stub_route("faith_journey", 0.50, "family_and_marriage", 0.49),
         gate_fn=stub_gate()),
    # 4 META route -> N-C
    dict(name="4 META route", ttft=1.0,
         route_fn=stub_route("robot_identity_meta", 0.62, "honors_received", 0.61),
         gate_fn=stub_gate()),
    # 5 X35-class stray (weather 0.5072) -> N-C
    dict(name="5 X35 stray (weather)", ttft=1.0,
         route_fn=stub_route("friendships_and_civic_circles", 0.5072, "honors_received", 0.507),
         gate_fn=stub_gate()),
    # 6 fast compose -> T-C (topic skipped, content immediate, gate d)
    dict(name="6 fast compose (gate d)", ttft=0.2,
         route_fn=stub_route("international_law_disputes", 0.62, "icc_and_duterte", 0.59),
         gate_fn=stub_gate()),
    # 7 long transient -> T-P-[silence]-C (silence_gap_ms logged). Accelerated: theme
    #   2.0s + topic 1.3s = 3.3s fillers; content at 4.5s -> ~1.2s silence. topic still
    #   fits (synth 1.0s < theme 2.0s), so it fires before the silence.
    dict(name="7 long transient", ttft=4.5, theme_dur=2.0, topic_synth_delay=1.0,
         route_fn=stub_route("international_law_disputes", 0.62, "icc_and_duterte", 0.59),
         gate_fn=stub_gate()),
    # 8 (bonus) late route (>300ms) -> N-C
    dict(name="8 late route (>300ms)", ttft=1.0, route_delay=0.45,
         route_fn=stub_route("constitutional_doctrine", 0.62, "due_process", 0.59),
         gate_fn=stub_gate()),
    # 9 SEV-a-i CONTENT SYNTH EXCEPTION (sentence 1 throws, sentence 2 succeeds) ->
    #   sentence-1 index backfilled with silence, sentence 2 STILL PLAYS -> T-P-C, no hole.
    dict(name="9 content-synth exception", ttft=2.0, content_mode="throw_once",
         route_fn=stub_route("international_law_disputes", 0.62, "icc_and_duterte", 0.59),
         gate_fn=stub_gate()),
    # 10 SEV watchdog: content synth HANGS (2.0s) with WATCHDOG_S=0.8 -> the reserved
    #    index is backfilled with silence at 0.8s (client unstalls); the late real result
    #    is dropped (idempotent fill) -> no hole, no duplicate, backfills>=1.
    dict(name="10 watchdog backfill (hang)", ttft=2.0, content_delay=3.0, topic_synth_delay=1.0,
         watchdog_s=0.8,
         route_fn=stub_route("international_law_disputes", 0.62, "icc_and_duterte", 0.59),
         gate_fn=stub_gate()),
]
CASES[8]["n_sentences"] = 2   # case 9: 2 content sentences so #2 plays after #1 fails

print("=== FILLER v5 harness — chains verbatim ($0 stubbed) ===")
results = []
for c in CASES:
    r = run_case(**c)
    results.append(r)
    extra = [f"queue={r['queue']}", f"no_hole={r['no_hole']}"]
    if r["backfills"]: extra.append(f"backfills={r['backfills']}")
    if r["synth_errors"]: extra.append(f"synth_errors={r['synth_errors']}")
    if r["topic_skipped"]: extra.append(f"topic_skipped={r['topic_skipped']}")
    if r["silence_gap_ms"]: extra.append(f"silence_gap_ms={r['silence_gap_ms']}")
    if r["error"]: extra.append(f"ERROR={r['error']}")
    print(f"  {r['case']:28s} -> {r['chain_annot']:18s} conf={r['route_confidence']} "
          f"reason={r['reason']}  {' '.join(extra)}")

# expected-chain assertions (+ the no-hole invariant on EVERY case)
EXPECT = {"1 confident+separated/slow": "T-P-C", "2 confident+near-tie": "T-C",
          "3 low-confidence": "N-C", "4 META route": "N-C", "5 X35 stray (weather)": "N-C",
          "6 fast compose (gate d)": "T-C", "7 long transient": "T-P-C",
          "8 late route (>300ms)": "N-C", "9 content-synth exception": "T-P-C",
          "10 watchdog backfill (hang)": "T-P"}
print("\n=== assertions (chain + no-hole invariant) ===")
ok = True
for r in results:
    exp = EXPECT[r["case"]]
    good = r["chain"] == exp and not r["error"] and r["no_hole"]
    if r["case"] == "7 long transient":
        good = good and (r["silence_gap_ms"] or 0) > 0
    if r["case"] == "9 content-synth exception":
        good = good and r["synth_errors"] >= 1          # sentence 1 failed, sentence 2 played
    if r["case"] == "10 watchdog backfill (hang)":
        good = good and r["backfills"] >= 1              # watchdog filled the hole
    ok = ok and good
    tag = ""
    if r["case"] == "7 long transient": tag = "  (+silence_gap>0)"
    if r["case"] == "9 content-synth exception": tag = "  (+synth_errors>=1, #2 plays)"
    if r["case"] == "10 watchdog backfill (hang)": tag = f"  (+backfills={r['backfills']})"
    print(f"  {'PASS' if good else 'FAIL'}  {r['case']:28s} chain={r['chain']} expect={exp} "
          f"no_hole={r['no_hole']}{tag}")

# clip durations + grammar drops (Part F.13)
man = json.loads((ROOT / "eval/results/filler_v5_clip_durations.json").read_text(encoding="utf-8"))
print(f"\n=== 53 clip durations (cap {man['hard_cap_s']}s) — min {man['duration_stats']['min']}s "
      f"max {man['duration_stats']['max']}s ===  over-cap: {len(man['over_cap'])}")
import importlib; import filler_route as fr; importlib.reload(fr)
dn = json.loads((ROOT / "eval/results/topic_display_names.json").read_text(encoding="utf-8"))
speak = [r for r in dn["topics"] if r["speakable"] == "YES"]
drops = [(r["spoken_name"], i + 1, fr.grammar_ok(i, r["spoken_name"])[1])
         for r in speak for i in range(10) if not fr.grammar_ok(i, r["spoken_name"])[0]]
print(f"=== grammar-check: {len(drops)} dropped template x name pairings of {len(speak)*10} ===")

# ---- optional REAL-API smoke of the T-P-C path (<=2 tts-1 calls; run with --smoke) ----
smoke = None
if "--smoke" in sys.argv:
    print("\n=== REAL-API smoke: T-P-C with real tts-1 (1 topic + 1 content = 2 calls) ===")
    import os
    from dotenv import load_dotenv
    load_dotenv(ROOT / "app" / ".env", override=False)
    from openai import OpenAI
    real = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    voice_job.WATCHDOG_S = 8.0
    voice_job._DURMAP = None                          # force real durations from manifest
    voice_job.synth_topic = _ORIG_SYNTH_TOPIC         # un-monkeypatch -> real tts-1 topic synth
    real_decks = {t: voice_job.Deck(voice_job.load_theme_pool("onyx").get(t, []))
                  for t in voice_job.filler_route.THEMES}
    real_decks["NEUTRAL"] = voice_job.Deck([])
    # Pin the topic template to t01 (cached by the earlier synth_topic run -> cache HIT, $0)
    # and use a clearly-slow compose (8s) so content lands well AFTER the topic clip -> the
    # topic is never gate-d-skipped by a timing race. 1 real content tts-1 call.
    seq_state = {"turn": 0, "topic_template_decks": {"international_law_disputes": voice_job.Deck([0])}}
    job = voice_job.start_job("What is international law?", "TEST", 0.5, real, set(), None,
                              "onyx", 0, real_decks, seq_state,
                              _route_fn=stub_route("international_law_disputes", 0.62,
                                                   "icc_and_duterte", 0.59),
                              _gate_fn=stub_gate(),
                              _retrieve_fn=stub_retrieve(),
                              _compose_fn=stub_compose(8.0, ("International law governs relations between states.",)))
    while not job["done"]:
        time.sleep(0.05)
    chain = "-".join(job["chain"])
    real_bytes = all(len(c["b64"]) > 100 for c in job["chunks"])
    smoke = {"chain": chain, "no_hole": _no_hole(job), "theme_used": job["theme_used"],
             "topic_used": job["topic_used"], "topic_clip_id": job["topic_clip_id"],
             "cache_hit": job["cache_hit"], "queue": f"{job['queue_reserved']}={job['queue_submitted']}+{job['queue_released']}",
             "n_chunks": len(job["chunks"]), "real_audio_bytes": real_bytes, "error": job["error"]}
    print(f"  chain={chain}  no_hole={smoke['no_hole']}  theme={smoke['theme_used']}  "
          f"topic={smoke['topic_used']} ({smoke['topic_clip_id']})  cache_hit={smoke['cache_hit']}  "
          f"chunks={smoke['n_chunks']}  real_audio={real_bytes}  queue={smoke['queue']}")
    print(f"  [diag] reason={(job['filler_decision'] or {}).get('reason')} "
          f"topic_gated={(job['filler_decision'] or {}).get('topic_gated')} "
          f"topic_skipped={job['topic_skipped']} synth_errors={job['synth_errors']} "
          f"backfills={job['watchdog_backfills']} error={job['error']}")
    smoke_ok = chain == "T-P-C" and smoke["no_hole"] and real_bytes and not job["error"]
    print(f"  SMOKE {'PASS' if smoke_ok else 'FAIL'}")
    ok = ok and smoke_ok

out = {"cases": results, "all_pass": ok, "clip_stats": man["duration_stats"],
       "over_cap": man["over_cap"], "grammar_drops": len(drops), "smoke": smoke}
(ROOT / "eval/results/filler_v5_harness.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
print(f"\nALL PASS: {ok}   wrote eval/results/filler_v5_harness.json")
sys.exit(0 if ok else 1)
