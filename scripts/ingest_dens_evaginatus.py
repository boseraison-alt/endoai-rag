"""
Targeted retrieval: dens evaginatus in mandibular premolars (`case-v2.1` Item 2a).

WHY THIS TOPIC AND NOT A GENERAL SWEEP. The fixture case is tooth #20 — a
mandibular second premolar — in a 20-year-old of Asian ethnicity, with a
necrotic pulp and no caries, no restoration and no cracks. That is the textbook
dens evaginatus presentation, and the library holds **12** rows that mention
the anomaly at all, of which exactly ONE is about it: Senia and Regezi, 1974.
Everything else is regenerative-endodontics outcome literature that happens to
name DE as an inclusion criterion.

So the answer's load-bearing etiologic claim had one 1974 case report and a
Thai cross-sectional study behind it, and it overreached the latter — the study
says "In IMMATURE teeth requiring NS-RCT, the predominant etiologies were dens
evaginatus (32.1%)", and the answer rendered that as "the leading cause of RCT
in premolars presenting without caries". Two substitutions in one sentence:
immature teeth became premolars, and the caries-free qualifier was invented.

The fix is better sourcing OR honest phrasing, never dropping the DE
discussion. This script is the sourcing half.

SYNONYMS. "Dens evaginatus" is the modern term; the older literature calls it
the central cusp, the tuberculated premolar, Leong's premolar, occlusal
tubercle, or evaginated odontoma. **Talon cusp is EXCLUDED** — it is the
anterior analogue and a different clinical problem, and including it would
import maxillary incisor literature into a mandibular premolar question.

Writes back through the normal path, so every row it adds has cleared the same
per-tier quality floor, tier assignment and provenance merge as any other. Dry
run by default.

    python scripts/ingest_dens_evaginatus.py            # dry run
    python scripts/ingest_dens_evaginatus.py --apply
"""

import argparse
import io
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import endo_ai  # noqa: E402

DE_TERMS = (
    '("dens evaginatus" OR "dens evaginatus"[tiab] OR "evaginated odontome" '
    'OR "evaginated odontoma" OR "central cusp" OR "tuberculated premolar" '
    'OR "Leong premolar" OR "Leong\'s premolar" OR "occlusal tubercle" '
    'OR "accessory cusp"[tiab])'
)
# Talon cusp is the anterior analogue and a different clinical problem.
EXCLUDE = 'NOT ("talon cusp"[ti])'

