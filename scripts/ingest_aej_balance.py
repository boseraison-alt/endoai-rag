"""
A34c — the stocking gap is Australian Endodontic Journal, and it is not JOE.

A34b measured the thing the item was written to find, and found the opposite of
what was expected:

    journal                  PubMed   library   retrieved
    Journal of Endodontics    15.4%     13.7%       16.2%   balanced
    Int Endodontic Journal     7.3%      7.8%       14.4%   retrieval 2x
    Australian Endod J         4.7%      1.6%        1.6%   UNDER-STOCKED

JOE is retrieved slightly ABOVE PubMed's own share, so there is nothing for a
JOE ingestion to correct. AEJ is the one genuine shortfall, and nobody was
looking for it.

A34c's shape applies unchanged: ADDITIVE ingestion, NO scoring change, NO
invariant touched, no journal signal entering the engine. Stocking a journal the
library under-holds is not preferring it — every paper added is judged by the
same tier ladder, the same floors and the same caps as any other.

HOW MANY. 693 recent in-domain AEJ papers exist and the library holds 50.
Ingesting all of them would take AEJ to ~18% of the library, four times PubMed's
4.7% — overshooting the imbalance in the other direction. The target is the
share the measurement named:

    to 3.0%    ~43 papers
    to 4.7%    ~99 papers      <- PubMed's share for the 29 eval questions
    to 6.0%   ~143 papers

WHICH ONES. By study design, highest tier first — the rule that would be applied
to any under-stocked journal, and journal-neutral in principle:

    systematic review / meta-analysis   54 available
    randomised controlled trial         26
    observational / cohort / x-sectional 56
    (review 92, case reports 66 — not drawn on unless the target needs them)

Recency breaks ties within a design, because the library's own staleness rule
(RAG_MAX_TOPIC_AGE_YEARS) says an old newest-paper sends a topic live.

    python scripts/ingest_aej_balance.py                 # dry run
    python scripts/ingest_aej_balance.py --apply
    python scripts/ingest_aej_balance.py --target 43 --apply
"""

import argparse
import io
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import endo_ai  # noqa: E402
from endo_ai import (ncbi_get, NCBI_EUTILS_BASE, ENDO_DOMAIN_FILTER,  # noqa: E402
                     extract_sample_size, extract_followup_period,
                     get_impact_factor, score_paper, _select_abstract_paragraph)
from rag import get_conn, embed, upsert_paper  # noqa: E402

JOURNAL = '"Aust Endod J"[jour]'
AEJ_PATS = ("aust endod j", "australian endodontic journal")
DEFAULT_TARGET = 99          # 4.7%, the share A34b measured in PubMed

# Highest tier first. Mirrors the ladder without touching it.
DESIGN_ORDER = [
    ("level1", "(systematic review[pt] OR meta-analysis[pt])"),
    ("level1", "randomized controlled trial[pt]"),
    ("level2", "clinical trial[pt]"),
    # A31's tier, not level3a. The filter is MeSH-based, and MeSH does not
    # appear in `pubtype`, so the inference below cannot see it — which is why
    # the selection tier is carried through as a fallback.
    ("observational", "(observational study[pt] OR cohort studies[mh] "
                      "OR cross-sectional studies[mh])"),
]
PUBTYPE_TO_LEVEL = [
    ("meta-analysis", "level1"), ("systematic review", "level1"),
    ("randomized controlled trial", "level1"), ("practice guideline", "level1"),
    ("guideline", "level1"), ("consensus development conference", "level1"),
    ("controlled clinical trial", "level2"), ("clinical trial", "level2"),
    ("multicenter study", "level2"),
    ("observational study", "level3a"), ("comparative study", "level3a"),
    ("evaluation study", "level3b"),
    ("case reports", "level4"),
    ("review", "level5"), ("editorial", "level5"),
    ("comment", "level5"), ("letter", "level5"),
]

