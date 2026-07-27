# Full-Repo Audit — CJP RAG Persona Kiosk (`develop` @ arch-baseline-v4.2)

**Date:** 2026-07-22 · **Scope:** read-only, $0 (no API calls, no app run, no fixes, no commits).
**Method:** static analysis + committed-file reads + read-only git/grep + $0 import-shape checks.
**Baseline assumed (not re-litigated):** retrieval = bge-base dense + BM25, RRF-fused, 34-topic
centroid soft-prior, top-p nucleus cutoff; compose = streamed Sonnet w/ cached Voice-Card;
voice = STT → pipeline → two-part theme+topic filler → gapless TTS. Tags v4.2 (`9ef1f5c`) and
v4.1 (reserved) treated as immutable. Demo = first week of August, Reachy Mini, Path B (brain
off-robot). Locked decisions D1–D8 and the B11 acceptance are honored, not re-opened.

Operator state, gitignored-by-policy assets, the `pyarrow==21.0.0` pin, and `.venv` were treated
as off-limits per the task and are **not** flagged as defects anywhere below.

Severity: **SEV** = breaks a new dev / demo path or a spoken-output correctness guarantee ·
**HIGH** = materially wrong architecture claim or a real latent bug · **MED** = drift/coupling that
will bite soon (esp. at the robot seam) · **LOW** = cosmetic / cleanup.

---

## Executive summary — top 10 by severity × effort

Ranked so the highest-severity, lowest-effort items float up (all ten are pre-demo-safe unless noted).

| # | Sev | Effort | Finding | Where |
|---|---|---|---|---|
| 1 | SEV | XS | **Documented quick-starts fail on first run.** README / app-README push `cj_chat.py --text …` and `streamlit run dashboard.py`; both now `raise SystemExit(2)` unless `CJ_ALLOW_LEGACY=1`. A new dev's first command errors out. | `README.md:54-67`, `app/cj_chat.py:44-49`, `app/dashboard.py:39-44` |
| 2 | SEV | S | **`architecture.md` documents the *opposite* architecture** ("No vector store at runtime … embeddings only for offline audit", Haiku router/gate/fidelity) and claims to be the single coherent picture. A new dev gets exactly the wrong mental model. | `architecture.md:1-100` |
| 3 | SEV | XS | **`app/.env.example` omits `OPENAI_API_KEY`** (still the kiosk template: `WHISPER_MODEL`/`PIPER_*`). The develop demo hard-requires it (STT+TTS default to OpenAI) and stops with an error the template never hints at. | `app/.env.example:1-6`, `streamlit_voice_demo.py:273-282` |
| 4 | HIGH | XS | **`SETUP.md` actively invites the failure the pyarrow pin prevents** ("deps are `>=` floors, re-pin only if a release breaks it") and tells the dev to install `all-MiniLM-L6-v2` / 384-dim (the bakeoff alt), not bge-base/768. | `SETUP.md:27-29,50-63` |
| 5 | HIGH | M | **Two divergent orchestration paths.** RI-301 describes the seam as `answer()→retrieval.run→compose_streamed`, but the live demo never calls `answer()` — `voice_job.start_job()` re-implements route→retrieve→compose inline. The "contract" and the shipping path have drifted; the robot seam needs one canonical orchestrator. | `service.py:489`, `voice_job.py:457-463` |
| 6 | HIGH | S | **No test guards the "envelope must never be spoken" guarantee** or the filler gate table — both are pure, zero-mock, buildable today. Highest-value $0 tests missing. | `service.py:327,356`, `filler_route.py:143` |
| 7 | MED | S | **Compose-retry re-emits prose.** On a mid-stream failure + retry, `_stream_native` restarts `on_text` from offset 0, re-feeding the chunker → duplicated spoken audio and duplicated `job["acc"]`. Latent (needs mid-stream drop), but real. | `service.py:392-414` |
| 8 | MED | S | **Config drift on the live path.** `whisper-1` / `tts-1` / TTS speed / voice are hardcoded in the demo path, bypassing the `config.OPENAI_*` knobs the older `voice_io.py` honored. Matters because `voice_job.py` is the module the robot will reuse. | `streamlit_voice_demo.py:165`, `voice_job.py:173,400,416` |
| 9 | MED | XS | **Stale architecture claims embedded in code.** `config.py` header says NEW-ARCH is "NOT yet wired … inert"; `embeddings.py:6` and `requirements.txt` say bge-**large**/1024. All false on develop. | `config.py:17-25`, `embeddings.py:6`, `app/requirements.txt:37-43` |
| 10 | MED | S | **No clean-clone setup guide + stale CHANGELOG.** Index rebuild (`corpus_dense.npy`/`pilot_sparse.pkl` are gitignored) and filler-clip regen are undocumented; CHANGELOG tip is 2026-06-30 (pre v4/v4.2/filler-v5). | (repo-wide) `CHANGELOG.md:1-3` |

**One-line health read:** the *engine* is in good shape; the *documentation and onboarding surface*
is the liability. See the closing assessment.