QUERIES = [
    ("DE epidemiology and prevalence",
     f'{DE_TERMS} AND (prevalence OR epidemiolog* OR incidence OR frequency '
     f'OR "population study" OR ethnic* OR Asian OR Chinese OR Thai OR '
     f'Japanese OR Korean OR Malay*) {EXCLUDE}'),
    ("DE aetiology of pulp necrosis in premolars",
     f'{DE_TERMS} AND (premolar* OR bicuspid*) AND ("pulp necrosis" OR '
     f'"pulpal necrosis" OR "periapical" OR "apical periodontitis" OR '
     f'"root canal treatment" OR endodontic*) {EXCLUDE}'),
    ("DE management and outcomes",
     f'{DE_TERMS} AND (management OR treatment OR outcome* OR prognosis OR '
     f'"prophylactic" OR sealant OR "pulp cap*") {EXCLUDE}'),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write results back into the library. Without it "
                         "nothing is written and the report is a dry run.")
    ap.add_argument("--out", default="eval/logs/de_ingest.json")
    args = ap.parse_args()

    # `fetch_papers`' OWN write-back is switched off and this script does the
    # writing itself, through the same `learn_from_live_results`, because a
    # RELEVANCE gate has to sit between them.
    #
    # WHY. A tier query that returns 0 hits is BROADENED once by `fetch_papers`
    # — sensible on an ordinary question, and destructive on a narrow one. The
    # first dry run of this script cleared 48 papers through the quality
    # floors and **23 of them did not mention the anomaly at all**: "Single
    # versus multiple visits for endodontic treatment", "Systemic antibiotics
    # for symptomatic apical periodontitis", "Materials for retrograde
    # filling". The broadened query stopped being about dens evaginatus and
    # became about endodontics, and every one of those would have been written
    # into the library as the product of a targeted DE ingest.
    #
    # A targeted ingest that imports the general corpus is not targeted. Only
    # papers whose title or abstract actually names the anomaly are written.
    endo_ai.LIBRARY_WRITE_BACK = False
    print(f"{'APPLY' if args.apply else 'DRY RUN'}\n")

    before = _library_de_rows()
    print(f"library rows mentioning dens evaginatus, before: {len(before)}")

    results = []
    keep, dropped = {}, {}
    for label, term in QUERIES:
        print(f"\n=== {label} ===")
        print(f"  term: {term[:160]}…")
        found = []
        # The same tier filters `build_evidence_base` uses, joined the same
        # way. Level 2 and 3b are skipped deliberately: this is an anomaly
        # with essentially no trial literature, and a controlled-trial or
        # case-control filter over it returns the general endodontic corpus
        # that the topic words happen to match. Level 4 is where DE actually
        # lives.
        for level_key, tier_filter in (
                ("cochrane", endo_ai.COCHRANE_TERM),
                ("level1",  " OR ".join(endo_ai.LEVEL_1_TERMS)),
                ("level3a", " OR ".join(endo_ai.LEVEL_3A_TERMS)),
                ("level4",  " OR ".join(endo_ai.LEVEL_4_TERMS)),
                ("level5",  " OR ".join(endo_ai.LEVEL_5_TERMS))):
            try:
                _text, ids, scored = endo_ai.fetch_papers(
                    term, tier_filter, f"{label} [{level_key}]", level_key,
                    mode="case", question=label)
            except Exception as e:
                print(f"    XX {level_key}: {e}")
                continue
            found.extend(scored)
        on, off = _split_on_topic(found)
        keep.update({p["pmid"]: p for p in on})
        dropped.update({p["pmid"]: p for p in off})
        results.append({"label": label, "term": term,
                        "on_topic": [_row(p) for p in on],
                        "off_topic": [_row(p) for p in off]})
        print(f"  {len(found)} paper(s) cleared the quality floors: "
              f"{len(on)} mention the anomaly, {len(off)} do not")

    print(f"\n{'=' * 60}")
    print(f"ON TOPIC   {len(keep)} distinct paper(s) — candidates for write-back")
    print(f"OFF TOPIC  {len(dropped)} distinct paper(s) — NOT written; the "
          f"broadening step reached the general corpus")
    for p in sorted(dropped.values(), key=lambda x: x.get("pmid") or ""):
        print(f"    drop {p.get('pmid')}  {(p.get('title') or '')[:88]}")

    if args.apply and keep:
        from rag import get_cached_abstracts_bulk, learn_from_live_results
        per_pmid = get_cached_abstracts_bulk(sorted(keep))
        n = learn_from_live_results(
            list(keep.values()), per_pmid,
            query_text="dens evaginatus pulp necrosis mandibular premolar")
        print(f"\nwrote {n} paper(s) into the library")

    after = _library_de_rows()
    added = [p for p in after if p[0] not in {r[0] for r in before}]
    print(f"\nlibrary rows mentioning dens evaginatus, after: {len(after)} "
          f"({'+' if added else ''}{len(added)} new)")
    for pmid, year, level_key, score, title in sorted(
            added, key=lambda r: (r[2] or "", -(r[3] or 0))):
        print(f"  {pmid}  {year}  {level_key:<8} {score}  {title}")
    if not args.apply:
        print("\n(dry run — nothing was written; re-run with --apply)")

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    io.open(out, "w", encoding="utf-8").write(json.dumps(
        {"applied": bool(args.apply),
         "before_rows": len(before), "after_rows": len(after),
         "added": [{"pmid": p[0], "year": p[1], "level_key": p[2],
                    "score": p[3], "title": p[4]} for p in added],
         "on_topic": len(keep), "off_topic": len(dropped),
         "off_topic_pmids": sorted(dropped),
         "queries": results}, indent=1, ensure_ascii=False))
    print(f"wrote {out}")


# The anomaly, by any of its names. Deliberately the SAME set the queries use,
# minus the field tags, so a paper is on topic exactly when it says one of the
# words the search asked for.
_ON_TOPIC = re.compile(
    r"evaginat|central cusp|tuberculated premolar|Leong|occlusal tubercle",
    re.IGNORECASE)


def _split_on_topic(scored):
    """(on_topic, off_topic) by whether the paper names the anomaly.

    Judged on the paper's own title and abstract, from the abstract cache the
    fetch just populated — not on the query that found it, because the query
    that found it may have been broadened into something else entirely.
    """
    from rag import get_cached_abstracts_bulk
    pmids = sorted({p.get("pmid") for p in scored if p.get("pmid")})
    if not pmids:
        return [], []
    cached = get_cached_abstracts_bulk(pmids)
    on, off, seen = [], [], set()
    for p in scored:
        pmid = p.get("pmid")
        if not pmid or pmid in seen:
            continue
        seen.add(pmid)
        rec = cached.get(pmid) or {}
        text = f"{rec.get('title') or p.get('title') or ''} " \
               f"{rec.get('abstract') or ''}"
        (on if _ON_TOPIC.search(text) else off).append(
            {**p, "title": rec.get("title") or p.get("title") or ""})
    return on, off


def _row(p):
    return {"pmid": p.get("pmid"), "level_key": p.get("level_key"),
            "score": p.get("score"), "year": p.get("year"),
            "title": (p.get("title") or "")[:120]}


def _library_de_rows():
    """Every library row that mentions the anomaly, by title or abstract."""
    from rag import get_conn
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT pmid, year, level_key, score, left(title, 100)
            FROM endo_papers_rag
            WHERE title ILIKE '%evaginat%' OR abstract ILIKE '%dens evaginatus%'
               OR title ILIKE '%central cusp%' OR title ILIKE '%tuberculated%'
            ORDER BY pmid;
        """)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