# WHY THE SELECTION TIER IS CARRIED THROUGH.
#
# The first dry run selected 46 papers with `cross-sectional studies[mh]` and
# `cohort studies[mh]` and then banded 27 of them level5, because MeSH terms do
# not appear in `pubtype` and the inference below is pubtype-only. The result
# read as "highest design first" while a third of the intake was landing in the
# weakest tier — a selection rule that does not match what the ladder reads is
# not a selection rule.
#
# A31 built the `observational` tier for exactly these designs. Where the
# pubtype inference falls through to level5 but the paper was SELECTED by a
# design filter, the filter's tier is what is known about it and is used.


def _get(url, params, tries=3):
    for k in range(tries):
        try:
            return ncbi_get(url, params=params, timeout=25).json()
        except Exception as ex:
            if k == tries - 1:
                print("    NCBI failed after %d tries: %s" % (tries, ex))
                return {}
            time.sleep(1.5 * (k + 1))


def esearch(term, n=300):
    j = _get(f"{NCBI_EUTILS_BASE}/esearch.fcgi",
             {"db": "pubmed", "term": term, "retmax": n,
              "retmode": "json", "sort": "pub_date"})
    return (j.get("esearchresult", {}) or {}).get("idlist", []) or []


def held_pmids():
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT pmid, journal FROM endo_papers_rag")
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()
    aej = {r[0] for r in rows
           if any(p in (r[1] or "").lower() for p in AEJ_PATS)}
    return {r[0] for r in rows}, aej, len(rows)


