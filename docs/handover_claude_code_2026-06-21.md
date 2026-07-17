# Engineering Handover — Supervaise FLP / CJ Panganiban Conversation App
### (Reconciled & migrated edition)

**Originally prepared:** 2026-05-31 (against `main` @ `0cc6be9`)
**Reconciled & migrated:** 2026-06-21 (against working branch `pre-wake-word-integration` @ `6858369`)
**Repo:** https://github.com/jeanettepao-star/Supervaise-Reachy-Mini-Project
**Local clone:** `C:\Reachy Mini Project 2026`
**Prepared for:** next Claude Code instance picking up the project

> **⚠️ SCOPE (added 2026-07-18):** This handover describes the **push-to-talk voice
> kiosk** on branch `pre-wake-word-integration` — a **no-embeddings** Haiku-router
> architecture. The `develop` branch runs a **different** architecture: an
> embeddings-based retrieval pipeline (bge-base + BM25 + RRF + centroids), whose
> current baseline is **arch-baseline-v4.2**. For that, see
> [handover_claude_code_2026-07-18.md](handover_claude_code_2026-07-18.md). Do not
> apply this doc's "no embeddings" framing to `develop`.

---

## 0. MIGRATION & RETRACTION NOTE (read first)

This handover was originally written on 2026-05-31 at `main` @ `0cc6be9`, describing
the **push-to-talk** voice kiosk. After that date, a wake-word integration
(**PLAN-0008**) was built and landed on `main` (HEAD `c76a9aa` — "PLAN-0008 — wake-word
integration complete"). **That wake-word work is being deliberately retracted.**

- **Work here, on `pre-wake-word-integration`** (HEAD `6858369` — "revert: drop wake-word
  scaffolding · return to push-to-talk kiosk"). This branch is the clean push-to-talk
  baseline and is the **source of truth** for this project.
- **Do not merge or cherry-pick from `main`.** `main` is ahead with the retracted
  wake-word feature; pulling it back re-introduces exactly what is being removed.
- There is **no wake word** in this build. The kiosk is push-to-talk: the visitor
  presses START/STOP. Nothing in this document refers to always-listening or
  wake-word triggering, because none exists on this branch.

The body below has been reconciled against the actual branch state. A changelog of
what changed versus the 2026-05-31 original is at the end (§13).

---

## 1. WHAT WAS BUILT

### Plain language
A voice-only museum-kiosk web app where a visitor presses a START/STOP
button, asks retired Philippine Chief Justice Artemio V. Panganiban a
question out loud, and hears a spoken reply in his voice. Behind the
kiosk is a hand-curated corpus of his published writing (65 columns +
15 speeches) and a 35-topic taxonomy. The app routes the visitor's
question to a few topics, lets Claude Sonnet compose a reply grounded
in those topics, has Haiku quickly check the reply for fidelity, then
synthesises speech via OpenAI TTS. The Reachy Mini robot avatar
provides the visual front-of-house.

### Technical components
- **Two Streamlit entry points** sharing one pipeline:
  - `app/app.py` — production museum kiosk (single-file, dark glass
    theme, twin frosted-glass console).
  - `app/dashboard.py` — developer/operator dashboard with verbose
    diagnostics.
- **`app/cj_chat.py`** — pure-pipeline module: corpus loader, Haiku
  **input gate** (in_corpus / OOC / META), Haiku **router** (picks
  1-3 topics with confidence), Sonnet **streamed composer**, Haiku
  **fidelity check**.
- **`app/voice_io.py`** — OpenAI Whisper STT (single call per
  recording) + tts-1 TTS (per-sentence parallel `asyncio.gather`,
  pydub concatenation, optional `imageio-ffmpeg` for ffmpeg binary).
- **Pre-processing pipeline** (`scripts/`) that turns the raw
  `data/csv/` + `data/text/` into 80 paired `.md`+`.json` corpus
  files + the topic map + the smoke-test runner.
- **Governance** — 18 ADRs, 11 lessons, 7 implementation plans, 6
  test specs, 5 persona guides, all manifested.
- **Vendored harness** — `claude-harness-public/` (Supervaise-Inc
  orchestration templates + skills) added in-place at the repo root.

---

## 2. STACK & ARCHITECTURE

| Layer | Stack |
|---|---|
| UI | **Streamlit ≥ 1.40** (Python), heavy custom CSS (frosted-glass, twin pill buttons, live progress drop-downs) |
| Chat | **Anthropic SDK ≥ 0.40.0** — Haiku 4.5 (`claude-haiku-4-5-20251001`) for router/gate/fidelity, Sonnet 4.6 (`claude-sonnet-4-6`) for composer; all 4 stages use **prompt caching** (`cache_control: ephemeral`) on the voice_card / router_prompt system prompt |
| Voice | **OpenAI SDK ≥ 1.40.0** — `whisper-1` STT + `tts-1` TTS; per-sentence parallel chunking + pydub concat (the accepted online stack, **ADR-0018**) |
| Audio | **pydub ≥ 0.25.1** + **imageio-ffmpeg ≥ 0.4.9** (bundles ffmpeg binary; falls back to raw MP3 byte concat if absent) |
| Env | **python-dotenv ≥ 1.0.0** — multi-location `.env` loader (cwd → repo-root → `app/`) |
| Data | Hand-curated 35-topic taxonomy in `corpus/voice/topic_map.json`; 80 paired `.md`+`.json` corpus files |

**No vector DB / no embeddings** — routing is a Haiku call against the
hand-curated taxonomy (decided in ADR-0003).

**Voice stack — confirmed current (2026-06-21):** the online path runs **OpenAI
hosted** `whisper-1` (STT) + `tts-1` (TTS), per **ADR-0018** (accepted 2026-05-26).
The local **faster-whisper + Piper** stack (ADR-0006 / ADR-0007) is the **offline /
air-gapped fallback only** — still "accepted" but explicitly superseded for online
operation by ADR-0018. ⚠️ Note: the **PLAN-0006 plan doc is stale** — it still names
Piper/Whisper as the stack and does not mention ADR-0018. Trust **ADR-0018 +
`app/voice_io.py`** as the source of truth for the voice stack, not PLAN-0006.

**Pipeline data flow** (museum kiosk, runs inline on the same script
execution that captured audio):

```
mic → st.audio_input → WAV bytes
  → transcribe_openai (Whisper) → user transcript
  → input_gate (Haiku, scope: in_corpus / out_of_corpus / identity_probe)
  → route_question (Haiku, primary_topic + confidence + 0-2 secondary)
      ↪ if identity_probe → force_meta_routing
  → build_context (topic data + 2-3 source documents)
  → generate_response_stream (Sonnet, streamed text)
  → fidelity_check (Haiku, advisory flags)
  → tts_concatenate_parallel (OpenAI tts-1, per-sentence) → MP3
  → st.audio(autoplay=True) → PLAY button enables for replay
```

---

## 3. REPO MAP

```
.
├── README.md                  Overview + pipeline diagram
├── CLAUDE.md                  Navigational entry for any LLM agent
├── PROJECT.md                 Runtime tuning detail
├── architecture.md            Architectural notes (read once)
├── End Point.txt              Quick PowerShell launch commands
│
├── app/                       ⚡ ENTRY POINT — the runnable kiosk
│   ├── app.py                 (1 380 LOC) production museum-kiosk Streamlit app
│   ├── dashboard.py           (1 111 LOC) developer dashboard (parallel UI)
│   ├── cj_chat.py             (1 324 LOC) shared pipeline (CLI + library)
│   ├── voice_io.py            (450 LOC) OpenAI STT + chunked TTS
│   ├── requirements.txt
│   ├── .env.example           (keys + model overrides)
│   ├── assets/                reachy_curious.png, museum_bg.jpg (with SVG/CSS fallbacks)
│   ├── piper/                 (gitignored) legacy Piper binary cache
│   ├── voices/                (gitignored) legacy Whisper/Piper models
│   ├── state/                 (gitignored) runtime TTS cache
│   ├── MANIFEST.md
│   └── README.md
│
├── corpus/                    📚 the runtime corpus the app reads
│   ├── voice/
│   │   ├── topic_map.json     35-topic taxonomy (hand-curated)
│   │   ├── voice_card.md      Sonnet system prompt (375 lines, contains length bands)
│   │   └── router_prompt.md   Haiku router system prompt
│   ├── columns/{theme}/       65 paired .md+.json
│   ├── speeches/{theme}/      15 paired .md+.json
│   └── MANIFEST.md
│
├── scripts/                   pipeline tooling (idempotent)
│   ├── generate_corpus_files.py
│   ├── build_topic_map.py
│   ├── apply_topic_paths.py
│   ├── check_paths.py
│   └── run_smoke_test.py
│
├── data/                      raw inputs
│   ├── csv/   (3 curated CSVs)
│   └── text/  (80 source .txt)
│
├── docs/                      governance — never auto-generated
│   ├── decisions/   ADR-0001 … ADR-0018  (+ MANIFEST.md)
│   ├── lessons/     LL-001 … LL-011      (+ MANIFEST.md)
│   ├── implementation-plans/ PLAN-0001 … PLAN-0007 (+ MANIFEST.md)
│   ├── test-specs/  TS-001 … TS-006      (+ MANIFEST.md)
│   ├── guides/      GUIDE-end-user/-reviewer/-admin/-manager/-firstrun (+ MANIFEST)
│   ├── handover_claude_code_2026-05-15.md / -16.md / -26.md / -31.md
│   └── MANIFEST.md
│
└── claude-harness-public/     vendored orchestration scaffolding (140 files)
    ├── modules/ patterns/ templates/ scripts/ docs/ hooks/
    └── README.md, MIGRATION.md, registry.yaml, bootstrap-prompt.md
```

**Entry point:** `app/app.py` (museum kiosk). `app/dashboard.py` is the
alternate developer surface.

> Note: `docs/implementation-plans/` holds PLAN-0001–0007. There is **no PLAN-0008**
> on this branch (consistent with the wake-word retraction). The `claude-harness-public/`
> tree carries its own unrelated `001–010` planning docs — that is the vendored
> toolkit, not this project's plans.

---

## 4. FILES CREATED / MODIFIED (original 2026-05-15→31 timeframe)

### Created
- `app/app.py` — museum-kiosk Streamlit entry point (single-file, ~1 380 LOC).
- `app/voice_io.py` — OpenAI STT + TTS + cost-estimation module.
- `app/assets/reachy_curious.png` — robot avatar override.
- `app/assets/museum_bg.jpg` — gallery backdrop override.
- `docs/decisions/0017-end-user-ui-also-streamlit.md`
- `docs/decisions/0018-openai-stt-tts-with-claude-chat.md`
- `claude-harness-public/**` — 140 files vendored as plain copies of
  `Supervaise-Inc/claude-harness-public`.

### Modified
- `app/cj_chat.py` — input gate, fidelity check, context-block builder,
  honesty rule, env-configurable models, prompt caching wiring,
  `max_tokens` 600 → 420 → **300** for composer.
- `app/dashboard.py` — Reachy Mini SVG, drawer → pure-CSS slide-in →
  inline live-progress dropdown.
- `corpus/voice/voice_card.md` — length bands compressed twice
  (final: 60-100 / 20-40 / up to 150 words).
- `corpus/voice/router_prompt.md` — JSON schema, confidence levels,
  OOC and identity-probe rules.
- `corpus/voice/topic_map.json` — 35-topic hand-curated taxonomy.
- `End Point.txt` — corrected launch instructions to point at `app.py`.

---

## 5. FEATURE STATUS

| Feature | Status | Evidence |
|---|---|---|
| Corpus generator (Phase 1) | ✅ Working | 80 paired files produced; `reports/generation_report.json` clean |
| Topic map + topic_paths (Phase 2) | ✅ Working | `reports/topic_map_report.json` clean; `check_paths.py` passes |
| Voice card (Phase 3) | ✅ Working | 375-line voice card with compressed length bands |
| Runtime pipeline (PLAN-0001 §A-E) | ✅ Working | `reports/smoke_test_summary.json`: 30/30 completed, 96.7 % primary routing, 92 % fidelity-clean, 100 % META routing, mean 241.7 w/turn (pre-compression numbers — re-running needed after the 50 % compression) |
| Smoke runner (`scripts/run_smoke_test.py`) | ✅ Working | TS-006 questions executed end-to-end |
| Developer dashboard (`app/dashboard.py`) | ✅ Working | Manual verification across many turns |
| Museum kiosk (`app/app.py`) | ✅ Working — but iterated heavily across ~15 UI fix-ups; needs a full smoke pass after the latest pill-dedupe fix | The user has been running it interactively; latest fix addressed the duplicate post-recording pill |
| OpenAI STT/TTS (`voice_io.py`) | ✅ Working | Echo voice @ 0.98 speed; per-sentence parallel TTS; online stack per ADR-0018 |
| Anthropic prompt caching | ✅ Working | 18 % observed savings (LL-001); cache headers correctly applied on all 4 Anthropic call sites |
| Topic-map evolution + diagnostics (PLAN-0007) | ✅ Working | Matcher health check + generator output hygiene diagnostics implemented (§4 + §5) |
| **PLAN-0002 — end-user *text* web chat UI** | ⏳ **Specced, not built** | Plan status "draft, Phase 5"; locked to Streamlit by ADR-0017; **no implementing commit**. This is a *text* chat surface, **distinct from the shipped voice kiosk** (voice was deferred to PLAN-0006). Do not treat the kiosk as satisfying PLAN-0002. **Open question for the team: is the text web chat still wanted given the kiosk pivot, or should PLAN-0002 be retired?** |
| Local Whisper/Piper fallback path | ⚠️ Code present but **not in active use** — ADR-0018 supersedes it for online operation; `app/piper/` + `app/voices/` are gitignored |
| `claude-harness-public/` integration | ⚠️ **Vendored but not wired** — no hooks, no `settings.json` link, no consumers in app code yet. Pure drop-in scaffolding. |
| End-to-end smoke run **after** the 50 % response compression | ❌ **Not yet re-run** — smoke_test_summary.json reflects pre-compression word counts |

---

## 6. DATA COUPLING

### What the runtime consumes

| Artifact | Path | Format | Loaded by | Schema assumptions |
|---|---|---|---|---|
| Topic map | `corpus/voice/topic_map.json` | JSON object | `cj_chat.CorpusArtifacts.__init__` | 35 topics, each with `name`, `description`, `themes`, optional `signature_phrases` |
| Voice card | `corpus/voice/voice_card.md` | Markdown | system prompt for Sonnet composer (cached) | length bands at heading `## Length and register guidance` |
| Router prompt | `corpus/voice/router_prompt.md` | Markdown | system prompt for Haiku router (cached) | must produce JSON with `primary_topic`, `confidence` (high/medium/low), optional `secondary_topics`, `reasoning` |
| Corpus docs | `corpus/{type}/{theme_folder}/{id}.{md,json}` (80 files) | paired md/json | `CorpusArtifacts.load_document(routing)` | id pattern: `[SC][A-E]NNN` (e.g. `SA136`, `CA001`); JSON must include `topic_paths` (list of `theme/topic` strings) — populated by `scripts/apply_topic_paths.py` |
| Smoke-test questions | `docs/test-specs/TS-006-smoke-test-questions.json` | JSON array | `scripts/run_smoke_test.py` | 30 questions, 6 themes × 5 |

### Baked-in assumptions
- **Article-code padding**: 3-digit numeric (`CA001`, not `CA1`) —
  `normalize_article_code()` fixes both shapes (LL-010).
- **CSV encoding fallback chain**: `utf-8` → `cp1252` w/
  errors=replace (LL-007).
- **CSV semicolon-or-JSON mixed cells** tolerated by permissive
  parser (LL-006).
- **Column .txt files have no `---` separator** — `normalize_body()`
  handles both column and speech formats (LL-008).
- **Word-boundary regex** for substring matching (LL-009).
- **Five canonical themes**: `A_liberty_rule_of_law`,
  `B_prosperity_economic_philosophy`, `C_biographical_personal`,
  `D_flp_mission_foundation`, `E_current_events_commentary` —
  hard-coded across pipeline + router prompt.

> ⚠️ Reconciliation caution: `data/text/GC001.txt` and
> `data/csv/cjp_biography_curated.csv` exist as **source inputs only** — the GC001
> biography (PLAN-0004) is **not ingested** into `corpus/`. The corpus type letters
> are only `C` (columns) and `S` (speeches); there is no type-`B` book corpus
> (PLAN-0005). The `C_biographical_personal` *theme* is a column/speech theme, not
> evidence that the biography was ingested.

### Inputs the runtime does **not** consume
- Raw `data/csv/` and `data/text/` — those are pipeline inputs,
  processed by `scripts/generate_corpus_files.py`, not loaded at
  runtime.

---

## 7. HOW TO RUN / BUILD / TEST

> Paths below use the current clone location, **`C:\Reachy Mini Project 2026`**.
> ⚠️ The repo's own `End Point.txt` still hard-codes the *old* operator path
> (`C:\Users\ASUS\Projects\Supervaise-Reachy-Mini-Project`) — ignore that or fix it.

### One-time setup (PowerShell, from repo root)

```powershell
cd "C:\Reachy Mini Project 2026\app"
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# edit .env to add ANTHROPIC_API_KEY + OPENAI_API_KEY
```

### Launch the museum kiosk

```powershell
cd "C:\Reachy Mini Project 2026\app"
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

### Launch the developer dashboard

```powershell
streamlit run dashboard.py
```

### Pre-processing pipeline (only when corpus inputs change)

```powershell
python ..\scripts\generate_corpus_files.py
python ..\scripts\build_topic_map.py
python ..\scripts\apply_topic_paths.py
python ..\scripts\check_paths.py
```

### Smoke test

```powershell
python ..\scripts\run_smoke_test.py
# writes reports/smoke_test_run.json + smoke_test_summary.json
```

### Required env var **names** (values go in `app/.env`)
- `ANTHROPIC_API_KEY` — required (chat)
- `OPENAI_API_KEY` — required (STT + TTS)

### Optional env vars (with current defaults)
- `ROUTER_MODEL` → `claude-haiku-4-5-20251001`
- `INFERENCE_MODEL` → `claude-sonnet-4-6`
- `OPENAI_TTS_VOICE` → `echo`
- `OPENAI_TTS_SPEED` → `0.98`
- Legacy: `WHISPER_MODEL`, `PIPER_BIN`, `PIPER_VOICE` (only used by
  the offline-fallback code path — not in production)

### Pre-flight check
`app.py` runs `_preflight()` which blocks page load with a clear
remediation banner if `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` is
missing, and prints a `pip install` command built from `sys.executable`
if any in-repo import fails.

---

## 8. TECHNICAL DECISIONS

| Decision | Reasoning / Tradeoff | ADR |
|---|---|---|
| Claude (Anthropic) for chat, not OpenAI | Better long-form reasoning at this register; the user's relationship is with Anthropic | 0001 |
| Tiered LLM (Haiku router, Sonnet composer) | ~10× cost reduction vs Sonnet-everywhere; latency-acceptable | 0002 |
| **Reject embeddings / no vector store** | 35 topics are small enough to hand-curate; deterministic; auditable | 0003 |
| Topic-routed two-stage API (not RAG) | The "Pattern 1" architecture | 0004 |
| Defer Reachy Mini robot embodiment for May 30 | Out of scope; demo is a laptop kiosk | 0005 |
| Local STT (faster-whisper) — original online choice | Privacy / no per-call cost | 0006 |
| Local TTS (Piper en_US-ryan-high) — original online choice | Privacy / no per-call cost | 0007 |
| **End-user web chat UI is also Streamlit (single-stack)** | One stack, faster iteration, kiosk-acceptable; lets PLAN-0002 land without an interrupting ADR | 0008, 0017 |
| **OpenAI STT/TTS for the online path (push-to-talk), not Realtime API** | Per-turn cost ~$0.054-0.066; Realtime would be 10-20×. **Supersedes ADR-0006/0007 for online; they remain the offline fallback.** | 0018 |
| Messages API, not Managed Agent | Caching control + lower latency | 0009 |
| Prompt caching on voice_card (cache_control: ephemeral) | 18 % cost savings observed (under the lower bound predicted by Anthropic — LL-001) | 0010 |
| Hand-curated taxonomy lives in Python code | Auditable, version-controlled, easy to evolve | 0014 |
| 4-character corpus IDs `[SC][A-E]NNN` | Sortable, theme-encoded, no DB needed | 0011 |
| Permissive CSV parser | Real-world CSV from `cp1252` Windows tools has mixed cell formats (LL-006) | 0012 |
| Strict date validation, no placeholder dates | Caught a real bug | 0013 |
| `topic_paths` derivation as a backfill step | Decouples generation from taxonomy choice | 0015 |
| Theme-anchored register selection | Lets the composer adopt a different rhetorical register per theme | 0016 |
| **Inline pipeline pattern** (no PROCESSING state) | The previous state-machine handoff lost audio bytes between reruns silently. dashboard.py worked because it ran the pipeline inline; ported to app.py. Hash-of-bytes guard prevents re-firing on subsequent reruns. | (none yet; should write ADR-0019) |
| **CSS `:has()` for recording-state detection** | Streamlit's audio_input owns its state client-side; Python never sees the click. `:has(button[aria-label*='stop' i])` reads it from the DOM. | (none yet) |
| Composer `max_tokens=300` + halved length bands | Two sequential 30 % cuts at user request. 300 tokens ≈ 200 words, comfortably above the new 150-word upper band. | (none yet; should write ADR-0019) |

---

## 9. KNOWN ISSUES / TODOs

### Real
1. **Smoke test not re-run after compression**.
   `reports/smoke_test_summary.json` says
   `mean_response_word_count: 241.7` — that's from the
   **pre-compression** runtime. Re-running TS-006 against the
   current voice card + `max_tokens=300` is the single most useful
   next verification.
2. **PLAN-0006 plan doc is stale.** It still documents the
   faster-whisper + Piper stack and cites only ADR-0006/0007; it does
   **not** reference ADR-0018 or the OpenAI stack the code actually
   runs. ADR-0018's own consequences note that PLAN-0006 needs a small
   update. Bring PLAN-0006 in line with ADR-0018 + `app/voice_io.py`
   (online = OpenAI; offline fallback = Piper/Whisper).
3. **No ADR yet for the late-stage runtime changes**. The
   inline-pipeline port, the audio-input-as-button CSS architecture,
   and the response compression all deserve an ADR-0019 to lock in
   the rationale.
4. **`claude-harness-public/` is vendored but unwired**. None of the
   modules, hooks, or templates are integrated yet. No registry
   call-sites; no `settings.json` references it.
5. **`fidelity_check` flags do nothing yet**. Results are surfaced
   in the diagnostic dropdown but not used to gate the response. The
   plan was advisory-only for v1 (per PLAN-0001 §E) and that hasn't
   changed.
6. **Local-fallback offline path is stale**. The `app/piper/` +
   `app/voices/` legacy assets are gitignored; the offline branch
   (faster-whisper + Piper) is still imported on a soft path in
   `cj_chat.py` but not exercised. ADR-0006 / ADR-0007 mark them as
   the offline fallback — needs a manual run to confirm they still
   work.
7. **Streamlit `st.audio_input` DOM is private API**. The pill
   styling relies on `[data-testid='stAudioInput']` +
   `:has(button[aria-label*='stop' i])`. Any Streamlit upgrade may
   shift the test IDs or aria-labels and break the START/STOP
   visual. Captured in source comments but not in an ADR.
8. **Cost tracking still runs but is hidden**. Per the user's spec
   the cost pill + `_card_spend` were removed. The `session_cost` /
   `last_turn_cost` accumulators still update — fine, just noting
   that no UI consumer remains.

### Open product question
- **PLAN-0002 (text web chat) is specced but unbuilt.** It is a separate surface
  from the shipped voice kiosk. Decide whether it is still wanted now that the
  end-user experience is the voice kiosk, or whether PLAN-0002 should be formally
  retired.

### Fragility
- **End Point.txt** points at the absolute Windows path
  `C:\Users\ASUS\...` — fine for the original operator's machine, not
  portable, and not the current clone path (`C:\Reachy Mini Project 2026`).
- **Anthropic model strings hard-coded as `claude-sonnet-4-6` /
  `claude-haiku-4-5-20251001`**. When Anthropic publishes 4.7+, both
  default constants need bumping (or `.env` override). Cache key
  invalidates on any change to the voice_card.
- **`pydub` + `imageio-ffmpeg` are optional**. Without them,
  voice_io falls back to raw MP3 byte concatenation — some browsers
  play it with seam clicks.
- The pre-flight check **doesn't catch a corrupted
  `corpus/voice/topic_map.json`** — it only verifies env keys.

---

## 10. GIT STATE  *(rewritten 2026-06-21)*

- **Working branch**: `pre-wake-word-integration`
  (tracking `origin/pre-wake-word-integration`)
- **HEAD**: `6858369` — "revert: drop wake-word scaffolding · return to
  push-to-talk kiosk"
- **Working tree**: ✅ clean (`nothing to commit, working tree clean`)
- **`main` is ahead** at `c76a9aa` — "PLAN-0008 — wake-word integration complete
  (Task 1 + Task 2)". **This is the RETRACTED feature. Do not merge or cherry-pick
  `main` into this branch.**
- **Remote**: `https://github.com/jeanettepao-star/Supervaise-Reachy-Mini-Project.git`

### Push-to-talk lineage (pre-wake-word — the substantive history under HEAD)

```
6858369 revert: drop wake-word scaffolding · return to push-to-talk kiosk  ← HEAD
0cc6be9 chore: vendor claude-harness-public at repo root
dd50d00 feat(voice+kiosk): 50% response compression · echo @0.98 · pill dedupe
e8d182b feat(kiosk): inline pipeline + twin glass console + text START/STOP pill
2cf9b88 fix(kiosk): rename ss._pending_audio → ss.pending_audio (silent state-bounce bug)
639d522 fix(kiosk): compact layout — progress dropdown fits in viewport
401a6cf fix(kiosk): live progress dropdown actually shows cards
dd3ed6a fix(kiosk): inline live-progress dropdown
4f3c5a3 fix(kiosk): RECORD→START · running cost pill · bulletproof autoplay
93fef11 fix(kiosk): museum-blurb on a single line, smaller font
c5a2f8f fix(kiosk): pure-CSS slide-in drawer
45e0130 feat(kiosk): app.py — museum-grade single-file kiosk entry point
e86b05d feat(ui): echo voice @ 0.75 + autoplay + museum copy
4f88d23 fix(voice): default voice to spruce + speed to 0.80
9d49f4d fix(app): SVG render + ffmpeg-missing warning
c5e1ffd fix(app): voice-deps install command from sys.executable
61810de fix(app): voice-deps pre-flight + SMIL Reachy avatar
71510b6 fix(voice): cadence — speed 0.82 + reflective ellipses
a888930 fix(voice): nova (female) → onyx (deep male)
88e7c68 feat(app): OpenAI STT/TTS + Reachy Mini avatar + dark theme
6931cb5 fix(app): robust .env loading + env-configurable models
```

> The list above is the push-to-talk history captured at the original handover
> (`0cc6be9`) plus the revert HEAD. Depending on how the branch was cut, the
> wake-word commits may also appear between `0cc6be9` and the revert. For the exact
> verbatim graph, run `git log --oneline --graph -30` on this branch.

### Items on disk but not in git (intentional)
- `app/.env` — secret, gitignored.
- `app/piper/`, `app/voices/`, `app/state/`, `app/__pycache__/` —
  gitignored.
- `claude-harness-public/` — fully committed (stripped its nested
  `.git/` so plain files were trackable).

---

## 11. WHERE YOU LEFT OFF + NEXT STEPS

### State at migration (2026-06-21)
On `pre-wake-word-integration`, clean tree, HEAD `6858369`. The wake-word work on
`main` is being retracted; this branch is the working baseline.

### Last substantive work before the wake-word detour
Commit `0cc6be9` vendored `claude-harness-public/` at the repo root (140 files,
in-place copy, no upstream link). Prior to that, `dd50d00` bundled three changes:
1. ~50 % response-length compression (two consecutive 30 % cuts) — composer length
   bands halved, `max_tokens` 600 → 300.
2. TTS flipped to `echo` @ `0.98` (was `onyx` @ `0.97`).
3. Duplicate START/STOP pill fix (CSS `:not()` chain to hide the post-recording
   play-preview button).

### Recommended next moves (in order)

1. **Re-run the smoke suite against the compressed runtime.**
   ```powershell
   cd "C:\Reachy Mini Project 2026\app"
   .\.venv\Scripts\Activate.ps1
   python ..\scripts\run_smoke_test.py
   ```
   Read `reports/smoke_test_summary.json` — verify
   `mean_response_word_count` drops from 241.7 toward the new band
   (~100-130 words) and `substantive_response_rate` stays at 1.0.
   Fidelity-clean and routing-accuracy should not regress.

2. **Update PLAN-0006** to match ADR-0018 + `app/voice_io.py` (online = OpenAI
   `whisper-1`/`tts-1`; offline fallback = faster-whisper + Piper). The plan doc
   currently trails both the decision and the code.

3. **Write ADR-0019** documenting the late-stage runtime decisions:
   inline-pipeline pattern, CSS `:has()` for recording state,
   length-band compression, audio_input-as-button architecture.

4. **Verify the museum-kiosk launch path on the current clone** and document an
   OS-neutral version in `docs/guides/GUIDE-firstrun.md`; fix `End Point.txt`'s
   hard-coded path.

5. **Decide PLAN-0002's fate** — build the text web chat, or formally retire it
   in favour of the voice kiosk.

6. **Decide on `claude-harness-public/` integration** — adopt its validation
   scripts for the docs pipeline, wire up a module, or leave it as vendored
   reference.

7. **Manual run of the offline fallback** (`faster-whisper` + Piper) to confirm
   ADR-0006/0007 still work or formally retire them.

---

## 12. ACTIVE TIMEFRAME

**Original work spanned: 2026-05-15 to 2026-05-31.**

Sequenced milestones:

- **2026-05-15** — first Claude Code handover.
- **2026-05-16** — corpus generator (Phase 1), topic map + paths
  (Phase 2), voice card (Phase 3).
- **mid-May** — PLAN-then-WRITE session: 6 ADRs (0011-0016), 5
  lessons (LL-006-010), 7 plans, 6 test specs, 5 guides.
- **2026-05-26** — third handover snapshot; ADR-0017 (end-user UI = Streamlit) and
  ADR-0018 (OpenAI STT/TTS, push-to-talk) accepted; smoke test executed.
- **2026-05-27 → 2026-05-31** — iterative UI hardening on
  `app/app.py` (15+ fix-up commits); response-compression and
  harness vendoring closed out (`0cc6be9`).

**After 2026-05-31 (now being retracted):** wake-word integration (PLAN-0008) was
built on `main` (HEAD `c76a9aa`), then reverted on this branch (`6858369`). This
reconciled handover is dated **2026-06-21** and supersedes the 2026-05-31 original.

---

## 13. RECONCILIATION CHANGELOG (what changed vs the 2026-05-31 original)

This edition was checked claim-by-claim against the live `pre-wake-word-integration`
branch. The original was found substantially accurate — no false "done" claims. The
changes made:

1. **Added §0 migration/retraction note** — wake-word (PLAN-0008) is retracted; this
   branch is the source of truth; do not merge `main`.
2. **Rewrote §10 GIT STATE** — was `main` @ `0cc6be9` "only branch"; now
   `pre-wake-word-integration` @ `6858369`, with `main` flagged as ahead with the
   retracted feature.
3. **Updated run paths** (§7, §11) from `C:\Users\ASUS\Projects\...` to
   `C:\Reachy Mini Project 2026`; flagged that the repo's `End Point.txt` still
   hard-codes the old path.
4. **Flagged PLAN-0006 doc staleness** (§2, §9) — the plan doc still names
   Piper/Whisper and omits ADR-0018; the *code* and ADR-0018 are the truth. (The
   handover's own voice-stack description was already correct.)
5. **Clarified PLAN-0002** (§5, §9) — it is a *text* web chat, specced (ADR-0017)
   but unbuilt, and distinct from the shipped voice kiosk; added the open product
   question of whether to build or retire it.
6. **Added reconciliation cautions** (§6) on GC001/PLAN-0004 (source staged, not
   ingested) and the absent PLAN-0005 book corpus, so neither is mistaken for a
   shipped feature.

**Confirmed correct and left unchanged:** the voice-stack ADR references
(ADR-0017 = Streamlit UI, ADR-0018 = OpenAI STT/TTS, ADR-0006/0007 = offline
fallback), the feature status of PLAN-0001 / PLAN-0007 / kiosk / dashboard / caching,
and the corpus/runtime architecture.
