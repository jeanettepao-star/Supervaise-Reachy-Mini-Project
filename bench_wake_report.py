"""WAKE-LIVE-1 — score the wake bench CSV(s) against the acceptance targets.

Reads one or more evidence/wake_bench_*.csv (from bench_wake_tuning.py), prints and
writes evidence/wake_bench_summary_<date>.md:
  * per speaker x distance: attempts, hits, hit-rate %
  * soak: total utterances, false accepts (count + verbatim transcripts)
  * missed transcripts: raw STT from FAILED wake attempts, deduped, freq-sorted
    (the input for a SEPARATE, reviewed variant-list addition — not done here)
  * PASS / FAIL / INSUFFICIENT DATA verdict against the targets below.

Run:  python bench_wake_report.py                       # globs evidence/wake_bench_*.csv
      python bench_wake_report.py evidence/wake_bench_2026-07-24.csv
"""
from __future__ import annotations

import argparse
import csv
import glob
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

try:                                    # console-safe unicode (Windows cp1252 chokes on ≥/×)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---- acceptance targets (the verdict logic) ----
NEAR_TARGET = 0.90        # wake success per speaker at ~1m
FAR_TARGET = 0.80         # wake success per speaker at ~2-3m
SOAK_MIN_MINUTES = 15.0   # false-accept soak length
SOAK_MAX_FALSE = 0        # zero false wakes
MIN_SPEAKERS = 3
MIN_NEAR = 10             # near attempts per speaker
MIN_FAR = 5               # far attempts per speaker


def load_rows(paths: list[str]) -> list[dict]:
    rows: list[dict] = []
    for p in paths:
        with open(p, encoding="utf-8-sig", newline="") as f:   # utf-8-sig round-trip
            rows.extend(csv.DictReader(f))
    return rows


def _rate(hits: int, attempts: int) -> float:
    return (hits / attempts) if attempts else 0.0


def _soak_minutes(soak: list[dict]) -> float:
    ts = []
    for r in soak:
        try:
            ts.append(datetime.fromisoformat(r["timestamp"]))
        except Exception:
            pass
    return ((max(ts) - min(ts)).total_seconds() / 60.0) if len(ts) >= 2 else 0.0