---

## A. Correctness & error-handling

**A1. [MED] Compose-retry re-emits already-streamed prose → duplicate audio.**
`compose_streamed` retries up to `COMPOSER_MAX_RETRIES` (=2) on exception. `_stream_native` starts
each attempt with `emitted = 0` and calls `on_text` for all prose from the top. If attempt 1 fails
*after* emitting some deltas (a mid-stream drop), the retry re-emits the same prose; the consumer
(`voice_job.on_text` appends to `job["acc"]` and feeds `SentenceChunker` → OpenAI TTS) will speak
the duplicated sentences. `streamlit_voice_smoke.py:155-160`'s `on_text` has the same exposure.
→ *`service.py:392-414`, `service.py:356-389`.* On retry, either pass `on_text=None` (accept
loss of streaming on the rare retry), or carry an emitted-high-water-mark across attempts and skip
already-emitted prose. Connection failures usually precede the first token (no dup), which is why
this hasn't surfaced — but a mid-stream blip during the demo would double a sentence.

**A2. [LOW] Dead function `service._compose`.** `service.py:297-299` (`_compose` → `_messages`,
non-streaming, `MAX_TOKENS=300`) has **no callers** (grep across `app/`, `scripts/`, root). The
live path is `compose_streamed` / `compose_with_expand`. → Delete post-demo (it also carries the
only remaining reference to the legacy `MAX_TOKENS=300` knob on a compose path).

**A3. [LOW] Retired-v3 code kept live in `voice_job.py`.** `_role_of` (`voice_job.py:55-63`) and
`load_pool` (`66-77`) are explicitly retired v3; the only remaining reference is a *comment* in
`scripts/gen_onyx_filler_pool.py:17`. → Safe to remove post-demo (or move to a `legacy/` shim) once
that generator is confirmed unused for v5.

**A4. [LOW] Inert dead branch — `WARM_ON_BOOT`.** `streamlit_voice_demo.py:291-294` is
`if config.WARM_ON_BOOT: warm_pipeline() else: warm_pipeline()  # (flag reserved; demo always
warms)` — both branches identical, so the config knob has no effect. → Either honor the flag or drop
the branch and the knob's "reserved" pretense.

**A5. [LOW→MED] Bare `assert` on the retrieval hot path.** `retrieval.py:126`
`assert dense_set == sparse_set` aborts the whole turn (→ `job["error"]`, no answer) if the dense and
sparse universes ever diverge, and is silently *removed* under `python -O`. It is a genuine invariant,
but for a live demo an aborted turn is a poor failure mode. → Convert to an explicit
`raise RuntimeError(...)` (survives `-O`) and/or degrade to the intersection with a logged warning so
one drifted doc can't blank a demo answer.

**A6. Exception-safety sweep — the reserved-index class looked clean elsewhere.** The Q2-SEV
reservation invariant in `voice_job.py` (reserve/fill/watchdog, 236-390) is the model example and is
well-tested. Searching for the *same* "acquired-but-not-released-on-error" pattern elsewhere:
tempfile handling in `service._messages` (curl path, `finally: os.unlink`) and
`streamlit_voice_demo.stt_openai` (`finally: unlink`) both release on error; the topic-synth future in
`_maybe_topic` reserves no index until `_push` (reserve+fill atomic), so a slow/failed topic leaves no
hole; `synth_mp3`/`synth_stream` backfill silence on exception. **No new reserved-index leak found.**
The one soft spot is A5 (assert-abort) and A1 (retry re-emit).

**A7. [MED] Config knobs bypassed by hardcoded literals on the live path** — see B/A overlap and
**C4**. Enumerated under Config drift below.

**Config drift (knobs defined but unused / literals that bypass config):**

- **[MED] Live path hardcodes model IDs, speed, and voice.** `streamlit_voice_demo.py:165`
  `model="whisper-1"` (ignores `config.OPENAI_STT_MODEL`); `voice_job.py:173,400,416`
  `model="tts-1"` ×3 (ignores `config.OPENAI_TTS_MODEL`); content TTS at `voice_job.py:400` sets no
  `speed`, so it runs at 1.0 and ignores `config.OPENAI_TTS_SPEED=0.98`; voice comes from the sidebar
  `VOICES` list (`streamlit_voice_demo.py:73`), not `config.OPENAI_TTS_VOICE`. The **older**
  `voice_io.py:136-150` reads all four knobs — the newer demo path regressed against the project's own
  "no literal that belongs in a sweep" contract. → Route these through config (esp. before the robot
  reuses `voice_job`).
- **[LOW] Genuinely dead knobs (zero external readers):** `EXPAND_ON_DEMAND_FIRE_RATE_GATE`
  (`config.py:310`), `CURATED_SCHEMA_COLUMNS` (`405`, comment says "Validators read this" — none do),
  `EMBEDDING_MODEL_ID`/`EMBEDDING_DIM` back-compat aliases (`330-331`, `478-479`), `DOC_ID_REGEX`
  (`409`, only `DOC_ID_REGEX_PADDED` is used). → Remove or annotate as reserved-for-books
  (`DOC_ID_REGEX`) / delete the aliases.
