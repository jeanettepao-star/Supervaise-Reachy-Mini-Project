"""W1.3 generator: build the v3 frozen pilot subset (95 docs, 19/theme).

Deterministic + reproducible. Reads the four normalised xlsx corpora, computes
per-theme format quotas by largest-remainder apportionment (floor 1 per present
format), raises any cell whose forced count exceeds its quota (compensating by
largest-remainder reduction elsewhere, never below floor 1), places forced docs,
then fills remaining slots by ascending Article-Code. Writes the four v3 outputs
as UTF-8-SIG.

Scratch tooling for the W1.3 freeze — not part of the runtime build pipeline.
"""
from __future__ import annotations
import openpyxl, os, re, csv, json, collections, datetime

OUT_DIR = "reports/pilot-eval subset"
FROZEN_DATE = "2026-06-26"   # passed in explicitly (no Date.now in determinism)
T = 19                        # target docs per theme

FILES = {
    "Column":    "data/csv/cjp_columns_curated_normalized.xlsx",
    "Book":      "data/csv/cjp_books_curated_normalized.xlsx",
    "Speech":    "data/csv/cjp_speeches_curated_normalized.xlsx",
    "Biography": "data/csv/cjp_biography_curated_normalized.xlsx",
}
FMT_LETTER = {"C": "Column", "B": "Book", "S": "Speech", "G": "Biography"}
THEMES = list("ABCDE")
FORMATS = ["Column", "Biography", "Book", "Speech"]
THEME_LABEL = {
    "A": "Liberty & Rule of Law",
    "B": "Prosperity & Economic Philosophy",
    "C": "Biographical & Personal",
    "D": "FLP Mission / Foundation / Judicial Reform",
    "E": "Signature Current-Events Commentary",
}
ID_RE = re.compile(r"^[CGBS][A-E]\d{3}$")

# ---- forced docs (category -> codes); CA242 & SA049 are in both -----------
AI = ["CA034","CA242","CB001","CD022","CE011","SA049","SE012","SE013"]
ORPH = ["CA242","CA060","CA377","CA330","CC069","CE072","BA027","BA009","SA049","SD035"]
# notes per forced doc (from prior version, reused for rationale text)
FORCED_NOTE = {
    "CA034": ("AI-governance", "AI in justice and governance"),
    "CA242": ("AI-governance + orphaned-topic", "right to be forgotten / data privacy (1 doc)"),
    "CB001": ("AI-governance", "AI fortifies liberty, prosperity, rule of law"),
    "CD022": ("AI-governance", "enforcing rights on surveillance capitalism"),
    "CE011": ("AI-governance", "robotics, for better or for worse"),
    "SA049": ("AI-governance + orphaned-topic", "intellectual property; jurisprudential disruption (1 doc)"),
    "SE012": ("AI-governance", "Constitution & the Running Bulls of Technology"),
    "SE013": ("AI-governance", "Three AI Takeaways"),
    "CA060": ("orphaned-topic", "indigenous peoples (1 doc)"),
    "CA377": ("orphaned-topic", "same-sex marriage (1 doc)"),
    "CA330": ("orphaned-topic", "extrajudicial killings (1 doc)"),
    "CC069": ("orphaned-topic", "surrogacy (2 docs)"),
    "CE072": ("orphaned-topic", "agrarian reform (1 doc)"),
    "BA027": ("orphaned-topic", "reproductive health / RH (1 doc)"),
    "BA009": ("orphaned-topic", "plagiarism / contempt (1 doc)"),
    "SD035": ("orphaned-topic", "climate (1 doc)"),
}

# ---- 1. read corpus -------------------------------------------------------
records = {}   # code -> {format, theme, title, keywords}
for fmt, path in FILES.items():
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    it = ws.iter_rows(values_only=True)
    header = [str(h) if h is not None else "" for h in next(it)]
    ci = header.index("Article Code"); ti = header.index("Title")
    ki = header.index("Keyword/s") if "Keyword/s" in header else None
    for row in it:
        if ci >= len(row) or row[ci] in (None, ""):
            continue
        code = str(row[ci]).strip()
        if not ID_RE.match(code) or code in records:
            continue
        records[code] = {
            "format": FMT_LETTER[code[0]], "theme": code[1],
            "title": (str(row[ti]).strip() if row[ti] is not None else ""),
            "keywords": (str(row[ki]).strip() if ki is not None and ki < len(row)
                         and row[ki] is not None else ""),
        }
    wb.close()

corpus_total = len(records)

# corpus counts per (format, theme)
corpus_cnt = collections.defaultdict(int)
for r in records.values():
    corpus_cnt[(r["format"], r["theme"])] += 1

