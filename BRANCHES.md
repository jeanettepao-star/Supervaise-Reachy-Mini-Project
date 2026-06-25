# BRANCHES.md — branch audit (W1.1)

Audit taken **2026-06-25** on a `git fetch --all --prune`, before any
consolidation work. No branches were deleted, rebased, or force-pushed.
This is a read-only census plus the rationale for the consolidation base.

Repo: `github.com/jeanettepao-star/Supervaise-Reachy-Mini-Project`

## ⚠ Flag — the suggested candidate base does not exist

The W1.1 brief names **`feat/topic-map-coverage`** as the "candidate clean
base to evaluate first." **That branch does not exist** — not locally, not on
`origin`, and not in the reflog. It is not a typo for any present ref. I did
not create it. The consolidation base below was therefore chosen on the
evidence actually in the repo, and the choice is justified in §"Consolidation
base."

## Branch census

All branches descend from a single common ancestor,
`6858369` (*"revert: drop wake-word scaffolding · return to push-to-talk
kiosk"*, 2026-06-05). From there the history forks into a **pre-wake-word
docs track** and a **wake-word re-integration track**.

| Branch | Tip SHA | Date | Author | Subject | Rel. to base¹ | Builds? | Purpose (inferred) | State |
|---|---|---|---|---|---|---|---|---|
| `weekly-plan-execution` (local, **= chosen base**) | `07a8b8d` | 2026-06-21 | jeanettepao-star | docs: point CLAUDE.md at reconciled 2026-06-21 handover | — | **Yes** (verified offline²) | Active working branch; reconciled pre-wake-word baseline + weekly-plan docs | **candidate-base** |
| `pre-wake-word-integration` (local) | `07a8b8d` | 2026-06-21 | jeanettepao-star | docs: point CLAUDE.md at reconciled 2026-06-21 handover | identical to chosen base (0/0) | Yes (same tree) | Same commit as `weekly-plan-execution`; ahead 2 of its own origin | candidate-base (dup) |
| `origin/pre-wake-word-integration` | `6858369` | 2026-06-05 | jeanettepao-star | revert: drop wake-word scaffolding · return to push-to-talk kiosk | base −2 (behind the local pre-wake tip) | Yes | Published pre-wake baseline before the 06-21 docs reconciliation | stale (superseded by local) |
| `origin/main` / `main` | `c76a9aa` | 2026-06-12 | jeanettepao-star | PLAN-0008 — wake-word integration complete (Task 1 + Task 2) | +5 / −2 vs chosen base | Not rebuilt this pass³ | Wake-word re-integration (openWakeWord/ONNX) declared complete | **off-track for pilot** (deferred feature) |
| `origin/integration/hands-free-wake` | `8e26061` | 2026-06-13 | jeanettepao-star | WIP: harden EOS auto-calibration in record_until_silence (untested) | +6 / −2 vs chosen base (main +1) | **No** (self-declared "untested") | Continued wake-word tuning on top of `main` | **WIP** (off-track for pilot) |

¹ "Rel. to base" = ahead/behind the chosen consolidation base
(`weekly-plan-execution` @ `07a8b8d`). `+a / −b` = a commits the branch has
that the base lacks, b commits the base has that the branch lacks.

² **Verified offline (no API key):** `cj_chat` imports cleanly, the 35-topic
`topic_map.json` + `voice_card.md` + `router_prompt.md` load, `build_context()`
assembles a ~7.6k-token grounded block, and `scripts/build_topic_map.py`
rebuilds the map content-identically (only its `generated_at` timestamp
changes). The live Claude round-trip is gated solely on `ANTHROPIC_API_KEY`.

³ The wake-word branches were **not** independently rebuilt in this pass: they
re-introduce the openWakeWord / ONNX / live-audio stack that is explicitly
**deferred** for the May-30 demo (ADR-0005; reconciled 2026-06-21 handover),
so they are out of scope for the pilot. `main`'s own commit message claims the
integration is "complete"; `integration/hands-free-wake`'s own message labels
its tip "untested." Neither is treated as validated here.

## Topology

```
6858369  revert: drop wake-word · return to push-to-talk   (origin/pre-wake-word-integration)  ← common ancestor
│
├─ 80baaa4  docs: reconciled handover 2026-06-21
│  └─ 07a8b8d  docs: point CLAUDE.md at reconciled handover   ← weekly-plan-execution / pre-wake-word-integration (CHOSEN BASE)
│
└─ a5a5adc → ebb0fee → 2864a8c → 7b617e6 → c76a9aa  PLAN-0008 wake-word complete   ← origin/main
   └─ 8e26061  WIP harden EOS (untested)                       ← origin/integration/hands-free-wake
```

## Consolidation base

**Chosen base: `weekly-plan-execution` @ `07a8b8d`** (byte-identical to local
`pre-wake-word-integration`). New work branched onto **`pilot/stabilise-config`**.

Why this branch and not the others:

1. **It is the reconciled source-of-truth baseline.** The 2026-06-21 handover
   and `CLAUDE.md` both point here as "latest implementation reality
   (pre-wake-word baseline)." It is the only branch whose docs and code agree.
2. **It builds and runs offline** (see footnote ²). The candidate named in the
   brief (`feat/topic-map-coverage`) could not be evaluated because it does not
   exist; this branch was confirmed to run before being trusted.
3. **The other divergent work is out of pilot scope.** `main` and
   `integration/hands-free-wake` carry only the wake-word re-integration track,
   which is deferred for the demo (ADR-0005). Consolidating from them would pull
   a deferred feature into the pilot baseline. There is therefore **no pilot
   work to cherry-pick** from them, and **no merge was performed** — so there
   were **no merge conflicts to resolve**. (The brief's "resolve each conflict
   toward the LOCKED NEW architecture" is conditional; it does not apply because
   no branch yet contains competing architecture code — see the note below.)

## Note — "LOCKED NEW architecture" vs. what is on disk

The brief describes a locked target architecture (dimensional/centroid topic
model, in-memory numpy retrieval, RRF hybrid fusion, soft-prior topic bias with
global fallback, deterministic routing, Sonnet-for-composition). **None of that
is implemented on any branch yet.** Every branch runs the documented baseline
pipeline: a Claude **Haiku** router/​gate against a hand-curated 35-topic
taxonomy → context assembled from `topic_map.json` `doc_ids` → Claude **Sonnet**
composer → Haiku fidelity check. There is no embedding store, no numpy
retrieval, and no RRF anywhere in the tree (consistent with `CLAUDE.md`'s
"Not RAG / no embeddings").

W1.1 therefore lands the **config surface** for that future architecture
(`config.py` carries all the retrieval/fusion/centroid knobs as the single
source of truth) without yet wiring a retrieval engine that does not exist.
Those knobs are consumed starting W1.4–W1.7. See `CHANGELOG.md`.
