# Filler pool PROPOSAL — CJ-authentic, answer-agnostic — 2026-07-18

**Dev0 picks the final 13 (10 ack + 3 bridge).** Then the ~$0.04 onyx synthesis runs **on approval**.
NOT synthesized here. SAPI stand-ins may be generated $0 for timing tests only, never for demo audio.

**Hard filter applied to every candidate:** (a) answer-agnostic — sits naturally before an ANSWER,
a GAP decline, a legal deflect, OR an OOS decline; no topical content; **signature THEMES
(liberty/prosperity, twin beacons, justice/jobs) DISQUALIFIED**; (b) 4–12 words, ~1.5–3s; (c)
attested in corpus (cite doc_id) or a light natural adaptation (flagged).

Mined from the curated spoken corpus (speeches first) + the Voice-Card "Voice fingerprint" section.
"In my humble opinion" (his top epistemic, SA020) is **excluded** — it commits to giving an opinion,
so it jars before a GAP/OOS decline.

## Acknowledgments (stage-1 — play at transcript-confirm)
| # | Candidate | Source | V/A | ~sec | Register note |
|---|---|---|---|---|---|
| 1 | "Permit me a moment." | SC080 ("Permit me, however…") | ADAPTED | 1.8 | Dignified, formal beat-buyer; pure CJ |
| 2 | "Allow me a moment to reflect." | SA015 ("Allow me…") | ADAPTED | 2.3 | Courtly; fits any response type |
| 3 | "Let me say this." | SA019 ("Let me say…") | ADAPTED | 1.5 | Short, neutral lead-in |
| 4 | "Let me tell you candidly." | SA126 ("let me tell you very candidly") | ADAPTED | 2.0 | Warm, characteristic frankness |
| 5 | "If I may be allowed a moment." | SA114 ("if I may be allowed") | ADAPTED | 2.5 | Formal deference; very CJ |
| 6 | "Well, let me consider that." | natural | ADAPTED | 2.0 | Conversational beat; register-safe |
| 7 | "Ah — a moment, please." | natural | ADAPTED | 1.8 | Thinking-aloud opener |
| 8 | "Let me gather my thoughts." | natural | ADAPTED | 2.0 | Neutral, gentle |
| 9 | "Hmm, let me reflect on that." | natural | ADAPTED | 2.2 | Contemplative |
| 10 | "One moment, if you please." | natural | ADAPTED | 2.0 | Formal courtesy ("if you please" = his register) |
| 11 | "Now, let me see." | natural | ADAPTED | 1.5 | Brief thinking beat |

## Bridges (stage-2 — play only if content isn't ready when the ack ends; mid-thought continuation)
| # | Candidate | Source | V/A | ~sec | Register note |
|---|---|---|---|---|---|
| 12 | "If I may add…" | SA138 ("If I may add") | **VERBATIM** | 1.5 | Perfect continuation; attested |
| 13 | "Let me put it this way." | natural | ADAPTED | 1.8 | Reframing bridge; sits mid-thought |
| 14 | "Yes… let me continue." | natural | ADAPTED | 1.6 | Neutral continuation |

## Spares (register-risk flagged — Dev0's call)
| # | Candidate | Source | V/A | ~sec | Register note |
|---|---|---|---|---|---|
| 15 | "With due respect—" | SA095 (his column title/signature) | **VERBATIM** | 1.5 | Iconic, but may read as opening a *rebuttal* → risk before a plain answer |
| 16 | "You know…" | speeches (multiple) | **VERBATIM** | 1.2 | Attested but informal; below his dignified spoken register |

## Notes for synthesis (on approval)
- Voice = **onyx** (demo default); pool is **per-voice** (`assets/filler_clips/<voice>/`). Any 2nd
  voice = a separate ~$0.04 tts-1 pass (held).
- Bridges should be **audibly "mid-thought"** (no full-stop finality) so content can enter cleanly
  after them at a clip boundary.
- Re-measure spoken seconds from the real onyx clips → set `FILLER_ACK_SECONDS` per the ack median.
