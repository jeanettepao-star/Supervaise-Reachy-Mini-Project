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

---

# §extenders — Filler v3.1 CJ-attested extender candidates (2026-07-18)

**Dev0 picks 3-4;** then ~$0.01 onyx synthesis + hot-swap (role files only, sequencer untouched).
The 3 scripted extenders stay LIVE until replacements are approved. Stricter role test than
openers: must work as the **2nd/3rd** thing said **while still thinking** — cannot imply speech
occurred, cannot commit to answering, no topical content. Band **1.5–2.5 s** (keeps the sizing math).

Corpus is sparse on hesitation phrases (CJ's prose is polished), so most are ADAPTED in his register;
the one strong attestation anchors them.

| # | Candidate | Source | V/A | ~sec | Role-fit note |
|---|---|---|---|---|---|
| E1 | "Let me take a moment more." | SB028 ("let me just take a few more minutes of your time") | ADAPTED | 1.6 | Attested time-request, stripped of its topical tail; pure extend |
| E2 | "A few moments more, if you please." | SB028 + his "if you please" register | ADAPTED | 2.1 | Courtly patience-ask |
| E3 | "Bear with me a moment." | natural | ADAPTED | 1.5 | Plain patience-ask; register-safe |
| E4 | "Let me not rush this." | natural | ADAPTED | 1.5 | Signals care, no commitment |
| E5 | "Let me weigh this carefully." | "carefully" is his register (SA049) | ADAPTED | 1.8 | Thinking-in-progress; not topical |
| E6 | "Give me a moment to be precise." | natural (his careful register) | ADAPTED | 1.9 | Precision-ask, extends the pause |
| E7 | "Let me gather this properly." | natural | ADAPTED | 1.6 | Mid-thought gather, no implied speech |

**Live scripted extenders (stay until replaced):** "A moment more, please." (1.32 s) ·
"Bear with me, I want to answer this properly." (2.45 s) · "Let me be sure I have this right." (1.97 s).