- **[LOW] Legacy-only knobs** (`FIDELITY_MAX_RETRIES`, `CONTEXT_TOKEN_BUDGET`, `MAX_SOURCE_DOCS`,
  `WHISPER_MODEL_SIZE`) are referenced **only** by `app/cj_chat.py` (the legacy-guarded kiosk). Not
  dead, but dead-for-develop; keep only as long as the legacy entry is supported.

---

## B. Latency (analysis only)

**Request path traced:** mic → **STT** (blocking, ~1.5-3s) → **route** (~40ms warm: GPU embed +
34-centroid cosine) → **retrieve** (127ms p50: RRF fuse + nucleus) → **compose** (TTFT ~1.3s,
streamed) → **TTS** (tts-1 ~3s floor, pipelined per-sentence) → gapless play. The two-part filler
covers compose+TTS; the felt-TTFA is confirm→first-audio.

**B1. [MED] STT is synchronous and un-hideable.** The pipeline can't start until the final transcript
exists (routing needs the text), so STT sits entirely *before* the filler can fire — it is the one
latency the filler cannot mask (matches the known "STT is the felt-TTFA driver"). The `STT_BACKEND`
knob is already exposed and openai/whisper-1 is the current best on this host. → No fix; flag
**streaming/partial STT** (RI-301 open item #8, finals-vs-partials) as the only structural lever left
here, to be revisited at robot time.

**B2. [LOW] The ~3s tts-1 floor has a dark lever.** `STREAM_TTS_ENABLED` (default **False**) gates the
streamed-PCM TTS path (`voice_job.synth_stream`, 24kHz/16-bit) that begins Web-Audio playback as
chunks arrive. It is shipped but *unverified* (needs ~2 paid TTS calls). → Post-demo, paid-verify and
consider promoting; it is the biggest remaining attack on the TTS floor and is also the shape the
robot speaker path wants (RI-102).

**B3. [PASS] No repeated work / no per-request re-init on the hot path.** Every heavy resource is a
lazily-loaded module singleton: the embedder (`embeddings._MODEL`), dense/pilot matrices, centroids,
BM25 index, phrase dict, `chunk_text`, `voice_card`, `doc_json`, `theme_of`. The query is embedded
**once** per turn (`route()` embeds; `retrieve()` reuses `route_info["qv"]`). Streamlit resources
(`warm_pipeline`, `openai_client`, `gapless_component`, `filler_decks`, `filler_stats`) are all under
`@st.cache_resource`, so the ~0.4s poll-rerun loop does **not** reload models or pools. This is a
strength — nothing to fix.

**B4. [LOW] Single-worker pool contention when streaming.** With `STREAM_TTS_ENABLED`, the pool is
`max_workers=1` and the **topic** synth shares it with **content** synth; a slow topic clip could
queue ahead of content. It is bounded by the topic deadline (`_maybe_topic`, `voice_job.py:342-351`)
and gate-d, so it degrades to "topic skipped", not a stall. → Note only; if B2 is promoted, give the
topic synth its own single-use executor.

---

## C. Architecture & modularity

**C1. [HIGH] The service contract and the shipping path have diverged.** `service.answer()`
(`service.py:489`) is the documented v1.0 seam (`answer()→retrieval.run→compose_with_expand`) and is
what RI-301 names — but its **only** callers are `service.main()` (the CLI) and
`scripts/check_expand_on_demand.py`. The live voice demo calls **`voice_job.start_job`**, which
re-implements the orchestration inline (`route_fn`/`retrieve_fn`/`compose_fn`, `voice_job.py:457-463`)
and uses `compose_streamed` directly (not `compose_with_expand`, so the W2.6 expand wrapper never runs
on the demo path). → This is the top modularity risk for the robot: the robot seam should have **one**
canonical orchestrator. Recommend converging — either promote `answer()` to a streaming-capable
orchestrator with an `on_prose`/`on_audio` callback that both the demo and the robot call, or have
`voice_job` delegate to a shared `run_turn()` so the contract *is* the code.

**C2. [MED] Wrapper/core separation is mostly already done — with three residual couplings.** The
core (`retrieval`, `service`, `filler_route`, `voice_job`, `voice_stream`, `embeddings`, `sparse`) is
**Streamlit-free**; only `streamlit_voice_demo.py` and `streamlit_voice_smoke.py` import Streamlit.
That's genuinely good. The couplings that still block a clean headless/robot entrypoint (rated by how
much each blocks it):
  - **(blocks most) `voice_job.start_job` returns a browser-shaped job dict** designed for Streamlit's
    poll-via-rerun (`job["chunks"]`, `job["done"]` read each rerun). A robot host wants push/callback or
    a generator, not a polled dict.
  - **(blocks) TTS is hardcoded to OpenAI inside `voice_job`** (`synth_mp3`/`synth_stream`). Meanwhile
    `voice_stream.py` already defines the clean `TTS` protocol (`synth(text)→(wav,ms,s)`) with
    `SapiTTS`/`PiperTTS` drop-ins — the intended "swap not rewrite" point for Piper/Kokoro — but the
    shipping path bypasses it. The abstraction exists; the live path doesn't use it.
  - **(browser-only) the b64/index/gapless machinery** (`components/gapless_audio/index.html` +
    reservation-index + R-28 silence backfill) is a browser-playback concern; on-robot the SDK owns
    ordering (RI-102), so that whole layer is bypassed rather than ported.

