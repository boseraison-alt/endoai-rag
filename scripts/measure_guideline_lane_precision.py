"""Item B (2026-09-06 night batch) — the guideline lane, measured for PRECISION.

THIS IS THE INSTRUMENT YESTERDAY'S MEASUREMENT LACKED.

`scripts/measure_guideline_lane_query.py` counted whether the lane returned
something: "empty rate 79% -> 3%, 22 questions gain a guideline, 0 lose one."
Every one of those numbers is true and none of them asks whether what came back
was the right document. A vascular-surgery guideline and a feline veterinary
dental guideline were reaching endodontic pools while that number improved.

So this script looks at WHAT came back. For each of the 32 questions (29 eval +
3 probes) it reports:

  * the AND-group the lane chose as "the subject"
  * whether that group contains a DOMAIN NOUN
  * the guideline-lane pool size
  * every guideline in the pool, with journal and title
  * a yes/no OFF-DOMAIN judgement per row, with the reason printed

Off-domain, per the batch's definition:
  (a) the subject population is non-human, OR
  (b) the issuing body and journal are outside dentistry / oral medicine /
      head-and-neck medicine AND the document does not address oral or
      dental care.

TERMS ARE GENERATED ONCE AND CACHED. `generate_search_terms` is a live Haiku
call and is not deterministic. Running it separately for the before and after
arms would move two things at once — the topic rule AND the terms it is applied
to — which is the same mistake in a different place. The cache file is the
fixed point both arms are measured against.

Usage:
    python scripts/measure_guideline_lane_precision.py --arm before
    python scripts/measure_guideline_lane_precision.py --arm after
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E  # noqa: E402

TERMS_CACHE = Path("eval/logs/night8_terms.json")

# The three probes, verbatim clinical stems. Recorded here so the run is
# reproducible rather than retyped each session.
PROBES = [
    ("probe-avulsion-40min",
     "Avulsed maxillary central incisor with a closed apex, replanted after "
     "40 minutes of extra-oral dry time. How should it be managed and what is "
     "the prognosis?"),
    ("probe-crown-fracture-6h",
     "Complicated crown fracture with pulp exposure in a mature premolar, "
     "6 hours old. What is the management?"),
    ("probe-retreat-implant",
     "Mature molar with a failed root canal retreatment. The patient asks for "
     "extraction and an implant. How should this be decided?"),
]

# ── DOMAIN NOUNS ─────────────────────────────────────────────────────────
# The candidate list, used to answer "does the chosen group contain a domain
# noun". After the fix ships, the shipped list is preferred and any difference
# is printed rather than silently absorbed.
CANDIDATE_DOMAIN_NOUNS = {
    "pulp", "pulpal", "pulpitis", "periapical", "periradicular", "apical",
    "root canal", "root canals", "endodontic", "endodontics", "endodontically",
    "avulsion", "avulsed", "luxation", "crown fracture", "root fracture",
    "resorption", "revascularisation", "revascularization", "revitalisation",
    "revitalization", "pulpotomy", "pulpectomy", "pulp cap", "pulp capping",
    "obturation", "irrigation", "irrigant", "retreatment", "apicectomy",
    "apicoectomy", "perforation", "replantation", "replanted", "dental trauma",
    "traumatic dental injur", "apexification", "apexogenesis",
    "dens invaginatus", "dens evaginatus", "odontogenic", "periodontitis",
    "necrotic pulp", "necrosis", "intracanal", "post-treatment disease",
}

_OFFDOMAIN_SPECIES = re.compile(
    r"\b(feline|felis|cat|cats|canine model|dog|dogs|equine|horse|bovine|"
    r"porcine|swine|murine|rat|rats|mouse|mice|rabbit|primate|veterinary|"
    r"zoo|avian|ferret)\b", re.I)

_DENTAL_JOURNAL = re.compile(
    r"(dent|oral|endod|periodont|orthod|prosthodont|maxillofac|craniofac|"
    r"stomatol|odontol|traumatol|j\s*am\s*dent|jada|caries)", re.I)

_DENTAL_TITLE = re.compile(
    r"\b(dental|dentist\w*|oral|tooth|teeth|endodont\w*|periodont\w*|pulp\w*|"
    r"caries|periapical|root canals?|maxillofacial|orthodont\w*|"
    r"prosthodont\w*|gingiv\w*|odontogenic|jaw|mandib\w*|maxill\w*)\b", re.I)

# THE STRICTER LIST, USED ONLY TO EXONERATE A CROSS-SPECIALTY DOCUMENT.
#
# Exonerating is the dangerous direction: it says "this vascular-surgery
# guideline belongs in an endodontic pool". So it requires vocabulary that
# CANNOT mean anything else. The broad list above is fine for a title, where
# "oral" is the cavity, and wrong for an abstract, where it is a route of
# administration. Measured, not assumed — the loose version exonerated two
# documents on these two matches alone:
#
#   "the most inferior part of the temp|oral| lobes"     -> `oral`
#   "no need to include sacral |root canals| in the CTV" -> `root canal`
#
# Both are in the SIOPE paediatric brain-tumour radiotherapy guideline, and
# the second one is also HOW THAT DOCUMENT REACHES AN ENDODONTIC POOL AT ALL:
# `ENDO_DOMAIN_FILTER` carries `"root canal"[tiab]`, and a spinal nerve root
# canal matches it. Reported as a finding in its own right.
_DENTAL_UNAMBIGUOUS = re.compile(
    r"\b(dental|dentist\w*|tooth|teeth|endodont\w*|periodont\w*|caries|"
    r"periapical|gingiv\w*|odontogenic|oral (?:cavity|mucosa|surgery|health|"
    r"hygiene)|dental pulp|maxillofacial|osteonecrosis of the jaw)\b", re.I)

# The four documents the 2026-09-11 handover named, plus the two found tonight.
# Tracked by PMID across both arms so the fix is judged on the actual documents
# the complaint was about, not only on a label.
WATCHLIST = {
    "41319038": "FelineVMA feline dental guidelines (veterinary)",
    "29268916": "Society for Vascular Surgery, abdominal aortic aneurysm",
    "29729847": "SIOPE paediatric brain-tumour craniospinal radiotherapy",
    "17446442": "AHA infective endocarditis 2007 (superseded by AHA-IE-2021)",
}


def judge_off_domain(title, journal, abstract=""):
    """(is_off_domain, reason). Both halves of the batch's definition.

    THE SECOND HALF IS AN **AND**, AND THE FIRST VERSION OF THIS FUNCTION
    IGNORED IT. It judged off-domain on "journal outside dentistry AND no
    dental word in the TITLE", which convicted PMID 17446442 — the AHA
    infective-endocarditis guideline, whose entire clinical content is
    antibiotic prophylaxis BEFORE DENTAL PROCEDURES, and whose 2021 successor
    is a legitimate record in this project's own manifest (AHA-IE-2021). It is
    a cross-specialty guideline that addresses dental care, which the batch's
    definition explicitly protects. Convicting it inflated the off-domain count
    by 13 of 48.

    So the document's OWN TEXT gets the second half of the test: a guideline
    published outside dentistry is off-domain only if it also fails to address
    oral or dental care.
    """
    t, j, a = title or "", journal or "", abstract or ""
    m = _OFFDOMAIN_SPECIES.search(t)
    if m and not re.search(r"\bcanine (tooth|teeth)\b", t, re.I):
        # `canine` alone is a human tooth in this corpus (animal_subjects.py
        # measured 32 rows, 1 animal). Only `canine model` is a cue, and it is
        # in the pattern explicitly.
        return True, "non-human subject population: %r in the title" % m.group(0)
    if _DENTAL_JOURNAL.search(j) or _DENTAL_TITLE.search(t):
        return False, ""
    # Journal and title are both outside the domain. Does the DOCUMENT address
    # oral or dental care? Counted, not eyeballed, and counted with the strict
    # vocabulary: a passing mention is not enough, so require two.
    hits = _DENTAL_UNAMBIGUOUS.findall(a)
    if len(hits) >= 2:
        return False, ("cross-specialty but DOES address dental care: %d "
                       "unambiguous dental mentions in its own abstract (%s)"
                       % (len(hits), ", ".join(sorted({h.lower() for h in hits
                                                       if isinstance(h, str)
                                                       })[:5])))
    return True, ("issuing journal %r is outside dentistry / oral medicine / "
                  "head-and-neck, and the document does not address oral or "
                  "dental care (%d unambiguous dental mentions in its abstract)"
                  % (j or "(unknown)", len(hits)))


def lane_filter():
    for key, terms, _label in E.tier_query_lanes():
        if key == "guideline":
            return " OR ".join(terms)
    raise SystemExit("no guideline lane in tier_query_lanes()")


def load_or_make_terms(cases):
    cache = {}
    if TERMS_CACHE.exists():
        cache = json.loads(TERMS_CACHE.read_text(encoding="utf-8"))
    made = 0
    for cid, q in cases:
        if cid not in cache:
            cache[cid] = E.generate_search_terms(q)
            made += 1
            time.sleep(0.2)
    if made:
        TERMS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        TERMS_CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    print("  term groups: %d from cache, %d newly generated (%s)"
          % (len(cache) - made, made, TERMS_CACHE))
    return cache


def esearch(term, retmax=20):
    try:
        r = E.ncbi_get(f"{E.NCBI_EUTILS_BASE}/esearch.fcgi",
                       params=E._ncbi_params({"db": "pubmed", "term": term,
                                              "retmode": "json",
                                              "sort": "relevance",
                                              "retmax": retmax}), timeout=25)
        d = r.json().get("esearchresult", {})
        return [str(i) for i in d.get("idlist", [])], int(d.get("count", 0))
    except Exception as ex:
        print("      esearch failed: %s" % ex)
        return [], -1


def summaries(pmids):
    """{pmid: (title, journal, abstract)}.

    Abstract included deliberately. The off-domain test's second half asks
    whether the DOCUMENT addresses oral or dental care, and a title alone
    cannot answer that: the AHA infective-endocarditis guideline is titled
    entirely in cardiology vocabulary and is about antibiotic prophylaxis
    before dental procedures. Judging on the title was what convicted it.

    esummary carries no abstract, so this goes through the repo's own efetch
    client, which returns title, journal and abstract in one call.
    """
    if not pmids:
        return {}
    out = {}
    try:
        recs = E._fetch_pubtypes_and_abstracts(list(pmids))
        for p in pmids:
            r = recs.get(p) or {}
            out[p] = (r.get("title", "") or "", r.get("journal", "") or "",
                      r.get("abstract", "") or "")
    except Exception as ex:
        print("      efetch failed: %s" % ex)
    for p in pmids:
        out.setdefault(p, ("", "", ""))
    return out


def domain_nouns():
    shipped = getattr(E, "DOMAIN_NOUNS", None)
    if shipped:
        only_shipped = set(shipped) - CANDIDATE_DOMAIN_NOUNS
        only_cand = CANDIDATE_DOMAIN_NOUNS - set(shipped)
        if only_shipped or only_cand:
            print("  NOTE: shipped DOMAIN_NOUNS differs from this script's "
                  "candidate list")
            print("        only in shipped: %s" % sorted(only_shipped))
            print("        only in script : %s" % sorted(only_cand))
        return set(shipped), "endo_ai.DOMAIN_NOUNS (shipped)"
    return set(CANDIDATE_DOMAIN_NOUNS), "script candidate list (fix not yet shipped)"


def has_domain_noun(group_terms, nouns):
    for t in group_terms:
        s = t.rstrip("*").strip().lower()
        for n in nouns:
            if s == n or s.startswith(n) or n in s:
                return True, n
    return False, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="before", choices=["before", "after"])
    ap.add_argument("--json", dest="json_out", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    cases = [(c["id"], c["question"])
             for c in json.load(open("eval/questions.json"))["cases"]]
    cases += PROBES
    if args.limit:
        cases = cases[:args.limit]

    print("=" * 78)
    print("ITEM B — GUIDELINE LANE PRECISION,  ARM = %s" % args.arm.upper())
    print("=" * 78)
    nouns, noun_src = domain_nouns()
    print("  domain-noun list: %d terms, source: %s" % (len(nouns), noun_src))
    print("  %s" % ", ".join(sorted(nouns)))
    print()
    terms = load_or_make_terms(cases)
    filt = lane_filter()
    print("  guideline lane filter: %s" % filt)
    print()

    rows = []
    for i, (cid, _q) in enumerate(cases, 1):
        smart = terms[cid]
        groups = E.parse_search_term_groups(smart)
        chosen = E.guideline_topic(smart)
        chosen_terms = [x.strip() for x in re.split(r"\s+OR\s+", chosen,
                                                    flags=re.I) if x.strip()]
        ok, which = has_domain_noun(chosen_terms, nouns)
        query = (f"({chosen}) AND ({filt}) AND {E.ENDO_DOMAIN_FILTER} "
                 f'NOT "Retracted Publication"[pt]')
        pmids, total = esearch(query)
        meta = summaries(pmids)
        pool = []
        for p in pmids:
            title, journal, abstract = meta.get(p, ("", "", ""))
            off, reason = judge_off_domain(title, journal, abstract)
            pool.append({"pmid": p, "title": title, "journal": journal,
                         "off_domain": off, "reason": reason,
                         "cross_specialty_kept": (not off and reason != "")})
        n_off = sum(1 for x in pool if x["off_domain"])
        rows.append({"id": cid, "n_groups": len(groups),
                     "chosen": chosen, "has_domain_noun": ok,
                     "domain_noun": which, "pool": len(pool),
                     "total_hits": total, "off_domain": n_off,
                     "query": query, "rows": pool})
        print("[%2d/%d] %-40s groups=%d  domain_noun=%-5s  pool=%-3d off=%d"
              % (i, len(cases), cid[:40], len(groups), ok, len(pool), n_off))
        print("        chose: %s" % chosen[:110])
        for x in pool:
            if x["off_domain"]:
                print("        OFF-DOMAIN  %s  %s" % (x["pmid"], x["title"][:70]))
                print("                    journal: %s" % x["journal"][:70])
                print("                    reason : %s" % x["reason"][:100])

    n = len(rows)
    n_noun = sum(1 for r in rows if r["has_domain_noun"])
    n_empty = sum(1 for r in rows if r["pool"] == 0)
    tot_off = sum(r["off_domain"] for r in rows)
    q_off = [r["id"] for r in rows if r["off_domain"]]
    print()
    print("=" * 78)
    print("RESULT — ARM %s" % args.arm.upper())
    print("=" * 78)
    print("  questions measured                         %d" % n)
    print("  chosen group CONTAINS a domain noun        %d  (target >= 30)"
          % n_noun)
    print("  chosen group contains NONE                 %d" % (n - n_noun))
    for r in rows:
        if not r["has_domain_noun"]:
            print("      no domain noun: %-40s chose %s"
                  % (r["id"][:40], r["chosen"][:60]))
    print("  guideline-lane pool EMPTY                  %d  (%.0f%%, target <= 15%%)"
          % (n_empty, 100.0 * n_empty / max(1, n)))
    print("  OFF-DOMAIN guideline rows in any pool      %d  (target 0)" % tot_off)
    print("  questions with >=1 off-domain row          %d  %s"
          % (len(q_off), q_off))
    kept = [(x["pmid"], x["title"][:60], x["reason"])
            for r in rows for x in r["rows"] if x.get("cross_specialty_kept")]
    print("  cross-specialty rows KEPT (not off-domain) %d" % len(kept))
    for pmid, title, reason in sorted(set(kept)):
        print("      %-9s %-60s" % (pmid, title))
        print("                %s" % reason)

    # THE WATCHLIST. The off-domain label is a judgement; an appearance count
    # is not. These are the documents the complaint was actually about, so
    # they are counted whatever the label says about them.
    print()
    print("  WATCHLIST — appearances across the 32 pools")
    for pmid, what in sorted(WATCHLIST.items()):
        n = sum(1 for r in rows for x in r["rows"] if x["pmid"] == pmid)
        qs = [r["id"] for r in rows
              if any(x["pmid"] == pmid for x in r["rows"])]
        off = any(x["off_domain"] for r in rows for x in r["rows"]
                  if x["pmid"] == pmid)
        print("    %-9s %-58s %2d pools  off_domain=%s"
              % (pmid, what, n, off))
        if qs:
            print("              %s" % ", ".join(qs[:6])
                  + (" ..." if len(qs) > 6 else ""))
    print()
    print("  AVULSION PROBE — the lane's final PubMed query string:")
    for r in rows:
        if r["id"] == "probe-avulsion-40min":
            print("    %s" % r["query"])

    out = args.json_out or ("eval/reports/night8_item_b_%s.json" % args.arm)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(rows, open(out, "w"), indent=1)
    print("\n  wrote %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
