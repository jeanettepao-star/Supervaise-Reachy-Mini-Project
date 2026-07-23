# Filler-v5 Live-Path Diagnosis — Phase 1 (READ-MOSTLY)

**Issued** 2026-07-24 · **Branch** `develop` · **Mode** diagnosis-only (no fixes)

## Header

| Field | Value |
|---|---|
| HEAD sha | `64c0cb7e303b06f67de1b7bbbb95b3f768d7765d` |
| Working tree at start | **NOT clean** — pre-existing operator/doc edits (`.env.example`, `CHANGELOG.md`, `End Point.txt`, `README.md`, `SETUP.md`, `config.py`, `corpus_snapshot.json`, `app/*`, docs). None touched by this session; commit uses scoped `git add` per the operator-files rule. |
| Transport self-check | **N/A — no paid calls made.** The instrumented re-run used the **real local** route/retrieve (embed + BM25, $0) and **stubbed** compose/TTS, so no Anthropic/OpenAI network timing was measured and no transport validity gate applies. |
| Total spend | **$0.00** (≤ $0.50 cap). See "Why $0" below. |
| Turns captured | **6** in `eval/results/filler_v5_trace_2026-07-24.jsonl` (all mandatory fields populated or reason-coded) + 5 isolated route-latency probes + a 6-question margin probe. |
| ENVELOPE guard | 4/4 required cases PASS (deterministic across 2 runs); 1 edge finding (truncated sentinel). |

**Why $0 (and the live-mic limitation).** This session ran head­less. I cannot operate the
live microphone, cannot click "Enable audio" to unlock the browser AudioContext the gapless
player needs, and cannot perform the R-28-style human-stopwatch audible cross-check. The
decisive H-A evidence (route race + topic gate) is **local and free** to measure; the existing
`voice_demo_log.csv` already carries real compose/TTS timings for H-C. The paid run's only unique
value — the audible cross-check — was impossible for me regardless of spend, so I reproduced the
**same post-confirm input path** (`voice_job.start_job(...)`, text-injected at the transcript-confirm
boundary; STT is upstream of that boundary and does not affect the route/filler race) with real
route/retrieve and stubbed compose/TTS. All timing that bears on the three hypotheses is real.

---

## Task 1 — $0 static wiring trace (all claims cited)

### T1.1 — Fire-point wiring
On the **live path** (`streamlit_voice_demo.py`), transcript-confirm calls
`voice_job.start_job(...)`:
- DEMO mode (auto-submit) — [streamlit_voice_demo.py:320](streamlit_voice_demo.py:320).
- TEST mode (after the "Ask" confirm button) — [streamlit_voice_demo.py:333](streamlit_voice_demo.py:333).

Filler-1 fires **inside** `start_job`: the confirm anchor is `job["t_confirm"]` at
[app/voice_job.py:331](app/voice_job.py:331); the THEME/NEUTRAL clip is placed by the
`fillers()` thread at [app/voice_job.py:437-478](app/voice_job.py:437) (clip enqueued via
`_push` → `fill`, first-chunk anchor at [app/voice_job.py:404-405](app/voice_job.py:404)).

The demo **does not** use `service.answer()`. `service.answer()`
([app/service.py:489](app/service.py:489)) has **no filler logic at all** — it calls
`compose_with_expand`/`compose_streamed` directly. The demo reaches the composer through
`voice_job` (`compose_fn = service.compose_streamed`, [app/voice_job.py:325](app/voice_job.py:325)
and the call at [app/voice_job.py:634](app/voice_job.py:634)), bypassing `service.answer()`.
So the filler fire-point exists **only** on the `voice_job` orchestration; `service.answer()`
is the "other orchestration" and is filler-free — confirming the audit's finding that the demo
bypasses it.

### T1.2 — Gate inputs
The filler gate is `filler_route.decide(ri, job["gate"], late_route=...)`, evaluated in the
`fillers()` thread at [app/voice_job.py:444-447](app/voice_job.py:444). Exact live inputs:
- **`ri`** = `job.get("route")` ([app/voice_job.py:439](app/voice_job.py:439)) = the result of
  `retrieval.route(q)` (set at [app/voice_job.py:623-629](app/voice_job.py:623)). Fields:
  `top_topic`, `top_cosine`, `cos` (full 34-vector), `in_scope`, `routed_topics`
  ([app/retrieval.py:96-101](app/retrieval.py:96)).
