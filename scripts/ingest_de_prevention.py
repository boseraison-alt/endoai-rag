"""
Targeted retrieval: dens evaginatus MANAGEMENT and PREVENTION (`case-v3` Item C).

WHY. `case-v2.1` ingested DE *aetiology* — enough to make the differential
name it and cite it. The next turn of the same conversation asked the other
half of the question: "is there anything a dentist can do to prevent pulp
necrosis from setting in?" The library had **8** rows touching DE management at
all, of which two are actually about prophylaxis, and the answer's Scenario A —
a four-step preventive protocol with a reduction increment, an interval and a
recall period — cited **nothing** on three of its four steps.

That is Items A and B's finding from the retrieval side: the detector should
have flagged those steps (it does now), but flagging them only helps if there
is something to cite. This closes the other half.

SYNONYMS. Prophylactic management of an evaginated tubercle goes by many
names, and the modern term finds few of them: tubercle reduction, prophylactic
grinding, staged occlusal reduction, tubercle capping, composite reinforcement,
fissure sealing of the tubercle base, and — because the tooth is usually
immature when it presents — vital pulp therapy, apexogenesis and MTA
pulpotomy in evaginated teeth.

**Talon cusp is EXCLUDED**, as in the aetiology ingest: it is the anterior
analogue and pulls maxillary incisor literature into a mandibular premolar
question.

RELEVANCE-GATED, the same pattern the aetiology ingest established and for the
same measured reason: `fetch_papers` broadens a zero-hit tier query once, and
on a narrow topic the broadened form stops being about the topic. 23 of 48
papers in that run were general endodontics. Only papers whose own title or
abstract names the anomaly are written.

    python scripts/ingest_de_prevention.py            # dry run
    python scripts/ingest_de_prevention.py --apply
"""

import argparse
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import endo_ai  # noqa: E402

DE_TERMS = (
    '("dens evaginatus" OR "evaginated odontome" OR "evaginated odontoma" '
    'OR "central cusp" OR "tuberculated premolar" OR "Leong premolar" '
    'OR "Leong\'s premolar" OR "occlusal tubercle" OR "evaginated tooth" '
    'OR "evaginated teeth")'
)
EXCLUDE = 'NOT ("talon cusp"[ti])'

QUERIES = [
    ("DE prophylactic tubercle management",
     f'{DE_TERMS} AND (prophylactic OR prophylaxis OR preventive OR prevention '
     f'OR "tubercle reduction" OR "selective grinding" OR "occlusal reduction" '
     f'OR "tubercle capping" OR "composite reinforcement" OR sealant OR '
     f'"fissure seal*" OR "resin reinforcement") {EXCLUDE}'),
    ("DE vital pulp therapy and pulpotomy",
     f'{DE_TERMS} AND ("vital pulp therapy" OR pulpotomy OR "pulp cap*" OR '
     f'apexogenesis OR "MTA" OR "calcium silicate" OR Biodentine OR '
     f'"direct pulp capping" OR "partial pulpotomy") {EXCLUDE}'),
    ("DE staged reduction and monitoring outcomes",
     f'{DE_TERMS} AND (outcome* OR survival OR prognosis OR follow-up OR '
     f'"recall interval" OR monitoring OR "reparative dentin*" OR '
     f'"secondary dentin*" OR "pulp canal obliteration") {EXCLUDE}'),
]

_ON_TOPIC = re.compile(
    r"evaginat|central cusp|tuberculated premolar|Leong|occlusal tubercle",
    re.IGNORECASE)


def _split_on_topic(scored):
    """(on_topic, off_topic) by whether the paper names the anomaly itself."""
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


