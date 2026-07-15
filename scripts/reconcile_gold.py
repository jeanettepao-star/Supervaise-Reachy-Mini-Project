"""
GOLD-SET RECONCILIATION — diff Sheena's authoritative v4 copy vs the repaired
repo gold, restore lost NON-GRADING cells, verify, and write the incident-closure
note. $0, no API. Content-aware only (CRLF-normalized); never numstat.

BLOCKED until Dev0 places: eval/results/incoming/gold_reference_set_SHEENA.csv
Expected fingerprint: raw sha256 453a6d28... | CRLF-normalized sha256 b08962e5...
40 rows / 17 cols; A4=CA377, E28=CE007, X33=GAP/in(gap-v4); in=34/meta=2/out=2/gap=2.

Usage:  python scripts/reconcile_gold.py           # dry-run (diff + report only)
        python scripts/reconcile_gold.py --apply   # restore at-risk cells + note
"""
from __future__ import annotations
import csv, hashlib, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT / "eval" / "results" / "gold_reference_set.csv"
AUTH = ROOT / "eval" / "results" / "incoming" / "gold_reference_set_SHEENA.csv"
NOTE = ROOT / "eval" / "results" / "gold_incident_reconciliation.md"

GRADING = ["qid", "scope_gold", "gold_source_docs", "gold_confidence", "qtype", "stakes",
           "theme", "gold_frozen_subset", "gold_change_v4"]
AT_RISK = ["gold_titles", "gold_grounding_summary", "model_answer", "review_status"]
NEUTRAL = ["query", "routed_topic", "retrieved_docs", "high_stakes_fact"]
EXPECT_RAW, EXPECT_NORM = "453a6d28", "b08962e5"
EXPECT_COLHASH = {"gold_titles": "a9b44310", "gold_grounding_summary": "fc38ef90",
                  "model_answer": "51b576b1", "review_status": "ee01e226"}


