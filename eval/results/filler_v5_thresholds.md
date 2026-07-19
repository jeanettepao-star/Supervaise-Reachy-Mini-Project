# FILLER v5 — threshold derivations (THEME_CONF_THRESHOLD + TOPIC_MARGIN_THRESHOLD)

Evidence: [filler_v5_route_bands.json](filler_v5_route_bands.json) — the local router
(bge-base + 34 centroids, **$0, no API**) run over the frozen-40 gold set
(`gold_reference_set.csv`): 34 in-scope, 2 meta (X31/X32), 2 out-of-domain strays
(X35 weather / X36 restaurant), 2 gap. Recorded per query: top-topic cosine (theme
confidence), runner-up cosine, and the CLEAN margin (top minus best NON-fallback
runner-up).

## 1. THEME_CONF_THRESHOLD = 0.51 (theme gate, on top-topic cosine)

| band | n | min | p25 | p50 | p75 | max |
|---|---|---|---|---|---|---|
| **in-scope** | 34 | **0.4904** | 0.5711 | 0.6016 | 0.6225 | 0.6864 |
| out stray (X35/X36) | 2 | 0.4611 | — | 0.4841 | — | **0.5072** |
| meta (X31/X32) | 2 | 0.4865 | — | 0.4903 | — | 0.4942 |
| gap | 2 | 0.5564 | — | 0.5736 | — | 0.5907 |

**The bands OVERLAP.** The weather stray (X35, 0.5072) scores *above* two genuine
in-scope queries (C18 "most proud of" 0.4904, E29 "Data Privacy Act" 0.5025). No cut
cleanly separates in-scope from strays — this is the same signal the project already
established (W3.7: the centroid cosine cannot separate OOS from in-scope; the composer
owns the real OOS decline).

**0.51 is the least-bad cut** — just above the highest stray (0.5072):
- **Sends all 4 strays/meta to NEUTRAL:** X35 (0.5072), X36 (0.4611), X31 (0.4865,
  also caught by the identity input-gate), X32 (0.4942). ✔
- **Cost: 2 of 34 in-scope → NEUTRAL** (C18 0.4904, E29 0.5025) — they still answer
  correctly, just with a generic opener instead of a themed one. D23 (0.5108) is kept.
- **Backstop:** any stray that clears the gate still hits the composer's OUT-OF-DOMAIN
  decline (NEW-4b/OOS), so a mis-themed clip on an OOS question is a cosmetic cost, not
  a correctness one.

Layered NEUTRAL triggers (belt-and-suspenders, so the cut isn't the only defense):
identity/empty **input-gate** → NEUTRAL; **theme_anchor == META** → NEUTRAL always;
**not in_scope** (`OUT_OF_SCOPE_THRESHOLD` 0.15) → NEUTRAL; **late route** (> 300 ms) →
NEUTRAL. GAP-leaning is only knowable post-compose, so at filler-time it collapses into
the confidence gate (the composer still owns the GAP decline).

## 2. TOPIC_MARGIN_THRESHOLD = 0.01 (topic gate, on the CLEAN margin)

Raw top-minus-runner-up is **degenerate** — in-scope p50 = 0.004 — because the two
gmean-fallback centroids (`honors_received`, `robot_identity_meta` = corpus mean) sit
near every query and keep grabbing the runner-up slot (e.g. A5 top vs runner-up =
constitutional_doctrine vs honors_received, raw margin 0.0012). So the margin is
computed against the best **non-fallback** runner-up (the CLEAN margin):

| band | n | min | p25 | p50 | p75 | max |
|---|---|---|---|---|---|---|
| **in-scope (clean)** | 34 | 0.0004 | 0.0025 | 0.006 | **0.0094** | 0.0301 |
| out stray (clean) | 2 | 0.0001 | — | 0.0002 | — | 0.0002 |
| meta (clean) | 2 | 0.0033 | — | 0.0061 | — | 0.0089 |

**0.01 ≈ the in-scope clean-margin p75.** The topic clip (Filler 2) fires only on the
~20 % most-separated in-scope queries (clean margin ≥ 0.01 → ~7/34: X38, D20, A6, B11,
B9, E25, X34); the near-tie majority stays **SILENT** — "never name a coin-flip topic."
Strays (0.0001–0.0002) are far below → always silent. The topic gate *also* requires
`speakable == YES` (topic_display_names.json, post Part D) and content-not-yet-buffered,
so the effective topic fire-rate is lower still.

## 3. Residuals (accepted)

- `honors_received` and `robot_identity_meta` route their TOP to a fallback centroid on
  a few queries (A2/E30 → honors_received theme C; A3 → robot_identity_meta → NEUTRAL).
  Per task A.2, `robot_identity_meta` → NEUTRAL always; `honors_received` gets no
  special-case — so A2/E30 get a (generic) Theme-C clip. The answer is unaffected
  (retrieval biases, never gates); the mis-themed clip is cosmetic.
- The 2 in-scope false-NEUTRALs (C18, E29) are the documented cost of the 0.51 cut.

Config: `config.THEME_CONF_THRESHOLD`, `config.TOPIC_MARGIN_THRESHOLD`,
`config.FILLER_ROUTE_WAIT_MS`. Both thresholds are env-overridable for re-tuning when
the taxonomy heals (OPS-3) or the robot's on-device router changes the cosine scale.