**C3. [MED] `theme_anchor` mapping implemented twice.** `service._theme_of` (`service.py:95-122`,
handles merged ids via `.split("+")[0]`) and `filler_route.theme_of_topic` (`filler_route.py:75-84`,
hardcodes the fused `msme…` id) both build topic_id→theme_anchor from `topic_map.json` with
*different* merge handling. → Consolidate into one helper to prevent silent drift when the taxonomy
heals (OPS-3).

**C4. [LOW] Duplicated status classifier.** The "declined/degraded/answered" decision is inlined in
both `voice_job.py:477-481` (`"speak to"` OR `"outside my"`) and `streamlit_voice_smoke.py:168-171`
(`"outside my"` only) — already slightly out of sync. → Extract `_classify_status(answer, cited,
degraded)` (also unlocks test E5).

**C5. [LOW] Legacy kiosk surfaces coexist.** `app/app.py` (61 KB museum kiosk), `app/cj_chat.py`,
`app/dashboard.py` are guarded by `CJ_ALLOW_LEGACY` but still imported by each other (`app.py` →
`cj_chat`). This is a **branch-scoping** question (they belong to `pre-wake-word-integration`), not
cruft to delete on `develop`. → Decide at merge time; until then, keep the guard and stop documenting
them as entrypoints (see D).

---

## D. Documentation

The two source-of-truth docs are accurate and should be trusted: **`CLAUDE.md`** (two-branch table)
and **`docs/handover_claude_code_2026-07-18.md`** (the develop pipeline). Almost everything else at the
top level describes the pre-W1.8 kiosk.

**D1. [SEV] Broken quick-starts.** `README.md:54-67` and `app/README.md:38,48,62` push `cj_chat.py
--text …` and `streamlit run dashboard.py`; both `raise SystemExit(2)` without `CJ_ALLOW_LEGACY=1`
(`app/cj_chat.py:44-49`, `app/dashboard.py:39-44`). → Replace with `python app/service.py --query
"…"` (headless) and `streamlit run streamlit_voice_demo.py` (voice demo).

**D2. [SEV] `architecture.md` documents the opposite architecture** ("No vector store at runtime",
"embeddings only offline", Haiku gate/router/fidelity) and asserts it "supersedes ad-hoc
descriptions" (`architecture.md:1-100`). → Add a top banner redirecting to the 07-18 handover, or
rewrite for the embeddings pipeline. Most dangerous file after the broken quick-starts.

**D3. [SEV/HIGH] `app/.env.example` omits `OPENAI_API_KEY`** and still lists `WHISPER_MODEL`/`PIPER_*`
(`app/.env.example:1-6`); the demo requires `OPENAI_API_KEY` (`streamlit_voice_demo.py:273-282`,
default `STT_BACKEND=openai`). → Add it; mark the Piper/Whisper vars legacy-only.

**D4. [HIGH] `SETUP.md` is W1.1-scoped and dangerous.** It calls deps "`>=` floors, re-pin only if a
release breaks it" (`SETUP.md:27-29`) — inviting the pyarrow-24 upgrade the `==21.0.0` pin exists to
prevent — and tells the dev to install `all-MiniLM-L6-v2`/384-dim, not bge-base/768
(`SETUP.md:50-63`). It also calls `sentence-transformers` "optional/commented" when it's an active
requirement. → Rewrite: call out the hard pins as do-not-touch, correct the model id/dim.

**D5. [HIGH] README/app-README corpus + pipeline facts stale.** "89 documents / 37 topics / 78
relationships" (`README.md:6-8`) vs actual **1,109 docs / 9,865 chunks / 34 centroids**; the pipeline
diagram (`README.md:33-47`, `app/README.md:9-25`) names faster-whisper/Haiku-router/Piper/"two Claude
calls per turn" — the develop path is OpenAI whisper-1 → zero-LLM centroid route → bge+BM25 RRF
nucleus → **one** streamed Sonnet call (`llm_calls_before_composition=0`) → tts-1. Repo-layout lists
removed dirs (`app/artifacts/`, `corpus/build_kit/`, `source_materials/`). → Rewrite from handover §2.

**D6. [HIGH] `app/MANIFEST.md` indexes only the legacy files** (README/cj_chat/dashboard/requirements)
and omits every core develop module (`service`, `retrieval`, `embeddings`, `sparse`, `voice_job`,
`voice_io`, `voice_stream`, `filler_route`) and `streamlit_voice_demo.py`. → Rebuild around the actual
pipeline.