# ---- 2. largest-remainder quotas per theme (floor 1 per present format) ---
def quotas_for_theme(theme):
    present = [f for f in FORMATS if corpus_cnt[(f, theme)] > 0]
    total = sum(corpus_cnt[(f, theme)] for f in present)
    ideal = {f: T * corpus_cnt[(f, theme)] / total for f in present}
    q = {f: int(ideal[f]) for f in present}            # floor
    need = T - sum(q.values())
    # distribute remainder by largest fractional part (tie -> FORMATS order)
    order = sorted(present, key=lambda f: (-(ideal[f] - int(ideal[f])), FORMATS.index(f)))
    for i in range(need):
        q[order[i]] += 1
    # enforce floor 1 for present formats
    for f in present:
        if q[f] == 0:
            q[f] = 1
            donor = max((g for g in present if q[g] > 1),
                        key=lambda g: (q[g], -FORMATS.index(g)))
            q[donor] -= 1
    return present, q

# ---- 3. forced placement + cell raises ------------------------------------
forced_by_cell = collections.defaultdict(list)  # (theme,fmt) -> [codes]
for code in sorted(set(AI) | set(ORPH)):
    r = records[code]
    forced_by_cell[(r["theme"], r["format"])].append(code)

quota = {}            # (theme, fmt) -> int
raise_log = []        # human-readable adjustments
for theme in THEMES:
    present, q = quotas_for_theme(theme)
    # apply forced-exceeds-quota raises
    for f in present:
        fc = len(forced_by_cell.get((theme, f), []))
        if fc > q[f]:
            deficit = fc - q[f]
            raise_log.append(f"Theme {theme}: forced {f}={fc} > quota {q[f]} -> raise to {fc}")
            q[f] = fc
            # reduce other present cells by largest current quota, floor 1
            for _ in range(deficit):
                donor = max((g for g in present if g != f and q[g] > 1),
                            key=lambda g: (q[g], -FORMATS.index(g)))
                q[donor] -= 1
                raise_log.append(f"           -> reduce {donor} to {q[donor]}")
    assert sum(q.values()) == T, (theme, q)
    for f in present:
        quota[(theme, f)] = q[f]

# ---- 4. select: forced first, then ascending-code fill --------------------
selected = {}   # code -> {theme, format, rationale, forced_category}
def add(code, rationale, forced_cat=""):
    r = records[code]
    selected[code] = {"theme": r["theme"], "format": r["format"],
                      "rationale": rationale, "forced": forced_cat}

# forced
for code in sorted(set(AI) | set(ORPH)):
    cat, desc = FORCED_NOTE[code]
    add(code, f"Forced [{cat}]: {desc}", cat)

# fill each cell by ascending Article-Code
for theme in THEMES:
    for f in FORMATS:
        if (theme, f) not in quota:
            continue
        target = quota[(theme, f)]
        pool = sorted(c for c, r in records.items()
                      if r["theme"] == theme and r["format"] == f)
        have = sum(1 for c in selected if selected[c]["theme"] == theme
                   and selected[c]["format"] == f)
        for c in pool:
            if have >= target:
                break
            if c in selected:
                continue
            add(c, f"Representative {THEME_LABEL[theme]} / {f} (ascending-code quota fill)")
            have += 1

# ---- 5. emit outputs (UTF-8-SIG) ------------------------------------------
os.makedirs(OUT_DIR, exist_ok=True)

# pilot_subset_frozen_v3.csv
frozen_rows = sorted(selected.items(), key=lambda kv: (kv[1]["theme"],
                     FORMATS.index(kv[1]["format"]), kv[0]))
with open(os.path.join(OUT_DIR, "pilot_subset_frozen_v3.csv"), "w",
          encoding="utf-8-sig", newline="") as fh:
    w = csv.writer(fh)
    fh.write(f"# FROZEN pilot subset v3 - frozen as of {FROZEN_DATE}. "
             "IMMUTABLE - later changes require a new versioned file (v4).\n")
    fh.write("# Supersedes v2 (125 docs) and v1 (25 docs); v1 & v2 retained unchanged.\n")
    fh.write("# 95 docs (19 per theme x 5) - restores the <100 pilot cap (v2 broke it at 125).\n")
    fh.write("# Pilot RUN+EVALUATION set, NOT the taxonomy-design set (full corpus = W1.7, 1089 docs).\n")
    w.writerow(["doc_id", "theme", "format", "one_line_rationale"])
    for code, d in frozen_rows:
        w.writerow([code, d["theme"], d["format"], d["rationale"]])

# coverage_table_v3.csv
sel_cnt = collections.defaultdict(int)
for d in selected.values():
    sel_cnt[(d["format"], d["theme"])] += 1
