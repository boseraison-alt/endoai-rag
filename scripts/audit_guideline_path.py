"""A49 phase 0 — audit the guideline path. MEASURE ONLY, changes nothing.

A1  withdrawn Cochrane reviews in the library, and who cites them
A2  the 16 hardcoded records vs the verified seed manifest
A3  score contamination — how much real evidence a guideline row outranks
A4  impact_factor — every read and every write
A5  bare-key leaks — citation slots holding a non-PMID identifier

Usage:  python scripts/audit_guideline_path.py [--json out.json]
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.getcwd())

import rag  # noqa: E402

SEED = "data/guidelines_seed.json"

# The 16 slugs ingest_aae_guidelines.py hardcodes.
SLUGS = [
    "AAE-PS-antibiotics", "AAE-PS-cbct", "AAE-PS-cracked-tooth",
    "AAE-PS-diagnosis", "AAE-PS-implant-v-endo", "AAE-PS-isolation",
    "AAE-PS-microscope", "AAE-PS-obturation", "AAE-PS-regenerative",
    "AAE-PS-retreatment", "AAE-PS-safety", "AAE-PS-trauma",
    "AAE-PS-vital-pulp", "ESE-PS-VPT-2019", "ESE-QG-2006", "ESE-QG-2023",
]

# A1 — endodontic Cochrane reviews that are WITHDRAWN.
WITHDRAWN_CD = {
    "CD007997": "post-endodontic pain",
    "CD005408": "root fracture",
    "CD004623": "posts",
}


def q(sql, params=(), fetch=True):
    conn = rag.get_conn()
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return cur.fetchall() if fetch else None
    finally:
        cur.close()
        conn.close()


def stored_answers():
    """Every stored answer surface: curricula, the archive, and the cache."""
    docs = []
    for p in sorted(glob.glob("learn_history/*.json")):
        try:
            rec = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        docs.append((os.path.basename(p), rec.get("answer") or ""))
    for p in sorted(glob.glob("answers/*.txt")):
        docs.append((os.path.basename(p),
                     open(p, encoding="utf-8", errors="replace").read()))
    try:
        for i, a in q("SELECT id, answer FROM query_cache"):
            docs.append(("query_cache/%s" % i, a or ""))
    except Exception as e:
        print("[warn] query_cache unavailable: %s" % e)
    return docs


def cites(docs, token):
    """How many stored answers mention this identifier in any citation shape."""
    pat = re.compile(r"[\[\(]{1,2}\s*(?:PMID[:\s]*)?" + re.escape(token) +
                     r"\s*[\]\)]{1,2}", re.I)
    bare = re.compile(re.escape(token), re.I)
    n_slot = sum(1 for _n, t in docs if pat.search(t))
    n_any = sum(1 for _n, t in docs if bare.search(t))
    return n_slot, n_any


# ── A1 ───────────────────────────────────────────────────────────────
def a1(docs, out):
    print("\n" + "=" * 72)
    print("A1  WITHDRAWN COCHRANE REVIEWS")
    print("=" * 72)
    rows = []
    for cd, topic in WITHDRAWN_CD.items():
        # No `doi` column on this table (checked): a Cochrane CD number
        # reaches the library only inside the title or abstract.
        hits = q("SELECT pmid, left(title,64), level_key, score, journal, year "
                 "FROM endo_papers_rag "
                 "WHERE title ILIKE %s OR abstract ILIKE %s OR pmid = %s",
                 ("%" + cd + "%", "%" + cd + "%", cd))
        if not hits:
            print("  %-10s %-24s NOT IN LIBRARY" % (cd, topic))
            rows.append({"cd": cd, "topic": topic, "in_library": False})
            continue
        for pmid, title, lk, score, journal, year in hits:
            ns, na = cites(docs, pmid)
            print("  %-10s %-24s pmid=%-9s tier=%-9s score=%-6s year=%s"
                  % (cd, topic, pmid, lk, score, year))
            print("             cited in %d stored answer(s) (%d mention it at all)"
                  % (ns, na))
            print("             %s" % title)
            rows.append({"cd": cd, "topic": topic, "in_library": True,
                         "pmid": pmid, "level_key": lk, "score": score,
                         "year": year, "cited_in_answers": ns})
    out["a1"] = rows
    return rows


# ── A2 ───────────────────────────────────────────────────────────────
# Titles in this corpus are mostly ORGANISATION BOILERPLATE: "AAE Position
# Statement:", "European Society of Endodontology position statement:". A naive
# shared-word overlap therefore matches everything against everything — the
# first version of this audit paired AAE-PS-trauma with AAE-MICROSCOPES-2020
# and ESE-QG-2023 with ESE-RESORPTION-2023, which are not the same documents.
# Rule 33: the instrument has to be applied to the signal, not the packaging.
#
# The correction over-corrected. Stripping "quality / consensus / report" as
# boilerplate left ESE-QG-2006 with no content words at all, so it failed to
# match its OWN VERBATIM ID in the manifest. Third instrument error in this
# session, and the lesson is the same each time: one fuzzy score collapsed from
# several signals hides which signal actually fired.
#
# So this uses THREE INDEPENDENT SIGNALS and reports which one decided:
#
#   1. the slug's id appears verbatim in the manifest        -> definitive
#   2. a document on the same SUBJECT exists for that org    -> then compare
#      years, and name the real editions that do exist
#   3. neither                                                -> no such document
#
# The subject keyword is taken from the slug, which is legitimate: the slug is
# untrusted as an IDENTIFIER but it is a fair statement of what the record
# claims to be ABOUT, and the audit's question is whether a document on that
# subject exists at that year.
_SUBJECT = {
    "AAE-PS-antibiotics":    ("antibiotic",),
    "AAE-PS-cbct":           ("cone", "cbct", "tomograph"),
    "AAE-PS-cracked-tooth":  ("crack",),
    "AAE-PS-diagnosis":      ("diagnos", "terminolog"),
    "AAE-PS-implant-v-endo": ("implant",),
    "AAE-PS-isolation":      ("isolat", "rubber dam", "dam"),
    "AAE-PS-microscope":     ("microscop", "magnif"),
    "AAE-PS-obturation":     ("obturat", "root filling"),
    "AAE-PS-regenerative":   ("regenerat", "revitalis", "revitaliz"),
    "AAE-PS-retreatment":    ("retreat",),
    # "difficulty" and "standards" were in this list and matched
    # AAE-CASEDIFFICULTY-2022, which is a different document. A subject key has
    # to be specific enough that a false match is not possible.
    "AAE-PS-safety":         ("safety",),
    "AAE-PS-trauma":         ("trauma", "injur", "avuls"),
    "AAE-PS-vital-pulp":     ("vital pulp", "pulp"),
    "ESE-PS-VPT-2019":       ("vital pulp", "deep caries", "exposed pulp"),
    "ESE-QG-2006":           ("quality",),
    "ESE-QG-2023":           ("quality",),
}


def _subject_hits(seed, org, slug):
    keys = _SUBJECT.get(slug, ())
    out = []
    for g in seed:
        if (g.get("org") or "").upper() != org:
            continue
        t = (g.get("title") or "").lower()
        if any(k in t for k in keys):
            out.append(g)
    return out


def a2(docs, out):
    print("\n" + "=" * 72)
    print("A2  THE 16 HARDCODED RECORDS vs THE VERIFIED MANIFEST")
    print("=" * 72)
    seed = json.load(open(SEED, encoding="utf-8"))["guidelines"]

    rows = []
    print("%-22s %-9s %-6s %-5s %-5s %s"
          % ("slug", "tier", "score", "IF", "cited", "verdict against the manifest"))
    for slug in SLUGS:
        hit = q("SELECT pmid, title, level_key, score, impact_factor, year "
                "FROM endo_papers_rag WHERE pmid = %s", (slug,))
        ns, _na = cites(docs, slug)
        if not hit:
            print("%-22s %-9s %-6s %-5s %-5d %s"
                  % (slug, "-", "-", "-", ns, "(not in library)"))
            rows.append({"slug": slug, "in_library": False,
                         "cited_in_answers": ns})
            continue
        pmid, title, lk, score, iff, year = hit[0]
        org = slug.split("-")[0].upper()
        by_id = {g["id"]: g for g in seed}

        # Signal 1 — the id itself is in the manifest.
        if slug in by_id:
            g = by_id[slug]
            match_id, kind = g["id"], "match"
            verdict = "id is in the manifest: %s (%s)" % (g["id"], g.get("status"))
        else:
            # Signal 2 — does a document on this SUBJECT exist for this org?
            hits = _subject_hits(seed, org, slug)
            same_year = [g for g in hits if g.get("year") == year]
            if same_year:
                g = same_year[0]
                match_id, kind = g["id"], "match"
                verdict = "matches %s (%s)" % (g["id"], g.get("status"))
            elif hits:
                match_id, kind = hits[0]["id"], "wrong_year"
                verdict = ("WRONG YEAR — stored as %s; the real editions are %s"
                           % (year, ", ".join("%s (%s)" % (h["id"], h.get("status"))
                                              for h in hits)))
            else:
                match_id, kind = None, "no_match"
                verdict = ("NO SUCH DOCUMENT — no %s guideline on this subject "
                           "in a 60-entry manifest" % org)
        # INTERNAL CONSISTENCY — does the record's own title agree with its own
        # slug? ESE-PS-VPT-2019 is stored with the title "Outcome of Primary
        # Root Canal Treatment", which is neither vital pulp therapy nor what
        # the slug claims. A record that disagrees with itself cannot be
        # verified against anything.
        keys = _SUBJECT.get(slug, ())
        tl = (title or "").lower()
        self_consistent = (not keys) or any(k in tl for k in keys)
        if not self_consistent:
            verdict += "  [TITLE DISAGREES WITH ITS OWN SLUG]"

        print("%-22s %-9s %-6s %-5s %-5d %s"
              % (slug, lk, score, iff, ns, verdict))
        rows.append({"slug": slug, "in_library": True, "level_key": lk,
                     "score": score, "impact_factor": iff, "year": year,
                     "title": title, "cited_in_answers": ns,
                     "match": match_id, "kind": kind, "verdict": verdict})

    import collections
    kinds = collections.Counter(r.get("kind") for r in rows if r.get("in_library"))
    bad = [r for r in rows if r.get("kind") in ("no_match", "wrong_year")]
    print()
    print("  verified match to a real document : %d of 16" % kinds.get("match", 0))
    print("  WRONG YEAR (no such edition)      : %d" % kinds.get("wrong_year", 0))
    print("  NO SUCH DOCUMENT                  : %d" % kinds.get("no_match", 0))
    print("  stored answers citing a record that matches no real document: %d"
          % sum(r["cited_in_answers"] for r in bad))
    out["a2"] = rows
    out["a2_summary"] = {"match": kinds.get("match", 0),
                         "wrong_year": kinds.get("wrong_year", 0),
                         "no_match": kinds.get("no_match", 0),
                         "answers_citing_unverifiable":
                             sum(r["cited_in_answers"] for r in bad)}
    return rows


# ── A3 ───────────────────────────────────────────────────────────────
def a3(a2rows, out):
    print("\n" + "=" * 72)
    print("A3  SCORE CONTAMINATION")
    print("=" * 72)
    g_pmids = [r["slug"] for r in a2rows if r.get("in_library")]
    if not g_pmids:
        print("  no guideline rows in the library")
        out["a3"] = {}
        return

    grows = q("SELECT pmid, score FROM endo_papers_rag WHERE pmid = ANY(%s)",
              (g_pmids,))
    gscores = [float(s) for _p, s in grows if s is not None]
    ev = q("SELECT count(*), min(score), max(score), avg(score) "
           "FROM endo_papers_rag WHERE NOT (pmid = ANY(%s)) AND score IS NOT NULL",
           (g_pmids,))[0]
    n_ev, mn, mx, avg = ev
    print("  guideline rows : n=%d  min=%.1f  max=%.1f"
          % (len(gscores), min(gscores), max(gscores)))
    print("  evidence rows  : n=%d  min=%.1f  max=%.1f  mean=%.1f"
          % (n_ev, mn, mx, avg))

    lo = min(gscores)
    outranked = q("SELECT count(*) FROM endo_papers_rag "
                  "WHERE NOT (pmid = ANY(%s)) AND score IS NOT NULL AND score < %s",
                  (g_pmids, lo))[0][0]
    print()
    print("  THE SEVERITY NUMBER")
    print("  the LOWEST-scoring guideline row (%.1f) outranks %d of %d evidence "
          "rows (%.1f%%)" % (lo, outranked, n_ev, 100.0 * outranked / n_ev))
    hi = max(gscores)
    above_hi = q("SELECT count(*) FROM endo_papers_rag "
                 "WHERE NOT (pmid = ANY(%s)) AND score IS NOT NULL AND score >= %s",
                 (g_pmids, hi))[0][0]
    print("  evidence rows scoring at or above the HIGHEST guideline (%.1f): %d"
          % (hi, above_hi))

    # Named comparisons the handover cites.
    for name, like in (("Schwendicke Cochrane", "%Schwendicke%"),
                       ("Coll 2025", "%Coll %")):
        r = q("SELECT pmid, left(title,50), score, level_key FROM endo_papers_rag "
              "WHERE authors ILIKE %s ORDER BY score DESC LIMIT 2", (like,))
        for pmid, t, s, lk in r:
            print("    %-22s pmid=%-9s score=%-6s tier=%s" % (name, pmid, s, lk))
    out["a3"] = {"guideline_min": lo, "guideline_max": hi,
                 "evidence_rows": n_ev, "outranked_by_lowest": outranked,
                 "evidence_above_highest": above_hi}


# ── A4 ───────────────────────────────────────────────────────────────
def a4(out):
    print("\n" + "=" * 72)
    print("A4  impact_factor — READ or only WRITTEN?")
    print("=" * 72)
    n_if = q("SELECT count(*) FROM endo_papers_rag WHERE impact_factor IS NOT NULL")[0][0]
    n_all = q("SELECT count(*) FROM endo_papers_rag")[0][0]
    top = q("SELECT pmid, impact_factor, score FROM endo_papers_rag "
            "WHERE impact_factor IS NOT NULL ORDER BY impact_factor DESC LIMIT 8")
    print("  library rows carrying a stored impact_factor: %d of %d (%.1f%%)"
          % (n_if, n_all, 100.0 * n_if / n_all))
    print("  highest stored values:")
    for pmid, iff, sc in top:
        print("    %-22s IF=%-5s score=%s" % (pmid, iff, sc))
    out["a4"] = {"rows_with_if": n_if, "rows_total": n_all,
                 "top": [{"pmid": p, "if": f, "score": s} for p, f, s in top]}


# ── A5 ───────────────────────────────────────────────────────────────
# Every shape a citation slot takes on a rendered surface.
SLOT_RES = [
    re.compile(r"\[\[PMID:\s*([^\]\s]+)\s*\]\]"),
    re.compile(r"\[PMID:?\s*([^\]\s]+)\s*\]"),
    re.compile(r"\(PMID:?\s*([^)\s]+)\s*\)"),
]
# A bare parenthetical that looks like a library key, e.g. (ESE-QG-2023).
BARE_KEY_RE = re.compile(r"\(([A-Z]{2,6}-[A-Za-z0-9-]{2,40})\)")


def a5(docs, out):
    print("\n" + "=" * 72)
    print("A5  BARE-KEY LEAKS — citation slots holding a non-PMID identifier")
    print("=" * 72)
    import collections
    bad = collections.Counter()
    bad_docs = collections.defaultdict(set)
    slots = 0
    for name, text in docs:
        for rex in SLOT_RES:
            for m in rex.finditer(text):
                slots += 1
                ident = m.group(1).strip()
                if not ident.isdigit():
                    bad[ident] += 1
                    bad_docs[ident].add(name)
        for m in BARE_KEY_RE.finditer(text):
            ident = m.group(1).strip()
            if not ident.isdigit():
                bad[ident] += 1
                bad_docs[ident].add(name)

    print("  citation slots scanned across %d stored answers: %d" % (len(docs), slots))
    print("  slots holding a NON-PMID identifier: %d, across %d distinct identifiers"
          % (sum(bad.values()), len(bad)))
    print()
    # Split the two populations. A `(CBCT-measured)` or `(MTA-Angelus)` is an
    # ordinary hyphenated parenthetical my slot regex swept up, not a citation.
    # A key that RESOLVES TO A LIBRARY ROW is a real leak: the system emitted an
    # id_slug where a PMID belongs, and it renders.
    idents = list(bad)
    resolves = set()
    if idents:
        for (p,) in q("SELECT pmid FROM endo_papers_rag WHERE pmid = ANY(%s)",
                      (idents,)):
            resolves.add(p)

    real = {k: v for k, v in bad.items() if k in resolves}
    noise = {k: v for k, v in bad.items() if k not in resolves}
    print("  of those, resolving to a REAL LIBRARY ROW: %d slots across %d keys"
          % (sum(real.values()), len(real)))
    print("  not library keys at all (ordinary parentheticals, placeholders): "
          "%d slots across %d" % (sum(noise.values()), len(noise)))
    print()
    print("  %-26s %6s  %-9s %s" % ("identifier", "slots", "documents", "kind"))
    for ident, n in bad.most_common():
        kind = "LIBRARY KEY LEAK" if ident in resolves else "not a library key"
        print("  %-26s %6d  %-9d %s" % (ident, n, len(bad_docs[ident]), kind))
    out["a5"] = {"slots_scanned": slots,
                 "bad_slots": sum(bad.values()),
                 "library_key_slots": sum(real.values()),
                 "library_keys": len(real),
                 "noise_slots": sum(noise.values()),
                 "distinct": len(bad),
                 "by_identifier": {k: {"slots": v, "docs": len(bad_docs[k]),
                                       "resolves": k in resolves}
                                   for k, v in bad.most_common()}}


def main():
    docs = stored_answers()
    print("stored answer surfaces scanned: %d" % len(docs))
    out = {}
    a1(docs, out)
    rows = a2(docs, out)
    a3(rows, out)
    a4(out)
    a5(docs, out)
    if "--json" in sys.argv:
        p = sys.argv[sys.argv.index("--json") + 1]
        json.dump(out, open(p, "w", encoding="utf-8"), indent=1, default=str)
        print("\nwrote %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