def build_report(rows: list[dict]) -> str:
    wake = [r for r in rows if r.get("mode") in ("wake", "simulate")]
    soak = [r for r in rows if r.get("mode") == "soak"]

    # per speaker x distance
    grp: dict = defaultdict(lambda: {"attempts": 0, "hits": 0})
    for r in wake:
        g = grp[(r.get("speaker", "?"), r.get("distance", "?"))]
        g["attempts"] += 1
        g["hits"] += 1 if r.get("wake_fired") == "Y" else 0

    speakers = sorted({r.get("speaker", "?") for r in wake})
    L = []
    L.append(f"# Wake-word live bench — summary ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    L.append("")
    L.append(f"Rows: {len(rows)} ({len(wake)} wake/sim attempts, {len(soak)} soak utterances) · "
             f"speakers: {', '.join(speakers) or '—'}")
    L.append("")
    L.append("## Wake success — speaker × distance")
    L.append("")
    L.append("| Speaker | Distance | Attempts | Hits | Hit-rate | Target | Meets |")
    L.append("|---|---|--:|--:|--:|--:|:--:|")

    def near(sp): return grp.get((sp, "near"), {"attempts": 0, "hits": 0})
    def far(sp):  return grp.get((sp, "far"), {"attempts": 0, "hits": 0})

    for sp in speakers:
        for dist, tgt in (("near", NEAR_TARGET), ("far", FAR_TARGET)):
            g = grp.get((sp, dist))
            if not g:
                continue
            rate = _rate(g["hits"], g["attempts"])
            meets = "✓" if (g["attempts"] and rate >= tgt) else "✗"
            L.append(f"| {sp} | {dist} | {g['attempts']} | {g['hits']} | {rate*100:.1f}% | "
                     f"≥{tgt*100:.0f}% | {meets} |")

    # soak
    L.append("")
    L.append("## False-accept soak")
    L.append("")
    false_rows = [r for r in soak if r.get("false_accept") == "Y" or r.get("wake_fired") == "Y"]
    soak_min = _soak_minutes(soak)
    L.append(f"- utterances: **{len(soak)}** over **{soak_min:.1f} min** "
             f"(target ≥ {SOAK_MIN_MINUTES:.0f} min)")
    L.append(f"- false accepts: **{len(false_rows)}** (target {SOAK_MAX_FALSE})")
    if false_rows:
        L.append("- offending transcripts (verbatim):")
        for r in false_rows:
            L.append(f"    - {r.get('transcript','')!r} → {r.get('matched_variant','')}")

    # missed transcripts (input for a separate reviewed variant addition)
    missed = Counter(r.get("transcript", "") for r in wake if r.get("wake_fired") == "N")
    L.append("")
    L.append("## Missed transcripts (failed wake attempts — candidates for a *reviewed* variant add)")
    L.append("")
    if missed:
        L.append("| # | Raw STT transcript |")
        L.append("|--:|---|")
        for txt, n in missed.most_common():
            L.append(f"| {n} | {txt!r} |")
    else:
        L.append("_none_")

    # ---- verdict ----
    L.append("")
    L.append("## Verdict")
    L.append("")
    real_speakers = [sp for sp in speakers if sp not in ("sim",)]
    insufficient = []
    if len(real_speakers) < MIN_SPEAKERS:
        insufficient.append(f"only {len(real_speakers)} speaker(s), need ≥ {MIN_SPEAKERS}")
    for sp in real_speakers:
        if near(sp)["attempts"] < MIN_NEAR:
            insufficient.append(f"{sp}: {near(sp)['attempts']} near attempts, need ≥ {MIN_NEAR}")
        if far(sp)["attempts"] < MIN_FAR:
            insufficient.append(f"{sp}: {far(sp)['attempts']} far attempts, need ≥ {MIN_FAR}")

    if insufficient:
        L.append("**INSUFFICIENT DATA** — not enough to PASS:")
        for m in insufficient:
            L.append(f"- {m}")
        return "\n".join(L) + "\n"

    fails = []
    for sp in real_speakers:
        if _rate(near(sp)["hits"], near(sp)["attempts"]) < NEAR_TARGET:
            fails.append(f"{sp} near {_rate(near(sp)['hits'], near(sp)['attempts'])*100:.1f}% < {NEAR_TARGET*100:.0f}%")
        if _rate(far(sp)["hits"], far(sp)["attempts"]) < FAR_TARGET:
            fails.append(f"{sp} far {_rate(far(sp)['hits'], far(sp)['attempts'])*100:.1f}% < {FAR_TARGET*100:.0f}%")
    soak_ok = (len(false_rows) <= SOAK_MAX_FALSE) and (soak_min >= SOAK_MIN_MINUTES)
    if not soak_ok:
        fails.append(f"soak: {len(false_rows)} false / {soak_min:.1f} min "
                     f"(need {SOAK_MAX_FALSE} false over ≥ {SOAK_MIN_MINUTES:.0f} min)")

    if fails:
        L.append("**FAIL** —")
        for m in fails:
            L.append(f"- {m}")
    else:
        L.append(f"**PASS** — all {len(real_speakers)} speakers meet near ≥ {NEAR_TARGET*100:.0f}% "
                 f"/ far ≥ {FAR_TARGET*100:.0f}%; soak {len(false_rows)} false over {soak_min:.1f} min.")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Score wake bench CSV(s) vs acceptance targets.")
    ap.add_argument("csvs", nargs="*", help="wake_bench CSV(s); default globs evidence/wake_bench_*.csv")
    ap.add_argument("--outdir", default="evidence", help="where to write the summary .md")
    args = ap.parse_args(argv)

    paths = args.csvs or sorted(glob.glob(str(Path(args.outdir) / "wake_bench_*.csv")))
    paths = [p for p in paths if "summary" not in Path(p).name]
    if not paths:
        print(f"no wake_bench CSVs found in {args.outdir}/ (run bench_wake_tuning.py first)")
        return 2
    rows = load_rows(paths)
    report = build_report(rows)
    print(report)
    out = Path(args.outdir) / f"wake_bench_summary_{datetime.now().strftime('%Y-%m-%d')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"[report] wrote {out}  (from {len(paths)} csv file(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