- **`job["gate"]`** = `retrieval.input_gate(q)` ([app/voice_job.py:411](app/voice_job.py:411)
  → [app/retrieval.py:72-82](app/retrieval.py:72)) = `{"scope": "in_corpus" | "identity_probe"
  | "empty"}`.
- **`late_route`** = `not got`, where `got = route_evt.wait(timeout=FILLER_ROUTE_WAIT_MS/1000)`
  ([app/voice_job.py:438](app/voice_job.py:438)); `FILLER_ROUTE_WAIT_MS=300`
  ([config.py:625](config.py:625)).

Inside `decide` ([app/filler_route.py:143](app/filler_route.py:143)): `conf =
float(route["top_cosine"])`; the **confidence-margin** gate uses `margin, ru =
clean_margin(route)` ([app/filler_route.py:159](app/filler_route.py:159)); the **topic** gate is
`topic_gated = margin >= TOPIC_MARGIN_THRESHOLD and speakable and spoken`
([app/filler_route.py:183](app/filler_route.py:183)). The **content-readiness** gate (gate d) is
enforced at runtime in `_maybe_topic` via `first_content.is_set()`
([app/voice_job.py:503,509](app/voice_job.py:503)).

### T1.3 — Filler-2 cache key
`_topic_cache_path(voice, topic_id, template_idx)` — [app/voice_job.py:274-276](app/voice_job.py:274):
```
config.FILLER_CLIP_DIR / <voice> / "topics" / f"{safe}__t{template_idx+1:02d}.mp3"
  where safe = re.sub(r"[^A-Za-z0-9]+","_", topic_id).strip("_")
```
Key components, in order: **(1) voice · (2) topic_id (sanitized) · (3) template_idx (1-based,
2-digit)**.

**The cache key does NOT use topic display names.** The Sheena red-lines
(`with_due_respect_persona` → "my book, With Due Respect"; `honors_received` → "my recognitions")
and any removed material ("Abangan") live in the **spoken text** that `render_topic` synthesizes
([app/filler_route.py:231-232](app/filler_route.py:231)), not in the cache path. A rename therefore
**cannot cause a cache miss**. Two nuances:
- The set of **allowed template indices** is grammar-filtered by the *spoken* name
  (`allowed_templates(spoken)`, [app/filler_route.py:226](app/filler_route.py:226)); a
  singular→plural or comma-adding rename changes which `template_idx` values are dealt, hence which
  cache filenames appear — but this only matters if the topic path executes (it never does; see H-A).
- A display-name red-line **after** a clip was cached would serve **stale audio** (old name) — a
  cache-*staleness* risk, not a miss. Also moot while filler-2 never fires.

**Verdict:** the "cache-key rename" sub-cause of H-A is **REFUTED** — the key is topic_id-based and
the topic path is never reached.

### T1.4 — Enumerability verdict — **ENUMERABLE**
Neither filler interpolates anything query-derived:
- **Filler-2 (topic):** `render_topic(template_idx, spoken)` = `TOPIC_TEMPLATES[template_idx].replace("{TOPIC}", spoken)`
  ([app/filler_route.py:231-232](app/filler_route.py:231)). `spoken` = `display_names()[topic_id]["spoken"]`
  ([app/filler_route.py:180,109-116](app/filler_route.py:180)) — a **locked** value from
  `topic_display_names.json`, not visitor words / STT fragments / retrieval snippets.
  **Template variable list: `{TOPIC}` only.** Key space = **voice × topic_id × template_idx**
  (grammar-filtered, ≤10 per topic).
- **Filler-1 (theme):** `render_theme(theme, variant_idx)` = `THEME_VARIANTS[variant_idx].replace("{T}", THEME_SPOKEN[theme])`
  ([app/filler_route.py:235-236](app/filler_route.py:235)). **Template variable list: `{T}` only**,
  bound to the 5 locked `THEME_SPOKEN` values. Key space = voice × theme(A–E/NEUTRAL) × variant_idx(≤10).