with open(os.path.join(OUT_DIR, "coverage_table_v3.csv"), "w",
          encoding="utf-8-sig", newline="") as fh:
    w = csv.writer(fh)
    fh.write("# Coverage table v3: theme (A-E) x format. Cell = # selected docs. "
             "Target = 19 per theme (column totals); 95 total (<100 cap).\n")
    w.writerow(["format"] + THEMES + ["ROW_TOTAL"])
    for f in FORMATS:
        cells = [sel_cnt[(f, t)] for t in THEMES]
        w.writerow([f] + cells + [sum(cells)])
    coltot = [sum(sel_cnt[(f, t)] for f in FORMATS) for t in THEMES]
    w.writerow(["COL_TOTAL"] + coltot + [sum(coltot)])
    w.writerow([])
    w.writerow(["GAP ANALYSIS (empty subset cell that HAS corpus docs = real gap)"])
    w.writerow(["format", "theme", "corpus_docs", "subset_docs", "status"])
    for f in FORMATS:
        for t in THEMES:
            cd = corpus_cnt[(f, t)]; sd = sel_cnt[(f, t)]
            if cd == 0:
                status = "expected-empty (none in corpus)"
            elif sd == 0:
                status = "GAP"
            else:
                status = "covered"
            w.writerow([f, t, cd, sd, status])

# forced_inclusions_v3.csv (CA242/SA049 under both categories)
with open(os.path.join(OUT_DIR, "forced_inclusions_v3.csv"), "w",
          encoding="utf-8-sig", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["category", "doc_id", "format", "theme", "title", "note"])
    for code in AI:
        r = records[code]
        w.writerow(["AI-governance", code, r["format"], r["theme"], r["title"],
                    FORCED_NOTE[code][1]])
    for code in ORPH:
        r = records[code]
        w.writerow(["orphaned-topic", code, r["format"], r["theme"], r["title"],
                    FORCED_NOTE[code][1]])

# ---- 6. self-checks + console report --------------------------------------
print(f"CORPUS TOTAL READ: {corpus_total}")
print("\nPER-THEME FORMAT QUOTAS (final, post forced-raise):")
print("theme | " + " ".join(f"{f[:4]:>5}" for f in FORMATS) + " | total")
for t in THEMES:
    cells = [quota.get((t, f), 0) for f in FORMATS]
    print(f"  {t}   | " + " ".join(f"{c:>5}" for c in cells) + f" |  {sum(cells)}")
print("\nRAISE LOG:")
for ln in raise_log: print("  " + ln)

print("\nSELECTED theme x format matrix:")
print("format    ," + ",".join(THEMES) + ",ROW")
for f in FORMATS:
    cells = [sel_cnt[(f, t)] for t in THEMES]
    print(f"{f:10},{','.join(str(x) for x in cells)},{sum(cells)}")
coltot = [sum(sel_cnt[(f, t)] for f in FORMATS) for t in THEMES]
print(f"{'COL_TOTAL':10},{','.join(str(x) for x in coltot)},{sum(coltot)}")

# acceptance
ids = list(selected.keys())
checks = []
checks.append(("total < 100", len(ids) < 100, len(ids)))
per_theme = collections.Counter(d["theme"] for d in selected.values())
checks.append(("19 per theme", all(per_theme[t] == 19 for t in THEMES), dict(per_theme)))
forced_all = set(AI) | set(ORPH)
checks.append(("all 16 forced present", forced_all <= set(ids), len(forced_all & set(ids))))
checks.append(("5 themes present", set(per_theme) == set(THEMES), sorted(per_theme)))
fmts_present = set(d["format"] for d in selected.values())
checks.append(("4 formats present", fmts_present == set(FORMATS), sorted(fmts_present)))
gaps = [(f, t) for f in FORMATS for t in THEMES
        if corpus_cnt[(f, t)] > 0 and sel_cnt[(f, t)] == 0]
checks.append(("no GAP cells", not gaps, gaps))
wellformed = all(ID_RE.match(c) for c in ids)
checks.append(("ids well-formed ^[CGBS][A-E]\\d{3}$", wellformed, wellformed))
checks.append(("ids unique", len(ids) == len(set(ids)), len(ids)))
checks.append(("all resolve in corpus", all(c in records for c in ids), True))
checks.append(("coverage totals == 95", sum(coltot) == 95, sum(coltot)))
print("\nACCEPTANCE:")
ok = True
for name, passed, val in checks:
    ok = ok and passed
    print(f"  [{'x' if passed else ' '}] {name}: {val}")
print("\nALL PASS" if ok else "\n*** FAILURES ***")

# emit a small machine summary for the notes writer
print("\nQUOTA_JSON=" + json.dumps({t: {f: quota.get((t, f), 0) for f in FORMATS} for t in THEMES}))
print("CORPUS_JSON=" + json.dumps({t: {f: corpus_cnt[(f, t)] for f in FORMATS} for t in THEMES}))
