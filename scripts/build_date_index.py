"""
W2.4 — build the date index (ADDITIVE, idempotent, append-only). Parses a date
for every doc from corpus metadata (front-matter 'date' first; year-extraction
and title fallback next). Undated docs recorded null/none, NEVER dropped.

Writes data/index/date_index.json (doc_id -> {date_iso, precision, source_of_date})
+ data/index/date_index_provenance.json (counts, undated list, sha256, commit).
Deterministic: re-run produces a byte-identical table (idempotency gate).

Usage:  python scripts/build_date_index.py
"""
from __future__ import annotations
import glob, hashlib, json, re, subprocess, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "data" / "index" / "date_index.json"
PROV = ROOT / "data" / "index" / "date_index_provenance.json"

_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_MON = re.compile(r"^\d{4}-\d{2}$")
_ISO_YR = re.compile(r"^\d{4}$")
_YEAR = re.compile(r"(1[89]\d\d|20\d\d)")     # a real 4-digit year present in the string


def parse_date(raw, title=""):
    """Deterministic. Extracts a present date signal; never fabricates one.
    Returns (date_iso|null, precision in {day,month,year,none}, source_of_date)."""
    s = (raw or "").strip()
    if _ISO_DAY.match(s):
        return s, "day", "metadata_iso_day"
    if _ISO_MON.match(s):
        return s, "month", "metadata_iso_month"
    if _ISO_YR.match(s):
        return s, "year", "metadata_iso_year"
    m = _YEAR.search(s)                        # range '1955-1959' / decade 'mid-1980s' -> first year
    if m:
        return m.group(1), "year", "metadata_year_extracted"
    m = _YEAR.search(title or "")              # fallback: a year in the title/source
    if m:
        return m.group(1), "year", "title_year_fallback"
    return None, "none", "unparseable"         # truly dateless -> null, NOT dropped/guessed


def _git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def build():
    # doc store = the sha-pinned chunks.jsonl (source of truth for which docs exist)
    store_docs = set()
    for ln in (ROOT / "corpus/index/chunks.jsonl").read_text(encoding="utf-8").splitlines():
        if ln.strip():
            store_docs.add(json.loads(ln)["doc_id"])
    # doc-level metadata (has 'date' + 'title')
    meta = {}
    for p in glob.glob(str(ROOT / "corpus" / "**" / "*.json"), recursive=True):
        try:
            d = json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(d, dict) and d.get("id") in store_docs:
            meta[d["id"]] = d

    table = {}
    for doc_id in sorted(store_docs):                      # sorted -> deterministic
        m = meta.get(doc_id, {})
        date_iso, precision, src = parse_date(m.get("date"), m.get("title", ""))
        table[doc_id] = {"date_iso": date_iso, "precision": precision, "source_of_date": src}

    canonical = json.dumps(table, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    prec_counts = Counter(v["precision"] for v in table.values())
    by_class_prec = Counter((d[0], table[d]["precision"]) for d in table)
    undated = sorted(d for d in table if table[d]["date_iso"] is None)

    prov = {
        "artifact": "date_index.json", "n_docs": len(table), "sha256": sha,
        "git_commit": _git_commit(),
        "precision_counts": dict(prec_counts),
        "dated": sum(1 for v in table.values() if v["date_iso"]),
        "undated": len(undated), "undated_doc_ids": undated,
        "by_source_class_precision": {f"{c}:{p}": n for (c, p), n in sorted(by_class_prec.items())},
        "parser": "metadata 'date' -> ISO day/month/year | year-extract from range/decade | title fallback | null",
        "idempotent": "deterministic: sorted doc_ids + canonical json; re-run hash stable",
    }
    TABLE.write_text(json.dumps(table, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    PROV.write_text(json.dumps(prov, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"date_index: {len(table)} docs | dated {prov['dated']} | undated {prov['undated']}")
    print("precision:", dict(prec_counts))
    print("by source-class x precision:", prov["by_source_class_precision"])
    print("sha256:", sha)
    print("undated sample:", undated[:12])
    return sha


if __name__ == "__main__":
    build()