**Robot pre-bake: GO.** Both fillers are fully enumerable and already pre-synthesized as clips.

### T1.5 — What the smoke test actually measured
The "<1s TTFA" is `voice_demo_log.csv:ttfa_felt_s` = `job["first_chunk_ready_s"]`
([streamlit_voice_demo.py:237](streamlit_voice_demo.py:237)), set in `fill()` at
[app/voice_job.py:404-405](app/voice_job.py:404):
```
job["first_chunk_ready_s"] = round(time.perf_counter() - job["t_confirm"], 2)
```
This is the interval **transcript-confirm → first chunk APPENDED to `job["chunks"]`** — i.e. the
moment the first clip is *handed to the gapless component's data channel* (**enqueued**), **not**
the first audible sample. The UI caption even labels it "confirm→first audio **ready**"
([streamlit_voice_demo.py:362](streamlit_voice_demo.py:362)). True audibility additionally requires
the browser AudioContext (one "Enable audio" click) plus Web Audio scheduling, none of which this
timestamp captures. → Maps to the schema's `t_first_content_chunk_enqueued` / `t_filler1_play_start`
(enqueue), with `play_start_observable=false`. **This directly implicates H-B.**

(The other file, `streamlit_voice_smoke.py` → `voice_smoke_log.csv`, is the **June no-filler** design
— it speaks the full answer at the end and has no filler machinery at all; its one row
["What do you mean by itchigaray?"] is not the filler-v5 path and is not the source of the observation.)

---

## Hypothesis verdicts

### H-A — Filler-2 dead (filler-1 possibly alive) — **CONFIRMED** (two independent sub-causes)

Filler-2 (the TOPIC sentence) is dead on the live path, for **two independent reasons**, either of
which alone suffices. The "two-part" filler is never two parts.

**Sub-cause A1 — Route loses the 300 ms race in the live app (→ NEUTRAL).**
Every row of `voice_demo_log.csv` shows `route_confidence=0.0`, `fallback_used=True`,
`theme_used`/`topic_used` empty, `chain=N-C | N | C` — including rows **after** the warm-inference
fix landed (fix = `retrieval.route("warm")` in `warm_pipeline`, commit `0d131fe`/`033674c`,
2026-07-20; affected rows dated **2026-07-21** and **2026-07-24**). `route_confidence` =
`dec["theme_conf"]` = `round(float(route["top_cosine"]),4)`; a resolved route never yields cosine
**exactly** 0.0 (a real embed cosine is ~0.3–0.62). `0.0` therefore uniquely identifies the
`ri is None` literal branch `decide({"top_topic": None, "top_cosine": 0.0}, ..., late_route=True)`
([app/voice_job.py:444-445](app/voice_job.py:444)). So in the live app the route is **not populated
in `job["route"]` before `FILLER_ROUTE_WAIT_MS` (300 ms) expires**, every turn → `late_route` →
NEUTRAL. This collapses the filler to a single generic "Permit me a moment" clip (or none, when the
per-voice NEUTRAL pool is empty → `filler_missing_pool`, e.g. the 2026-07-24 `chain=C` row).

**But this did NOT reproduce headlessly.** In the instrumented re-run (same HEAD, same warm, same
`FILLER_ROUTE_WAIT_MS=300`), the warm route resolved in **41–82 ms and won the race on 6/6 turns**
(`got=True`, `route_confidence` 0.47–0.62); isolated warm route latency was **39–65 ms**
(trace `route_latency_ms`; harness log). So on the current code, warmed, the route is fast and
filler-1 (theme) fires. The live-app collapse is therefore tied to the **live Streamlit execution
context**, not to the route code itself. Leading hypothesis for Phase-2: GIL/CPU contention from the
`st.rerun()` loop that fires immediately after `start_job` ([streamlit_voice_demo.py:323,352-353](streamlit_voice_demo.py:323))
delays the route's Python-side work (tokenize/encode wrapper) past 300 ms even though the isolated
route is <100 ms; a live-context instrumentation run is required to confirm. **This is the one axis
that could not be reproduced headlessly — see limitations.**