**D7. [HIGH] `CHANGELOG.md` tip is 2026-06-30 (W1.8b).** It predates arch-baseline-v4 (bge-base),
OPS-2 (v4.2), and filler v5; its corpus numbers (1,089/8,887) trail the handover (1,109/9,865). →
Append v4.0-v4.2 + filler-v5 entries, or add a pointer to the handover as current head.

**D8. [MED] `PROJECT.md` §6 contradicts develop** ("No vector store at runtime / No chunking /
embeddings offline only", `PROJECT.md:156-172`) and the roadmap still says "35-topic taxonomy". →
Scope banner ("Phase-1 corpus doc; retrieval superseded — see handover") or update §6/§12.

**D9. [MED] `BRANCHES.md` says the embeddings engine exists "on no branch"** (`BRANCHES.md:84-94`,
dated 2026-06-25) — false on develop and never mentions develop. → Add a dated note + reference the
two-branch table.

**D10. [MED] Stale numbers/claims inside code and the source-of-truth handover.**
  - `config.py:17-25` header: NEW-ARCH knobs "NOT yet wired into runtime code … inert until then" and
    BASELINE Haiku router "ships today" — false on develop.
  - `embeddings.py:6` docstring and `app/requirements.txt:37-43` comment say **bge-large/1024**; actual
    is bge-base/768. `config.py:126-128,177` rationale comments also still say "bge-large"/"35×1024"
    while the *values* are correct.
  - Even the accurate handover lists `COMPOSER_MAX_TOKENS=640` (`handover…07-18.md:74`) while
    `config.py:252` is now **480** (lowered same day per the W3.3-LITE comment). Minor, but the one
    number a reader would copy.
  - Root `.env.example` documents `OPENAI_TTS_VOICE=spruce` / `SPEED=0.80` (`.env.example:29,36`) while
    `config.py:369,371` defaults are `echo` / `0.98`. → Align the template's "default" with config (or
    state the sidebar overrides it).

**D11. [SEV/missing] No clean-clone setup guide for develop.** There is **no** correct end-to-end path
to a running voice demo. Undocumented on a fresh clone: (a) rebuild `corpus_dense.npy` (GPU ~17 min)
+ `pilot_sparse.pkl` (both gitignored, `.gitignore:53,56`); (b) regenerate filler clips
(`scripts/gen_v5_theme_clips.py` / `gen_onyx_filler_pool.py` → `assets/filler_clips/<voice>/…`, needs
`OPENAI_API_KEY`) — findability today is **poor (>5 min)**; (c) Piper (well covered in
`docs/robot/PIPER_SETUP.md`, incl. the 401 `Authorization:`-header-clear workaround); (d) the Avast
Service-host profile (only reachable via the handover / `docs/RUNBOOK_transport.md` / MEMORY.md — not
surfaced in any README). **Findability ratings:** pyarrow pin *good* (inline in requirements +
handover); Avast *good only if you reach the handover*; Piper *good*; "HF token" is a **red herring**
(no code reads `HF_TOKEN`; the real gotcha is the injected bad `Authorization` header, documented in
PIPER_SETUP); filler regen *poor*. → Write a `develop` "from clean clone to talking demo" runbook; it
would also seed the missing `CJP_NEW2_Doc_Refresh_Changelist.md` (which does **not** exist).

**D12. [PASS] Module docstrings are a strength.** All eight core files carry real module docstrings;
the only accuracy defect is D10's bge-large line in `embeddings.py:6`.

---

## E. Testing

**Coverage map (existing harnesses):**
- `scripts/verify_filler_v5.py` — **$0** (FakeOAI + stubbed route/gate/retrieve/compose). The
  strongest harness: drives `voice_job.start_job` through 10 scenarios, asserting chain shape
  (T-P-C / T-C / N-C …) **and** the reservation invariant (contiguous indices,
  `reserved==submitted+released`, no dup) every case; cases 9-10 exercise the watchdog/backfill.
  Optional `--smoke` makes ≤2 paid `tts-1` calls. **The reservation invariant / watchdog is genuinely
  well covered — do not re-invest here.**
- `scripts/verify_v4_transition.py` — $0 but heavy (needs the real embedder + built indices). Pins
  recall to 0.618/0.882/0.941/0.971 and matches `retrieval.run` against an **independent
  re-implementation** of the fusion math — caveat: it *re-implements the same formula*, so a shared
  off-by-one would agree with itself (catches regressions only as an end-to-end recall delta).
- `scripts/check_expand_on_demand.py` — $0 parts 1-3 (stubs `compose_streamed` wholesale → never
  touches `_split_envelope`/`_stream_native`); part 4 is a paid live demo.
