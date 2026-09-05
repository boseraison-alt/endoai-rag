"""A49 item 4b — ingest data/guidelines_seed.json as first-class guidelines.

60 documents, 19 organisations, every record checked against a primary source.
This puts them in the library as GUIDELINES rather than as papers.

WHAT MAKES THIS DIFFERENT FROM ingest_aae_guidelines.py, which wrote the
twelve records the A2 audit had to quarantine:

  no hand-set score      score is stored NULL. A guideline is not on the
                         study-design ladder and carries no number. The old
                         ingester hard-set 85-95, which outranked all 3,192
                         real evidence rows.
  no impact_factor       stored NULL. It is a forbidden signal, and the old
                         ingester wrote 4.5-8.0 as an "authority weighting".
  no model summaries     nothing is paraphrased. Where PubMed has a real
                         abstract it is used; where it does not, the record is
                         a POINTER -- org, title, year, status, URL -- which a
                         clinician can follow. A paraphrase Curo cannot verify
                         is worth less than a link, and `verify_citation_support`
                         checking a claim against a paraphrase is a hole
                         directly under the grounding guarantee.
  real identifiers       the manifest id, not an invented slug. Six of the old
                         sixteen named no document at all.

BINDING RULES, each enforced here and pinned in tests/test_guideline_seed.py:

  dedupe by PMID         a manifest record whose PMID is already in the paper
                         table RECLASSIFIES that row. Never a second row for
                         the same document. 41121563 and 40533920 are expected
                         to move -- the AAPD permanent-teeth VPT guideline and
                         its supporting review, currently sitting in the corpus
                         as papers, which is how a paediatric guideline became
                         the top-scored anchor of an adult curriculum.
  withdrawn              never citeable. Already enforced by G1, which reads
                         this manifest's own withdrawn ids; belt and braces
                         here via quarantine_reason.
  superseded             excluded from retrieval by the shipped superseded_by
                         machinery. STRICTER than the item asked for -- see
                         the report -- because a superseded guideline served
                         WITHOUT its notice is a clinical hazard and the
                         notice cannot be guaranteed tonight.
  draft                  never presented as current: quarantined, reversibly.
  unconfirmed_pmid       10 records whose DOI and journal are verified but
                         whose PubMed accession is not. Keyed by MANIFEST ID,
                         never by PMID, so they can never be emitted as
                         [PMID:N].
  reversible             quarantine_reason is the undo, exactly as in c7d7540.

Usage:
  python scripts/ingest_guidelines_seed.py            # DRY RUN
  python scripts/ingest_guidelines_seed.py --apply
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import psycopg2                    # noqa: E402
import psycopg2.extras             # noqa: E402
import rag                         # noqa: E402
from rag import DATABASE_URL       # noqa: E402

SEED = ROOT / "data" / "guidelines_seed.json"

# Statuses that must never be served as a current clinical recommendation.
QUARANTINE_STATUS = {
    "withdrawn": "withdrawn: the publisher has removed this document's "
                 "conclusions (manifest status 'withdrawn')",
    "draft": "draft: not a published guideline; must never be presented as "
             "current (manifest status 'draft')",
}
# Statuses handled through the shipped superseded_by exclusion instead.
SUPERSEDED_STATUS = {"superseded", "superseded_in_content"}

# ORGANISATIONS WHOSE MANIFEST ENTRIES ARE STUDIES, NOT POSITIONS.
#
# Caught on the dry run, and it would have been a bad regression. The manifest
# carries eight Cochrane entries -- it has to, because three of them are the
# WITHDRAWN reviews G1 exists for, and their supersession chains matter. But a
# Cochrane review is a SYSTEMATIC REVIEW: the archetypal top-of-the-ladder
# study design, not a specialty's stated position.
#
# Reclassifying them to level_key='guideline' would have moved three real
# systematic reviews from the cochrane tier (LEVEL_SCORES 100) to the
# guideline rung (12) and nulled their scores -- the exact
# score-as-membership category error, running in the opposite direction from
# the one A49 was opened to fix. Tier census on the dry run: cochrane 21 -> 18.
#
# So these records are ENRICHED (status, supersession, URL, jurisdiction all
# recorded) and their tier, score and impact factor are left alone. What the
# manifest knows about them is worth having; where they sit on the ladder is
# not the manifest's call.
REVIEW_PUBLISHERS = {"COCHRANE"}


def is_study_not_guideline(g):
    return (g.get("org") or "").strip().upper() in REVIEW_PUBLISHERS


def load_seed():
    d = json.loads(SEED.read_text(encoding="utf-8"))
    return d["guidelines"]


def key_for(g):
    """The library key. A confirmed PMID lets the row dedupe against an
    existing paper; anything else is keyed by manifest id, which is also what
    a citation will render, so an unconfirmed accession can never leak into a
    PMID slot."""
    if g.get("pmid") and g.get("confidence") == "confirmed":
        return str(g["pmid"]).strip()
    return str(g["id"]).strip()


def embed_text(g):
    """What the row is embedded on.

    Title, the manifest's own scope question, and its scope terms. All three
    are the DOCUMENT'S OWN metadata from a verified manifest, not a summary of
    its contents -- nothing here is written by a model.
    """
    bits = [g.get("title") or "", g.get("question") or ""]
    bits += list(g.get("scope") or [])
    bits.append("%s %s guideline" % (g.get("org") or "", g.get("year") or ""))
    return " ".join(b for b in bits if b).strip()


def pointer_text(g):
    """The stored 'abstract' for a record PubMed does not index.

    A POINTER, not a paraphrase: organisation, title, year, status,
    jurisdiction and URL. Everything in it is copied from the manifest.
    """
    lines = [
        "GUIDELINE RECORD — pointer only; Curo has not stored this document's text.",
        "Organisation: %s" % (g.get("org") or "?"),
        "Title: %s" % (g.get("title") or "?"),
        "Year: %s" % (g.get("year") or "?"),
        "Status: %s" % (g.get("status") or "?"),
        "Jurisdiction: %s" % (g.get("jurisdiction") or "?"),
    ]
    if g.get("question"):
        lines.append("Question it answers: %s" % g["question"])
    if g.get("url"):
        lines.append("Read it: %s" % g["url"])
    if g.get("superseded_by"):
        lines.append("SUPERSEDED BY: %s" % g["superseded_by"])
    return "\n".join(lines)


def tier_census(cur):
    cur.execute("""
        SELECT COALESCE(level_key,'(none)') AS level_key, COUNT(*) AS n
        FROM endo_papers_rag
        WHERE COALESCE(quarantine_reason,'') = ''
          AND NOT COALESCE(has_retraction, FALSE)
          AND title NOT ILIKE 'WITHDRAWN:%%'
          AND COALESCE(superseded_by,'') = ''
        GROUP BY 1 ORDER BY 1
    """)
    return {r["level_key"]: r["n"] for r in cur.fetchall()}


def plan(cur, guidelines):
    """Decide, per manifest record, what will happen. No writes."""
    keys = [key_for(g) for g in guidelines]
    cur.execute("SELECT pmid, level_key, score, impact_factor, title "
                "FROM endo_papers_rag WHERE pmid = ANY(%s)", (keys,))
    existing = {r["pmid"]: dict(r) for r in cur.fetchall()}

    actions = []
    for g in guidelines:
        k = key_for(g)
        cur_row = existing.get(k)
        status = (g.get("status") or "").lower()
        act = {
            "id": g["id"], "key": k, "org": g.get("org"),
            "status": status, "confidence": g.get("confidence"),
            "keyed_by": "pmid" if k == str(g.get("pmid") or "") else "manifest id",
            "action": ("enrich" if (cur_row and is_study_not_guideline(g))
                       else "reclassify" if cur_row else "insert"),
            "is_study": is_study_not_guideline(g),
            "was_level_key": (cur_row or {}).get("level_key"),
            "was_score": (cur_row or {}).get("score"),
            "was_impact_factor": (cur_row or {}).get("impact_factor"),
            "quarantine": QUARANTINE_STATUS.get(status, ""),
            "superseded_by": (g.get("superseded_by") or "")
                             if status in SUPERSEDED_STATUS else "",
        }
        actions.append(act)
    return actions, existing


def write(cur, guidelines, actions):
    by_id = {g["id"]: g for g in guidelines}
    for a in actions:
        g = by_id[a["id"]]
        k = a["key"]
        text = pointer_text(g)
        vec = rag.embed(embed_text(g))
        if a["action"] == "enrich":
            # Metadata only. level_key, score and impact_factor untouched:
            # a Cochrane systematic review's rung is a study-design fact and
            # the manifest has no authority over it.
            cur.execute("""
                UPDATE endo_papers_rag SET
                    guideline_id = %s, guideline_org = %s,
                    guideline_status = %s, guideline_jurisdiction = %s,
                    guideline_url = %s, guideline_confidence = %s,
                    superseded_by = COALESCE(NULLIF(%s,''), superseded_by),
                    quarantine_reason = COALESCE(NULLIF(%s,''), quarantine_reason)
                WHERE pmid = %s
            """, (g["id"], g.get("org") or "", g.get("status") or "",
                  g.get("jurisdiction") or "", g.get("url") or "",
                  g.get("confidence") or "", a["superseded_by"],
                  a["quarantine"], k))
        elif a["action"] == "reclassify":
            cur.execute("""
                UPDATE endo_papers_rag SET
                    level_key = 'guideline',
                    score = NULL,
                    impact_factor = NULL,
                    is_curated = TRUE,
                    journal = %s,
                    guideline_id = %s, guideline_org = %s,
                    guideline_status = %s, guideline_jurisdiction = %s,
                    guideline_url = %s, guideline_confidence = %s,
                    superseded_by = %s,
                    quarantine_reason = %s
                WHERE pmid = %s
            """, (g.get("journal") or "%s guideline" % (g.get("org") or ""),
                  g["id"], g.get("org") or "", g.get("status") or "",
                  g.get("jurisdiction") or "", g.get("url") or "",
                  g.get("confidence") or "", a["superseded_by"],
                  a["quarantine"], k))
        else:
            cur.execute("""
                INSERT INTO endo_papers_rag
                    (pmid, title, abstract, authors, year, journal,
                     impact_factor, citations, level_key, score, is_curated,
                     medline_indexed, embedding,
                     guideline_id, guideline_org, guideline_status,
                     guideline_jurisdiction, guideline_url,
                     guideline_confidence, superseded_by, quarantine_reason)
                VALUES (%s,%s,%s,%s,%s,%s, NULL,0,'guideline',NULL,TRUE,
                        FALSE,%s, %s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (pmid) DO NOTHING
            """, (k, g.get("title") or "", text, g.get("org") or "",
                  g.get("year"), g.get("journal")
                  or "%s guideline" % (g.get("org") or ""),
                  vec, g["id"], g.get("org") or "", g.get("status") or "",
                  g.get("jurisdiction") or "", g.get("url") or "",
                  g.get("confidence") or "", a["superseded_by"],
                  a["quarantine"]))


def main():
    apply_ = "--apply" in sys.argv
    rag.setup_table()

    guidelines = load_seed()
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    before = tier_census(cur)
    actions, existing = plan(cur, guidelines)

    print("=" * 78)
    print("A49 ITEM 4b — GUIDELINE SEED INGEST  —  %s"
          % ("APPLY" if apply_ else "DRY RUN"))
    print("=" * 78)
    print("  manifest records            %d" % len(guidelines))
    print("  will RECLASSIFY existing    %d"
          % sum(1 for a in actions if a["action"] == "reclassify"))
    print("  will ENRICH only (studies)  %d   tier/score untouched"
          % sum(1 for a in actions if a["action"] == "enrich"))
    print("  will INSERT new             %d"
          % sum(1 for a in actions if a["action"] == "insert"))
    print("  keyed by manifest id        %d   (never emitted as [PMID:N])"
          % sum(1 for a in actions if a["keyed_by"] == "manifest id"))
    print("  quarantined on ingest       %d   (withdrawn / draft)"
          % sum(1 for a in actions if a["quarantine"]))
    print("  marked superseded           %d"
          % sum(1 for a in actions if a["superseded_by"]))
    print()

    recl = [a for a in actions if a["action"] == "reclassify"]
    if recl:
        print("  RECLASSIFIED — these are already in the corpus AS PAPERS:")
        for a in recl:
            print("    %-22s %-14s was level_key=%-8s score=%-6s IF=%-5s"
                  % (a["key"], a["id"][:14], a["was_level_key"],
                     a["was_score"], a["was_impact_factor"]))
        print()

    enr = [a for a in actions if a["action"] == "enrich"]
    if enr:
        print("  ENRICHED ONLY — systematic reviews, NOT specialty positions.")
        print("  Their tier is a study-design fact; the manifest has no say in it.")
        for a in enr:
            print("    %-22s %-24s stays level_key=%-9s score=%s"
                  % (a["key"], a["id"][:24], a["was_level_key"], a["was_score"]))
        print()

    q = [a for a in actions if a["quarantine"]]
    if q:
        print("  QUARANTINED ON INGEST:")
        for a in q:
            print("    %-24s %-10s %s" % (a["id"], a["status"],
                                          a["quarantine"][:52]))
        print()

    s = [a for a in actions if a["superseded_by"]]
    if s:
        print("  SUPERSEDED (excluded by the shipped superseded_by machinery):")
        for a in s:
            print("    %-24s -> %s" % (a["id"], a["superseded_by"]))
        print()

    unconf = [a for a in actions if a["confidence"] == "unconfirmed_pmid"]
    print("  UNCONFIRMED PMID — keyed by manifest id, %d records:" % len(unconf))
    for a in unconf:
        print("    %-24s keyed_by=%s" % (a["id"], a["keyed_by"]))
    print()

    if apply_:
        write(cur, guidelines, actions)
        after = tier_census(cur)
        conn.commit()
    else:
        write(cur, guidelines, actions)
        after = tier_census(cur)
        conn.rollback()

    print("  DELTA — CITEABLE ROWS PER TIER")
    print("    %-16s %8s %8s %8s" % ("tier", "before", "after", "delta"))
    for t in sorted(set(before) | set(after)):
        b, a_ = before.get(t, 0), after.get(t, 0)
        print("    %-16s %8d %8d %+8d%s"
              % (t, b, a_, a_ - b, "   <-- changed" if a_ != b else ""))
    tb, ta = sum(before.values()), sum(after.values())
    print("    %-16s %8d %8d %+8d" % ("TOTAL", tb, ta, ta - tb))

    print("\n  %s" % ("APPLIED AND COMMITTED." if apply_
                      else "DRY RUN — rolled back. Re-run with --apply."))
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