**Sub-cause A2 — Topic margin gate never passes (→ theme_only), even when the route wins.** *(reproducible)*
When the route wins and the theme fires, filler-2 is still gated **off** on every in-scope turn:
`filler2_attempted=false`, `filler2_absent_reason="topic_not_gated:theme_only"` (trace turns 1–4).
Mechanism (margin probe, warm): `clean_margin` = top-cosine minus the best **non-fallback** runner-up
([app/filler_route.py:119-139](app/filler_route.py:119)) is **always below `TOPIC_MARGIN_THRESHOLD=0.01`**
([config.py:622](config.py:622), gate at [app/filler_route.py:183](app/filler_route.py:183)):

| Question | top_topic | cos | clean_margin | runner-up | topic_gated |
|---|---|---|---:|---|:--:|
| foundation for liberty & prosperity | twin_beacons_doctrine | 0.5974 | **0.0011** | foundation_for_liberty_and_prosperity | ✗ |
| your book, With Due Respect | mentors_and_legal_lineage | 0.5411 | **0.0079** | with_due_respect_persona | ✗ |
| rule of law | global_geopolitics | 0.6239 | **0.0036** | constitutional_doctrine | ✗ |
| recognitions & honors | early_life_sampaloc | 0.5659 | **0.0039** | bar_exam_and_legal_education | ✗ |

The query→centroid cosines are so densely clustered that top-1 and the runner-up are 0.001–0.008
apart — **never** the 0.01 the gate demands. All top topics are `speakable=YES` with a valid `spoken`
name, so speakable/spoken are **not** the blocker; the **margin** is. Note the *intended* topic is
frequently the runner-up (foundation…, with_due_respect… are runners-up, not top-1) — a routing-quality
issue (Found, not fixed). **Consequence: fixing the route race alone (A1) restores filler-1 but NOT
filler-2; the margin gate (A2) must also be recalibrated for the two-part filler to ever fire.**

### H-B — Measurement artifact (enqueue vs audible) — **CONFIRMED** (with a stated gap)
The logged "TTFA" is **enqueue**, not audible (T1.5; `first_chunk_ready_s` set the instant the first
chunk is appended to `job["chunks"]`, [app/voice_job.py:404-405](app/voice_job.py:404)). The trace
records `play_start_observable=false` on all 6 turns: there is **no server-side audible-play event**
— the gapless component reports per-chunk `gap_ms` after the fact
([streamlit_voice_demo.py:343](streamlit_voice_demo.py:343)) but the enqueue→audible delta (component
round-trip + AudioContext scheduling) is never captured. So "<1s" is first-byte-enqueued, and the
Felt-TTFA GREEN KPI is measured against the wrong event. **Gap:** I could not run the human-stopwatch
audible cross-check (no operator, no audio surface in a headless agent) — so I **cannot quantify** the
enqueue→audible delta here. That measurement is the one piece of H-B that still needs a human-in-the-loop
pass (see stopwatch table below).

### H-C — Content short-circuit — **REFUTED**
Content did **not** arrive fast; it is never the sub-1s source.
- Existing `voice_demo_log.csv` `chunk_timings` show **real** content synth of **1.6–8.0 s per
  sentence** (real Anthropic compose + real OpenAI tts-1). The <1s chunk is the **filler** clip
  (index `base`), not content — every `N-C` row places the NEUTRAL clip first (rel-index 0) and
  content seconds later.
- The most recent row (2026-07-24 "are you a robot?") is `chain=C` with `ttfa_felt_s=9.79s` — content
  first, and **slow**, not a short-circuit.
- TTS engine is the expected OpenAI `tts-1` (call site `oai.audio.speech.create(model="tts-1", ...)`,
  [app/voice_job.py:428,443](app/voice_job.py:428)); trace `tts_engine_used=openai`,
  `tts_model_used=tts-1` — **no degraded/alternate TTS path**. The gate did not "correctly suppress
  filler on content-readiness"; rather the filler (NEUTRAL) fired first and content was slow.