- `scripts/check_paths.py`, `verify_pin.py` — $0 environment/corpus-integrity diagnostics (not
  behavior). `run_smoke_test.py` — **paid + legacy** (guarded behind `CJ_ALLOW_LEGACY`; runs the
  pre-W1.8 stack — dead for the shipping arch). `streamlit_voice_smoke.py` — paid + manual.
- **No `tests/` dir, no `pytest`/`conftest`/`pyproject` tracked** (all matches are inside `.venv`).
  Verification is ad-hoc PASS/FAIL scripts, not a runnable suite.

**The 5 highest-value missing tests (all $0-runnable with stubs):**

1. **[HIGH] Envelope split + streaming anti-leak** — `service._split_envelope` (`:327`) and
   `_stream_native` (`:356`). The failure it catches: the kiosk literally speaking
   `---ENVELOPE--- {"doc_ids_cited":…}` aloud. `_split_envelope` is a **pure string→(str,dict)** fn
   (zero mocks): feed clean / no-sentinel / sentinel-split-across-chunks / garbled-JSON /
   braces-in-prose and assert. For streaming, a fake `client.messages.stream` yielding a sentinel
   split across chunk boundaries (`"…answer.\n---ENVE"`, `"LOPE---\n{…}"`); assert no `on_text` call
   contains any substring of the sentinel. The `FakeOAI` pattern in `verify_filler_v5.py:27-39` is the
   template. **Already structured for it** (both take params) — no refactor.
2. **[HIGH] `filler_route.decide()` gate table** (`:143`). Catches a gate that *silently stops
   firing* (someone reorders the `if` cascade or flips `THEME_CONF_THRESHOLD`/`TOPIC_MARGIN_THRESHOLD`
   and the kiosk starts naming coin-flip topics or sending in-scope questions to NEUTRAL). Today's
   harness asserts only end-to-end chain shape and feeds **lean** route dicts, so the production
   full-`cos` `clean_margin` branch (`:132-139`) and the `out_of_scope`/`input_gate`/`no_theme_anchor`
   NEUTRAL triggers are never hit. `decide()` is pure; set the cached module globals (`_THEME_OF`,
   `_DISPLAY`, `_FALLBACK`, `_TOPIC_IDS`) to fixed dicts and table-test each `reason` at the 0.51 /
   0.01 boundaries.
3. **[HIGH] `select_nucleus` + RRF fusion core** (`retrieval.py:168`, `:141`). A fusion off-by-one
   (rank 0 vs 1; `>=` vs `>` at the top-p boundary) silently reorders every payload — the exact bug
   `verify_v4_transition` can't isolate. `select_nucleus(su,…)` is **pure** (hand-build `su`, assert
   `kept`/`floor_hit`/`cum_mass`, all three bases). For the RRF loop, either monkeypatch `_load_pilot`
   + `sparse.sparse_score`, or extract the pure fusion (`:141-160`) into `_fuse(...)` taking plain
   dicts. Also worth a test that the `dense_set==sparse_set` invariant (`:126`) holds for the frozen
   allowlist.
4. **[MED] Config load/validation** (`config.py:56-69`). `_env_int/_env_float` swallow `ValueError`
   → default, and there is **no range validation** except the `MAX_TOPIC_TAGS` clamp. `CJ_RETRIEVAL_TOP_P=95`
   (fat-fingered 0.95) silently keeps every chunk; a negative `LAMBDA` or `RRF_K=0` passes. A sweep
   typo produces a wrong-but-running pipeline and wastes a paid eval. → `import config; config.summary()`
   must succeed; add a tiny `config.validate()` (`0<TOP_P≤1`, `MIN_K≥1`, `RRF_K>0`,
   `0≤THEME_CONF≤1`, `EMBED_DIM==index meta`) and assert it.
5. **[MED] Decline scaffolding** (`service.py:322`, `voice_job.py:477-481`). The LLM's actual decline
   judgment needs paid Sonnet (the one genuinely paid gap), but the wiring is a real regression
   surface: assert `_composer_system()` appends `COMPOSER_OOS_DECLINE_TEXT` iff
   `COMPOSER_OOS_DECLINE_ENABLED` (pure, no mocks), and table-test the status classifier after
   extracting it (C4). Locks the scaffolding even though it can't grade the model.

---

## F. Repo hygiene

**F1. [PASS — secrets ALL CLEAR].** `app/.env` (on disk) is **not tracked** (`git ls-files` shows only
`app/.env.example`; ignored via `app/.gitignore`). Every key-pattern hit in tracked files is a
placeholder (`.env.example` `sk-ant-xxxx…`), a docstring example (`cj_chat.py`, `dashboard.py`), a
runtime `os.environ` read (`service.py:210,224,352`), Colab warning-text in the notebooks, or corpus
prose. **No live key/token/password in any tracked file** (no values printed).