def fetch(pmid, selected_tier=None):
    meta = (_get(f"{NCBI_EUTILS_BASE}/esummary.fcgi",
                 {"db": "pubmed", "id": pmid, "retmode": "json"})
            .get("result", {}) or {}).get(pmid, {}) or {}
    if not meta or meta.get("error"):
        return None
    try:
        raw = ncbi_get(f"{NCBI_EUTILS_BASE}/efetch.fcgi",
                       params={"db": "pubmed", "id": pmid,
                               "rettype": "abstract", "retmode": "text"},
                       timeout=25).text
    except Exception:
        raw = ""
    paras, cur = [], []
    for line in raw.split("\n"):
        if line.strip():
            cur.append(line.strip())
        elif cur:
            paras.append(" ".join(cur)); cur = []
    if cur:
        paras.append(" ".join(cur))
    ym = re.search(r"\b(19|20)\d{2}\b", meta.get("pubdate", "") or "")
    names = [a.get("name", "") for a in (meta.get("authors") or []) if a.get("name")]
    pubtypes = [str(p).strip().lower() for p in (meta.get("pubtype") or [])]
    tier = None
    for tag, level in PUBTYPE_TO_LEVEL:
        if tag in pubtypes:
            tier = level
            break
    if tier in (None, "level5") and selected_tier:
        tier = selected_tier
    tier = tier or "level5"
    return {
        "pmid": pmid,
        "title": (meta.get("title") or "").rstrip("."),
        "abstract": _select_abstract_paragraph(paras) or "",
        "journal": meta.get("fulljournalname") or meta.get("source") or "",
        "year": ym.group(0) if ym else None,
        "authors": ", ".join(names[:5]) + (", et al." if len(names) > 5 else ""),
        "level_key": tier, "pubtypes": pubtypes,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    # argparse re-expands %-escapes in help text, so the literal percent has
    # to survive two passes.
    ap.add_argument("--target", type=int, default=DEFAULT_TARGET,
                    help="how many papers to ADD; the default reaches PubMed's "
                         "own 4.7 percent share")
    ap.add_argument("--out", default="eval/logs/a34c_aej_ingest.json")
    args = ap.parse_args()
    endo_ai.LIBRARY_WRITE_BACK = False
    print("APPLY\n" if args.apply else "DRY RUN\n")

    all_held, aej_held, n_rows = held_pmids()
    print("library %d rows; AEJ held %d (%.1f%%)"
          % (n_rows, len(aej_held), 100.0 * len(aej_held) / max(1, n_rows)))

    # ── choose, highest design first, newest within each ──────────────────
    chosen, seen_design = [], {}
    for tier, dfilter in DESIGN_ORDER:
        if len(chosen) >= args.target:
            break
        term = "%s AND %s AND 2015:2026[dp] AND %s" % (
            JOURNAL, ENDO_DOMAIN_FILTER, dfilter)
        ids = [p for p in esearch(term) if p not in all_held]
        take = ids[:args.target - len(chosen)]
        for p in take:
            if p not in [c[0] for c in chosen]:
                chosen.append((p, tier, dfilter))
        seen_design[dfilter] = (len(ids), len(take))
        print("  %-58s available %3d, taking %3d"
              % (dfilter[:58], len(ids), len(take)))

    print("\nselected %d paper(s); target was %d" % (len(chosen), args.target))
    if len(chosen) < args.target:
        print("  NOTE: fewer than the target — the higher tiers are exhausted. "
              "Reviews and case reports are deliberately NOT drawn on to make "
              "up the number; a balance made of case reports is not balance.")

    # ── fetch and report BEFORE writing (rule 2) ─────────────────────────
    fetched, skipped = [], []
    for i, (pmid, _t, _d) in enumerate(chosen, 1):
        rec = fetch(pmid, selected_tier=_t)
        if not rec:
            skipped.append((pmid, "not returned by PubMed")); continue
        if not rec["abstract"]:
            # An abstract-less row embeds on its title alone and reaches
            # synthesis as a name with no finding.
            skipped.append((pmid, "no abstract")); continue
        n = extract_sample_size(rec["abstract"])
        fu = extract_followup_period(rec["abstract"])
        if_val, if_pts = get_impact_factor(rec["journal"])
        rec["score"], _b = score_paper(
            level_key=rec["level_key"], year=rec["year"] or "2020", citations=0,
            sample_size=n, followup_months=(fu[0] if fu else None), if_score=if_pts)
        rec.update({"impact_factor": if_val, "sample_size": n,
                    "followup_months": (fu[0] if fu else None)})
        fetched.append(rec)
        if i % 20 == 0:
            print("  fetched %d/%d" % (i, len(chosen)))

    tiers = Counter(r["level_key"] for r in fetched)
    years = Counter((r["year"] or "?")[:4] for r in fetched)
    print("\nDELTA SPLIT (rule 2 — reported before applying)")
    print("  fetched %d, skipped %d" % (len(fetched), len(skipped)))
    for t, c in sorted(tiers.items()):
        print("    %-10s %3d" % (t, c))
    print("  years: %s" % dict(sorted(years.items())))
    if fetched:
        s = sorted(r["score"] for r in fetched)
        print("  score: min %.1f median %.1f max %.1f"
              % (s[0], s[len(s) // 2], s[-1]))
    for p, why in skipped[:10]:
        print("    skipped %s — %s" % (p, why))
    print("\n  library %d -> %d  (AEJ %.1f%% -> %.1f%%)"
          % (n_rows, n_rows + len(fetched),
             100.0 * len(aej_held) / max(1, n_rows),
             100.0 * (len(aej_held) + len(fetched)) / max(1, n_rows + len(fetched))))

    if args.apply and fetched:
        for r in fetched:
            upsert_paper({
                "pmid": r["pmid"], "title": r["title"], "abstract": r["abstract"],
                "authors": r["authors"],
                "year": int(r["year"]) if (r["year"] or "").isdigit() else None,
                "journal": r["journal"], "impact_factor": r["impact_factor"],
                "sample_size": r["sample_size"],
                "followup_months": r["followup_months"], "citations": 0,
                "level_key": r["level_key"], "score": r["score"],
            }, embed("%s %s" % (r["title"], r["abstract"])))
        print("\nwrote %d paper(s)" % len(fetched))
    elif not args.apply:
        print("\n(dry run — nothing written; re-run with --apply)")

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    io.open(out, "w", encoding="utf-8").write(json.dumps({
        "target": args.target, "library_rows_before": n_rows,
        "aej_held_before": len(aej_held),
        "selected": [c[0] for c in chosen],
        "fetched": [{k: r[k] for k in ("pmid", "title", "year", "level_key", "score")}
                    for r in fetched],
        "skipped": skipped, "by_tier": dict(tiers), "applied": bool(args.apply),
    }, indent=2))
    print("report: %s" % args.out)


if __name__ == "__main__":
    main()