def col_hash(rows, col):
    """Documented recipe: sha256 over 'qid=cell' lines, qid-sorted, utf-8, LF-joined."""
    blob = "\n".join(f"{r['qid']}={r.get(col, '')}" for r in sorted(rows, key=lambda r: r["qid"]))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def main():
    apply = "--apply" in sys.argv
    if not AUTH.exists():
        print(f"BLOCKED: {AUTH.relative_to(ROOT)} not present. Ask Dev0 to place Sheena's file there.",
              file=sys.stderr)
        return 2

    # ---- fingerprint gate ----
    raw = AUTH.read_bytes()
    raw_sha = hashlib.sha256(raw).hexdigest()
    norm_sha = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
    A = list(csv.DictReader(open(AUTH, encoding="utf-8-sig")))
    Ad = {r["qid"]: r for r in A}
    checks = {
        "raw_sha_453a6d28": raw_sha.startswith(EXPECT_RAW),
        "norm_sha_b08962e5": norm_sha.startswith(EXPECT_NORM),
        "rows_40": len(A) == 40, "cols_17": len(A[0]) == 17,
        "A4_CA377": Ad.get("A4", {}).get("gold_source_docs") == "CA377",
        "E28_CE007": Ad.get("E28", {}).get("gold_source_docs") == "CE007",
        "X33_gap": Ad.get("X33", {}).get("gold_source_docs") == "GAP"
                   and Ad.get("X33", {}).get("scope_gold") == "in(gap-v4)",
        "scope_counts": sorted((r["scope_gold"] for r in A)) is not None and
                        {s: sum(1 for r in A if r["scope_gold"] == s) for s in set(r["scope_gold"] for r in A)}
                        .get("in") == 34,
    }
    print("[fingerprint]", {k: v for k, v in checks.items()})
    print(f"  raw={raw_sha[:8]} norm={norm_sha[:8]}")
    if not all(checks.values()):
        print("STOP — wrong file (fingerprint failed).", file=sys.stderr)
        return 2

    R = list(csv.DictReader(open(REPO, encoding="utf-8-sig")))
    Rd = {r["qid"]: r for r in R}
    fields = list(R[0].keys())
    assert set(Ad) == set(Rd), "qid sets differ — STOP"

    # ---- 3-class cell diff ----
    def diff_cols(cols):
        out = []
        for qid in sorted(Rd):
            for c in cols:
                if (Rd[qid].get(c, "") or "").strip() != (Ad[qid].get(c, "") or "").strip():
                    out.append({"qid": qid, "col": c,
                                "repo": (Rd[qid].get(c, "") or "")[:80],
                                "authoritative": (Ad[qid].get(c, "") or "")[:80]})
        return out
    grading_diffs = diff_cols([c for c in GRADING if c in fields])
    atrisk_diffs = diff_cols([c for c in AT_RISK if c in fields])
    neutral_diffs = diff_cols([c for c in NEUTRAL if c in fields])
    print(f"[diff] grading={len(grading_diffs)} at-risk cells={len(atrisk_diffs)} neutral={len(neutral_diffs)}")
    if grading_diffs:
        print("*** GRADING columns differ — NEW FINDING, NOT auto-fixed (canonical scorecard was "
              "computed against the repo's grading columns): ***")
        for d in grading_diffs:
            print("  ", d)

    if not apply:
        print("[dry-run] pass --apply to restore at-risk cells + write the note.")
        return 0

    # ---- restore at-risk cells from authoritative ----
    for d in atrisk_diffs:
        Rd[d["qid"]][d["col"]] = Ad[d["qid"]][d["col"]]
    with open(REPO, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields); w.writeheader()
        for r in R:
            w.writerow(r)

    # ---- verify: N=34, corrections intact, column hashes match authoritative ----
    R2 = list(csv.DictReader(open(REPO, encoding="utf-8-sig")))
    R2d = {r["qid"]: r for r in R2}
    assert sum(1 for r in R2 if r["scope_gold"] == "in") == 34
    assert R2d["A4"]["gold_source_docs"] == "CA377" and R2d["E28"]["gold_source_docs"] == "CE007"
    assert R2d["X33"]["gold_source_docs"] == "GAP"
    hashes = {}
    for c in AT_RISK:
        if c in fields:
            h_repo, h_auth = col_hash(R2, c), col_hash(A, c)
            hashes[c] = {"repo": h_repo[:8], "authoritative": h_auth[:8], "files_match": h_repo == h_auth,
                         "expected_prefix": EXPECT_COLHASH.get(c),
                         "matches_expected_prefix": h_auth.startswith(EXPECT_COLHASH.get(c, "~"))}
    print("[verify] column hashes:", json.dumps(hashes, indent=1))

    # ---- $0 regrade sanity: recall@1/@5 must not move ----
    SENT = {"OOS", "META", "GAP"}
    canon = json.loads((ROOT / "eval/results/w3_2_REGRADE_v3_v4gold.json").read_text(encoding="utf-8"))
    rd_map = {r["qid"]: r["retrieved_docs"] for r in canon["per_query"]}
    insc = [r for r in R2 if r["scope_gold"] == "in"]
    def hit(r, k):
        gd = [x.strip() for x in r["gold_source_docs"].split(";") if x.strip() and x.strip() not in SENT]
        return any(d in gd for d in rd_map[r["qid"]][:k])
    r1 = round(sum(1 for r in insc if hit(r, 1)) / len(insc), 3)
    r5 = round(sum(1 for r in insc if hit(r, 5)) / len(insc), 3)
    print(f"[sanity] regrade recall@1={r1} (expect 0.735) recall@5={r5} (expect 0.971)")
    if (r1, r5) != (0.735, 0.971):
        print("STOP — recall moved: a grading column changed.", file=sys.stderr)
        return 3

    # ---- reconciliation note ----
    residual = "CLOSED" if not grading_diffs else "OPEN — grading columns divergent (see list)"
    NOTE.write_text(f"""# Gold Incident Reconciliation — round-2 checkout regression

Date: {datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')}
Authoritative: incoming/gold_reference_set_SHEENA.csv (raw {raw_sha[:8]}, norm {norm_sha[:8]})

## What differed
- GRADING columns: {len(grading_diffs)} diffs {'(NONE — repair from e18e1d1 was complete)' if not grading_diffs else json.dumps(grading_diffs, ensure_ascii=False)}
- AT-RISK cells restored from authoritative: {len(atrisk_diffs)}
{chr(10).join(f"  - {d['qid']}.{d['col']}" for d in atrisk_diffs) or '  - none'}
- NEUTRAL diffs (reported, not auto-overwritten): {len(neutral_diffs)}
{chr(10).join(f"  - {d['qid']}.{d['col']}: repo={d['repo']!r} vs auth={d['authoritative']!r}" for d in neutral_diffs) or '  - none'}

## Verification
- Column hashes (recipe: sha256 over qid-sorted 'qid=cell' lines):
{json.dumps(hashes, indent=2)}
- N=34, A4/E28/X33 corrections intact, scope counts unchanged.
- $0 regrade sanity: recall@1={r1}, recall@5={r5} — unchanged.

## Incident residual risk: **{residual}**
""", encoding="utf-8")
    print(f"[note] wrote {NOTE.relative_to(ROOT)} | residual: {residual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