---

## Decision table

| Finding | Verdict | Evidence | Phase-2 action this selects |
|---|---|---|---|
| **H-A1** filler-2 dead — route loses 300ms race → NEUTRAL | **CONFIRMED (live) / not reproduced headlessly** | `voice_demo_log.csv` `route_confidence=0.0`+`N-C` on **all** rows incl. post-warm-fix 07-21/07-24; `0.0` uniquely = the `ri is None` branch [voice_job.py:444](app/voice_job.py:444). Harness: warm route 41–82 ms, `got=True` 6/6 [trace]. | **Instrument the LIVE Streamlit path** (add this session's `route_latency_ms`/`_route_got` telemetry to the actual `streamlit run` context) to measure the real in-app route latency. Candidate fixes if confirmed slow: compute the route **before** spawning the fillers thread ([voice_job.py:437 vs 623](app/voice_job.py:437)) / raise `FILLER_ROUTE_WAIT_MS` / verify the warm persists in-session. |
| **H-A2** filler-2 dead — topic margin gate never passes | **CONFIRMED (reproducible)** | Margin probe: `clean_margin` ∈ {0.0011, 0.0079, 0.0036, 0.0039} < `TOPIC_MARGIN_THRESHOLD=0.01` on every in-scope turn; `speakable=YES`, `spoken` valid → margin is the blocker. Trace `filler2_absent_reason="topic_not_gated:theme_only"` turns 1–4. | **Recalibrate `TOPIC_MARGIN_THRESHOLD`** ([config.py:622](config.py:622)) to the *observed* query→centroid margin band (all < 0.01), **or redefine the topic gate** (`clean_margin` in [filler_route.py:119](app/filler_route.py:119) / gate at [filler_route.py:183](app/filler_route.py:183)) — e.g. top-vs-gmean-fallback gap, softmax-relevance gap, or top-p mass. Re-derive `eval/results/filler_v5_thresholds.md` from live query margins, not frozen-40 doc bands. |
| **H-B** measurement artifact (enqueue vs audible) | **CONFIRMED** | `ttfa_felt_s=first_chunk_ready_s` = enqueue [voice_job.py:404](app/voice_job.py:404); `play_start_observable=false` 6/6; no audible-play event. | **KPI definition correction + harness fix, no pipeline change:** emit a play-start event from `components/gapless_audio` (AudioContext `start` callback) and redefine Felt-TTFA as confirm→first-audible. |
| **H-C** content short-circuit | **REFUTED** | `chunk_timings` 1.6–8.0 s/sentence; <1s chunk is the filler; 07-24 `chain=C` `ttfa=9.79s`; `tts_engine_used=openai/tts-1`. | None on this axis (no gate/path change). |
| **ENVELOPE guard** | **PASS** (4/4 required) | `tests/test_envelope_never_spoken.py` — cases 1–4 pass, deterministic across 2 runs. | — |
| ENVELOPE guard — truncated-sentinel edge | **FINDING (leak)** | Case-5 probe: a stream truncated mid-sentinel leaks the partial tail (`"---ENV"`) to TTS via `flush()` — `feed()` suppresses only the **complete** sentinel [voice_stream.py:49](app/voice_stream.py:49); `flush()` emits the held partial [voice_stream.py:65-68](app/voice_stream.py:65). Same gap exists upstream in `_stream_native` [service.py:382-386](app/service.py:382). | **Phase-2 hardening (rare):** suppress a trailing *partial*-sentinel prefix in `flush()` (and/or in `_stream_native`'s final flush). Requires truncation inside the 14-char sentinel to trigger. |
| **Filler-2 enumerability** | **ENUMERABLE** | `render_topic` uses only `{TOPIC}`←locked `spoken`; `render_theme` only `{T}`←locked `THEME_SPOKEN` [filler_route.py:231-236](app/filler_route.py:231). No query-derived text. | **Robot pre-bake: GO.** Key space = voice × topic_id × template_idx (filler-2) and voice × theme × variant (filler-1). |

---

## Found, not fixed

1. **Routing top-1 frequently mislands** (retrieval quality, not filler): "foundation for liberty and
   prosperity" → `twin_beacons_doctrine` (correct topic is the runner-up); "rule of law" →
   `global_geopolitics`; "recognitions & honors" → `early_life_sampaloc`. The intended topic is often
   the runner-up with a sub-0.01 margin. Compounds H-A2. ([app/retrieval.py:85-101](app/retrieval.py:85))
2. **Compose-retry duplicate-emit** (known/deferred) — not exercised this session; `compose_streamed`
   internal retry count is not surfaced to the caller ([app/service.py:402-417](app/service.py:402)), so
   the trace's `retry_count` is reason-coded null.
3. **Hardcoded literals**: `whisper-1` ([streamlit_voice_demo.py:165](streamlit_voice_demo.py:165)),
   `tts-1`/voice/speed ([app/voice_job.py:428,443,289](app/voice_job.py:428)) — not config-driven.
4. **Dead `service._compose`** ([app/service.py:297-299](app/service.py:297)) — unused by the live path.
5. **Two-orchestration divergence**: `service.answer()` (filler-free) vs the `voice_job` demo path
   (filler-bearing). The demo bypasses `service.answer()` entirely (T1.1).
6. **ENVELOPE truncated-sentinel leak** (decision table) — `flush()` + `_stream_native` final flush.
7. **`filler_missing_pool` when a per-voice NEUTRAL pool is empty** → no filler at all (the 2026-07-24
   `chain=C` row); the demo shows a text spinner instead ([app/voice_job.py:473-475](app/voice_job.py:473)).
8. **Stale docs/caption**: the "boot warm-inference makes Q1 fast" caption
   ([streamlit_voice_demo.py:265-267](streamlit_voice_demo.py:265)) is contradicted by the live log,
   where **every** turn (not just Q1) routes late.
9. **`ttfa_felt_s` naming** overstates what it measures (enqueue, not audible) — H-B.

---

## Stopwatch cross-check (H-B: human-perceived audible vs logged enqueue)

| Turn | Logged (enqueue) `first_chunk_ready_s` | Human-perceived first audio | Δ (audible − enqueue) |
|---|---|---|---|
| — | — | **NOT CAPTURED** | **NOT CAPTURED** |

**Could not be performed.** A headless agent has no microphone, no speaker, and no way to unlock the
browser AudioContext (the "Enable audio" click) that the gapless player requires; there was no human
operator to stopwatch audible onset. This is the single measurement in the brief that is
**infrastructurally impossible** for me. **Phase-2 must run this with a human at the live demo** (the
R-28 audible-verification pattern): for 2–3 turns, record operator-perceived first audio vs the logged
`first_chunk_ready_s`, to quantify the enqueue→audible delta that H-B predicts is non-trivial.

---

## What Phase-2 needs (if any hypothesis were to be called INCONCLUSIVE)

Only **H-A1** is context-dependent (confirmed in the live log, not reproduced headlessly). To close it
decisively, Phase-2 needs a **route-latency measurement taken inside the running Streamlit app** — the
telemetry added this session (`route_latency_ms`, `_route_got`, `warm_pipeline_ran` in
`filler_v5_trace_2026-07-24.jsonl`) already emits from `start_job`, so it will populate automatically the
next time `streamlit run streamlit_voice_demo.py` handles a real question; compare that in-app
`route_latency_ms` against the 300 ms window. H-A2, H-B, H-C, ENVELOPE, and enumerability are all fully
resolved by the evidence above.

---

## Evidence artifacts (this session)

- `eval/results/filler_v5_trace_2026-07-24.jsonl` — 6 instrumented turns (real route/retrieve, stubbed
  compose/TTS), all mandated fields.
- `tests/test_envelope_never_spoken.py` — 4 required cases (PASS ×2) + case-5 edge probe (leak finding).
- Telemetry: additive, behavior-preserving emission in `app/voice_job.py` (guarded `_emit_trace`;
  the 10-case `scripts/verify_filler_v5.py` still passes unchanged — behavior preserved).