def _library_rows():
    from rag import get_conn
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT pmid, year, level_key, score, left(title, 100)
            FROM endo_papers_rag
            WHERE title ILIKE '%evaginat%' OR abstract ILIKE '%dens evaginatus%'
               OR title ILIKE '%central cusp%' OR title ILIKE '%tuberculated%'
               OR title ILIKE '%occlusal tubercle%'
            ORDER BY pmid;
        """)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--min-score", type=float, default=50.0,
                    help="write-back quality floor. `learn_from_live_results` "
                         "defaults to 50, and on THIS topic that floor is the "
                         "whole problem — see the note in main().")
    ap.add_argument("--out", default="eval/logs/de_prevention_ingest.json")
    args = ap.parse_args()

    endo_ai.LIBRARY_WRITE_BACK = False      # this script writes, gated
    print(f"{'APPLY' if args.apply else 'DRY RUN'}\n")

    before = _library_rows()
    print(f"library rows naming the anomaly, before: {len(before)}")

    results, keep, dropped = [], {}, {}
    for label, term in QUERIES:
        print(f"\n=== {label} ===")
        found = []
        for level_key, tier_filter in (
                ("cochrane", endo_ai.COCHRANE_TERM),
                ("level1",  " OR ".join(endo_ai.LEVEL_1_TERMS)),
                ("level3a", " OR ".join(endo_ai.LEVEL_3A_TERMS)),
                ("level4",  " OR ".join(endo_ai.LEVEL_4_TERMS)),
                ("level5",  " OR ".join(endo_ai.LEVEL_5_TERMS))):
            try:
                _t, _ids, scored = endo_ai.fetch_papers(
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
        print(f"  {len(found)} cleared the floors: {len(on)} on topic, "
              f"{len(off)} not")

    print(f"\n{'=' * 60}")
    print(f"ON TOPIC   {len(keep)}   OFF TOPIC (not written) {len(dropped)}")

    # WHY THE FLOOR IS THE STORY HERE.
    #
    # The first apply run of this script wrote ZERO papers. Not because the
    # retrieval failed — 27 papers cleared the relevance gate — but because 14
    # of them scored below `learn_from_live_results`' flat floor of 50, and the
    # other 13 were already in the library. Among the 14 rejected:
    #
    #   37506764  35.4  Current Management of Dens Evaginatus Teeth Based on
    #                   Pulpal Diagnosis
    #   16410059  23.1  Dens evaginatus: literature review, pathophysiology,
    #                   and comprehensive treatment regimen
    #   37180325  35.9  Apexification of dens evaginatus in a mandibular
    #                   premolar
    #
    # The first of those is the single most on-point paper in existence for the
    # answer this item is about — a management scheme organised by pulpal
    # diagnosis, which is exactly the Scenario A/B/C structure the model
    # invented for itself and could not cite.
    #
    # This is WORKLIST §1.5's defect on the write-back path: "a flat floor of
    # 50 culls entire fields whose best papers score in the 40s by
    # construction". Dens evaginatus is such a field. It is a developmental
    # anomaly; its literature is narrative reviews and case series, with no n,
    # no follow-up and no control arm, and it scores in the 20s and 30s
    # BECAUSE of what it is and not because it is bad.
    #
    # The floor is not lowered globally — that is a change to every topic with
    # no measurement behind it, and it belongs in its own batch. It is lowered
    # HERE, for one hand-written topic-specific ingest that has already applied
    # a relevance gate: every paper admitted names the anomaly in its own title
    # or abstract, which is a stronger guarantee than the score was providing.
    below = [p for p in keep.values()
             if (p.get("score") or 0) < 50 >= args.min_score]
    if below:
        print(f"\n  {len(below)} on-topic paper(s) score below the usual "
              f"write-back floor of 50 and are admitted at --min-score "
              f"{args.min_score:g}:")
        for p in sorted(below, key=lambda x: -(x.get("score") or 0)):
            print(f"    {p['pmid']}  {p.get('level_key'):<8} "
                  f"{p.get('score')}  {(p.get('title') or '')[:74]}")

    if args.apply and keep:
        from rag import get_cached_abstracts_bulk, learn_from_live_results
        per_pmid = get_cached_abstracts_bulk(sorted(keep))
        n = learn_from_live_results(
            list(keep.values()), per_pmid, min_score=args.min_score,
            query_text="dens evaginatus prophylactic tubercle management "
                       "prevention of pulp necrosis")
        print(f"\nwrote {n} paper(s) into the library "
              f"(min_score={args.min_score:g})")

    after = _library_rows()
    added = [p for p in after if p[0] not in {r[0] for r in before}]
    print(f"\nlibrary rows naming the anomaly, after: {len(after)} "
          f"(+{len(added)})")
    for pmid, year, level_key, score, title in sorted(
            added, key=lambda r: (r[2] or "", -(r[3] or 0))):
        print(f"  {pmid}  {year}  {level_key:<8} {score}  {title}")
    if not args.apply:
        print("\n(dry run — nothing written; re-run with --apply)")

    p = ROOT / args.out
    p.parent.mkdir(parents=True, exist_ok=True)
    io.open(p, "w", encoding="utf-8").write(json.dumps(
        {"applied": bool(args.apply), "before_rows": len(before),
         "after_rows": len(after), "on_topic": len(keep),
         "off_topic": len(dropped), "off_topic_pmids": sorted(dropped),
         "added": [{"pmid": r[0], "year": r[1], "level_key": r[2],
                    "score": r[3], "title": r[4]} for r in added],
         "queries": results}, indent=1, ensure_ascii=False))
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