**F2. [MED] Root-level eval-JSON clutter — but three files are LIVE FIXTURES, do not move blindly.**
`arch_baseline.json`, `arch_baseline_v2.json`, `w2_1_baseline.json` are read via **hardcoded
`ROOT / "<name>"`** paths in ~10 scripts (`check_date_index.py:38`, `check_expand_on_demand.py:58`,
`run_bakeoff_round3.py:203`, `run_w2_7_ttfa*.py`, `run_w2_2_probe.py:92`, `run_w2_3_cache_probe.py:73`,
…). → They *belong* under `eval/results/`, but only relocate **together with** the path constants in
their readers/writers. Otherwise leave at root.

**F3. [LOW] Root files safe to archive (no readers, none are operator state):** `baseline.json/.jsonl`
(oldest generation, write-only), `w2_2_payload_report.json`, `w2_3_cache_report.json`,
`w2_7_ttfa_report.json`, `w2_7_ttfa_v2_report.json` (week-2 interim, terminal outputs). Move to
`eval/results/` (update the writer's `OUT = ROOT/…`) or archive. `Copy_of_automatic_model_training.ipynb`
is a byte-identical duplicate of `notebooks/automatic_model_training.ipynb` — fold in or drop.

**F4. [LOW] CJP docx/xlsx/png deliverables at root** (`CJP_Dimensional_Modelling.docx`,
`CJP_RAG_Kiosk_Paper_DRAFT.docx`, `CJP_Retrieval_Methods_Rationale.docx`,
`CJP_Latency_Cost_Assessment(_v2).docx`, `CJP_Pilot_Report_W3_5_SCAFFOLD.docx`,
`CJP_Pilot_Weekly_Plan(_v2).xlsx`, `CJP_Pipeline_Architecture.png`, `W1.10_Decisions_Memo.docx`) →
relocate under `docs/` or `reports/` (`reports/pilot-eval subset/` already holds docx/xlsx). Keep the
`.md` twin of the W1.10 memo tracked (diffable); the `.docx` is a rendered artifact.

**F5. [LOW] `streamlit_voice_smoke.py` is superseded** by `streamlit_voice_demo.py` (current demo host)
and is imported nowhere (referenced only in comments at `config.py:364`, `bench_stt_backends.py:126`).
→ Archive post-demo; update the two comment references. (Its `voice_smoke_log.csv` is operator state —
leave it.)

**F6. [LOW] `.gitignore` gaps/over-reaches.** Solid on secrets/venv/by-policy assets. Gaps: no
`~$*` (Office lock/temp files, risky with many tracked docx/xlsx at root); the `_*` scratch convention
is scoped to `eval/results/` only, so any generated JSON dropped at root auto-tracks (how the F2/F3
clutter accumulated); no `.ipynb_checkpoints/`. Latent over-reaches: `models/`, `env/`, `ENV/` would
hide any dir of that literal name (none exists today). → Add `~$*`; consider writing all eval output
under `eval/results/`.

**F7. [naming] Inconsistencies:** baseline lineage drifts `baseline → arch_baseline → arch_baseline_v2`
(no `_v1`), then v3/v4/v4.2 moved into `eval/results/` while v1/v2 stayed at root; `w2_*` reports at
root while all `w3_*` live under `eval/results/` (same generator pattern, split location);
`Copy_of_` Colab prefix. → Normalize when F2/F3 are relocated.

---

## G. Robot-readiness (vs RI-301)

RI-301's Path B keeps STT/TTS/chunking/envelope on our side and uses the SDK only for raw audio I/O +
motion (`media_backend="no_media"`); the pipeline is a pure text-in/prose-out slot with a trailing
(never-spoken) ENVELOPE and a `cancel()` for barge-in.

**G1. [HIGH] There is no headless voice entrypoint — only a headless *text* one.** `service.answer()`
is a clean text-in/text-out seam (and `service._resolve_transport()` will auto-pick `native_sdk` on
the Linux CM4, so the `schannel_curl` Windows/Avast artifact self-resolves — no change needed there).
But the *voice* orchestration lives inside `voice_job.run()`, shaped around Streamlit's poll-via-rerun
job dict and the browser gapless component. So today the robot has a text slot but no voice loop to
drop into.

**G2. [MED] The intended TTS swap point exists but the shipping path bypasses it.** `voice_stream.py`
defines the `TTS` protocol (`synth(text)→(wav,ms,s)`) with `SapiTTS` and a ready `PiperTTS` drop-in
(`voice_stream.py:100-121`; `PIPER_SETUP.md` verifies ~2s local synth) — exactly the "swap not
rewrite" seam RI-102 wants. But `voice_job` calls OpenAI TTS inline (`voice_job.py:173,400,416`) and
never uses the protocol. → The robot port must re-route `voice_job`'s synth through a pluggable
`TTSBackend` (the `voice_stream` protocol), not OpenAI-inline.

**G3. [MED] Browser-only machinery to shed on-robot.** The b64 chunk dicts, the reservation-index
invariant, and the R-28 silence-backfill (`voice_job.py` + `components/gapless_audio/index.html`) are
browser-playback concerns; RI-102 says the SDK owns playback ordering on-robot, so that layer is
bypassed rather than ported. Good — it means the robot loop is *smaller*, not a rewrite; but it must be
consciously dropped, not carried.

**G4. [MED] No cancellation hook for barge-in.** RI-301 exposes `cancel()` as a design stub, but the
compose loop (`_stream_native`, `client.messages.stream`) has no mid-turn cancel and the TTS synth
futures aren't interruptible. → Wire a `cancel_event` through the orchestrator (checked in the stream
loop and before each `submit`/synth) when the SDK's interrupt lands.

