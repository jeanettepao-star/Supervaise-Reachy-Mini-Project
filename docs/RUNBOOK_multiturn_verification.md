# RUNBOOK — Live-Browser Verification, Filler v5 (Phase 2 + 2c)

**Audience:** operator at the demo machine (Dev0/Dok). **Time:** ~15 min · **one uninterrupted browser session.**
**Why:** headless testing cannot see the multi-turn audio-death class or measure true audible latency. This
runbook closes the gates left open by `filler_v5_phase2c_bisect_2026-07-24.md` and `filler_v5_reattest2_2026-07-24.md`:
(1) multi-turn audio survival, (2) mid-session-rerun recovery, (3) the real audible Felt-TTFA. Hand the
filled-in results to Dev0 for the W3.5 FINAL.

Related: [filler_v5_phase2c_bisect_2026-07-24.md](../eval/results/filler_v5_phase2c_bisect_2026-07-24.md) ·
[filler_v5_reattest2_2026-07-24.md](../eval/results/filler_v5_reattest2_2026-07-24.md) · transport: [RUNBOOK_transport.md](RUNBOOK_transport.md)

> ⚠️ Do **not** reload the page or restart Streamlit during Tests A–D. A reload resets the very state under
> test and voids the run. Re-attestation must be **8+ consecutive turns, one session, no reloads.**

---

## 0 · Pre-flight
- [ ] On `develop` at `ec79e65` or later: `git log --oneline -1`
- [ ] Clips present: `ls assets/filler_clips/onyx/neutral/` shows **10** `.mp3`.
      If empty (fresh clone — clips are gitignored, regenerated locally): `python scripts/gen_v5_subject_free_clips.py --all`
- [ ] Keys in `app/.env` (ANTHROPIC + OPENAI); Avast Service-host profile active (HTTPS scanning OFF → native TLS).
- [ ] Launch: `streamlit run streamlit_voice_demo.py --server.headless false`
- [ ] Open **browser DevTools → Console** (F12); leave it open the whole session.
- [ ] Page loads; click **"🔊 Enable audio"** once (or confirm "Audio enabled"). Sidebar → Mode = **DEMO (auto-submit)**, voice = **onyx**.

## 1 · Test A — Multi-turn audio survival  *(the Phase-2c acceptance gate)*
Ask **8+ questions in a row**, same session, letting each answer finish first. Suggested set: foundation for
liberty & prosperity · your book With Due Respect · rule of law · your recognitions · ICC and Duterte · the
Foundation's mission · judicial reform · due process.

- [ ] T1 ☐  T2 ☐  T3 ☐  T4 ☐  T5 ☐  T6 ☐  T7 ☐  T8 ☐  — a **spoken opener + answer** on each?
- **PASS** = audio on **every** turn. **FAIL** = audio goes silent after turn 1–2 (the original regression) →
  stop, capture the console (Test F), report to Dev0. The fix did not hold.

## 2 · Test B — Mid-session-rerun kill-test  *(the base-clamp recovery)*
Same session, after ~turn 3:
- [ ] Trigger a benign rerun: change the sidebar **voice** to `nova` then back to `onyx` (or toggle Mode).
- [ ] Ask **one more question**.
- **PASS** = audio still plays. **FAIL** = silence after the widget change → remount-recovery isn't firing; capture console + report.
- [ ] (Optional, stronger) DevTools Console before/after: `document.querySelectorAll('iframe').length` — the count must not climb (the player iframe must not multiply).

## 3 · Test C — Audible Felt-TTFA capture  *(fills the KPI gap — the H-B correction owed since Phase 1)*
Open `eval/results/voice_demo_log.csv` (the rows you just made). New columns:
- [ ] `audible_onset_observable` = **True** on the rows?  ☐ yes ☐ no
  - **yes** → record `t_filler1_audible_s` per turn; compute **median (p50)**: ______ s.  **PASS** = p50 ≤ **1.0 s**.
  - **no** (postback not landing) → **stopwatch fallback (R-28)**, 3 turns: start a phone stopwatch the instant
    the **"STT heard: …"** caption appears; stop it the instant you **first hear the CJ voice**.
    T1 ___ s · T2 ___ s · T3 ___ s. Note in the report: stopwatch, `audible_onset_observable:false`.
- [ ] Sanity: `t_filler_fire_call_s` ≈ 0.005 s and `fire_mode` = `unconditional` on every row.

## 4 · Test D — Dead-air watchdog stayed silent
Same CSV rows:
- [ ] `deadair_watchdog_fired` = **False** on all normal turns? **PASS** = all False. Any **True** = the
  unconditional fire failed on that turn — record the turn + its `chain_pattern` (a finding to investigate;
  not a demo-blocker, audio still played via the watchdog).

## 5 · Test E — Rollback drill  *(demo-week lever)*
- [ ] Stop Streamlit. Relaunch with gated mode (PowerShell): `$env:CJ_FILLER_FIRE_MODE="gated"; streamlit run streamlit_voice_demo.py --server.headless false`
- [ ] Ask **one** question → still get a spoken filler + answer (legacy path). **PASS** = yes.
- [ ] `Remove-Item Env:\CJ_FILLER_FIRE_MODE` (or relaunch fresh) to return to `unconditional` for the demo.

## 6 · Test F — Browser console (capture if anything looks off)
Across the session, screenshot any of:
- [ ] `AudioContext was not allowed to start` / `suspended` warnings
- [ ] repeated `gapless_audio` component load / iframe remount messages
- [ ] any red JS errors
- **Clean console** (no repeated remounts, no persistent suspended-context warning) supports the fix.

## 7 · Hand to Dev0
- [ ] Attach this session's `voice_demo_log.csv` rows (or the stopwatch table).

| Test | Result |
|---|---|
| A · 8-turn audio survival | ☐ PASS ☐ FAIL (silent after turn __) |
| B · mid-session-rerun recovery | ☐ PASS ☐ FAIL |
| C · audible Felt-TTFA p50 | ____ s (☐ logged ☐ stopwatch) — ☐ ≤ 1.0 s |
| D · watchdog silent | ☐ PASS (all False) ☐ fired on turn __ |
| E · gated rollback | ☐ PASS ☐ FAIL |

- [ ] Only if **A and B pass and C ≤ 1.0 s**: Dev0 may amend the W3.5 Felt-TTFA line to the **audible** number,
  basis noted. Otherwise hold the KPI and report the failure.

---

**Notes.** Tests A + B are the real acceptance gate for the Phase-2c browser fix — everything committed in
`d54a19e` is *unverified* until they pass live. Test C is what finally replaces the enqueue-basis KPI with a
true audible number. `.mp3` clips are gitignored by repo policy (regenerated via `scripts/gen_v5_subject_free_clips.py`),
so a fresh demo-bench clone must run that script once before Pre-flight.

*New columns written by the fix (`voice_demo_log.csv`): `fire_mode`, `t_filler_fire_call_s`, `deadair_watchdog_fired`,
`t_filler1_audible_s`, `t_first_content_audible_s`, `audible_onset_observable`. Full per-turn telemetry also lands in
`eval/results/filler_v5_trace_2026-07-24.jsonl`.*