**Shortest path to a headless service entrypoint:** the pieces all exist (SentenceChunker,
`compose_streamed` with `on_text`, `filler_route.decide`, the `TTS` protocol, `service._directives`,
the auto transport). What's missing is a small orchestrator that assembles them **without** Streamlit
or the browser player — e.g. `run_voice_turn(text, tts_backend, on_prose, on_audio, cancel_event)` —
extracted from `voice_job.run()`, emitting audio via the `TTSBackend` protocol and dropping the
gapless/reservation-index layer. This single extraction (which also resolves C1 by giving the demo and
the robot one shared orchestrator) is the highest-leverage robot-readiness task and is post-demo work.

---

## Proposed cleanup sequence — three tiers

### Tier 1 — pre-demo-safe (zero behavior change; do before Aug)
Documentation + inert-code only; nothing here touches the retrieval/compose/filler behavior, config
defaults, indices, or tags.
1. Fix the broken quick-starts (D1) and add the missing `OPENAI_API_KEY` to `app/.env.example` (D3) —
   the two things that break a new dev on minute one.
2. Banner or correct `architecture.md` (D2), `SETUP.md` pins+model (D4), README/app-README/app-MANIFEST
   facts (D5/D6), CHANGELOG pointer (D7), and the bge-large / "NEW-ARCH not wired" code comments (D10).
3. Add a one-page **clean-clone → talking-demo runbook** (D11): entrypoints, `OPENAI_API_KEY`, index
   rebuild, filler regen, Avast profile, Piper — and drop the "HF token" red herring.
4. Delete/annotate the inert dead code and knobs that carry zero risk: `service._compose` (A2), the
   `WARM_ON_BOOT` no-op branch (A4), the four dead config knobs (A7).

### Tier 2 — post-demo (small behavior-adjacent changes; verify each)
1. Fix the compose-retry re-emit (A1) — small, but it's a genuine correctness bug; verify with a
   fault-injection stub.
2. Route the live path's `whisper-1`/`tts-1`/speed/voice through config (A7/C-drift), so `voice_job`
   is config-clean before the robot reuses it.
3. Harden the RRF universe assert (A5) into a survivable exception + logged intersection.
4. Land the 5 $0 tests (E1-E5) — start with the envelope anti-leak and the filler gate table (pure,
   no mocks). Convert the ad-hoc scripts into a minimal `pytest` suite.
5. Relocate the root clutter (F3/F4/F5) — **but** leave the three live-fixture JSONs (F2) unless you
   move their reader paths in the same change. Add `~$*` to `.gitignore` (F6).

### Tier 3 — nice-to-have / robot-window
1. Extract the headless `run_voice_turn(...)` orchestrator (G1) — resolves the two-path divergence
   (C1) and the browser coupling (C2/G3) in one move; route TTS through the protocol (G2); wire
   `cancel_event` for barge-in (G4).
2. Consolidate the duplicated `theme_anchor` mapping (C3) and status classifier (C4).
3. Paid-verify and consider promoting `STREAM_TTS_ENABLED` (B2); revisit streaming/partial STT (B1) at
   robot time.
4. Branch-scoping decision for `app/app.py` / `cj_chat.py` / `dashboard.py` (C5) at the
   kiosk↔develop merge.

---

## Overall assessment

**For a project two weeks from a public demo, the engine is in genuinely good shape and the paperwork
is the liability.** The retrieval → compose → filler → gapless-TTS core is well-instrumented, resident
(no per-request re-init), $0-testable in the parts that matter most, and — critically — the hard-won
threaded playback invariant that caused the Q2 total-silence SEV is now guarded and *tested*. Secrets
are clean, the config is a real single-source-of-truth, and the pipeline core is already Streamlit-free,
so the robot port is a small extraction rather than a rewrite. The genuine bugs are few and narrow: a
latent compose-retry double-speak, an assert that can blank a turn, and config literals that bypass
their own knobs — all low-effort. The real risk is onboarding and truth-in-docs: a fresh clone has **no
correct path to a running demo**, the top-level docs (README, architecture.md, SETUP.md, PROJECT.md)
confidently describe the *previous* architecture, and the two documented quick-starts now hard-exit.
None of that threatens the demo *if the same operator runs it*, but it is exactly what bites a new pair
of hands, a reviewer, or the robot integrator arriving next week. Spend the pre-demo window on the
Tier-1 documentation/onboarding fixes (a day of low-risk edits), keep the code changes for after the
demo, and this is a healthy, demo-ready repo whose only embarrassment would be someone trying to start
it from the README.
