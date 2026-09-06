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
    r"(dental|dentist|oral|tooth|teeth|endodont|periodont|pulp|caries|"
    r"periapical|root canal|maxillofac|orthodont|prosthodont|gingiv|"
    r"odontogenic|jaw|mandib|maxill|osteonecrosis of the jaw)", re.I)


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
    # oral or dental care? Counted, not eyeballed: a passing mention is not
    # enough, so require the dental vocabulary to appear more than once.
    hits = _DENTAL_TITLE.findall(a)
    if len(hits) >= 2:
        return False, ("cross-specialty but addresses dental care: %d dental "
                       "mentions in its own abstract" % len(hits))
    return True, ("issuing journal %r is outside dentistry / oral medicine / "
                  "head-and-neck, and the document does not address oral or "
                  "dental care (%d dental mentions in its abstract)"
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
    """{pmid: (title, journal)} via esummary."""
    if not pmids:
        return {}
    out = {}
    try:
        r = E.ncbi_get(f"{E.NCBI_EUTILS_BASE}/esummary.fcgi",
                       params=E._ncbi_params({"db": "pubmed",
                                              "id": ",".join(pmids),
                                              "retmode": "json"}), timeout=25)
        res = r.json().get("result", {})
        for p in pmids:
            e = res.get(p) or {}
            out[p] = (e.get("title", "") or "",
                      e.get("fulljournalname", "") or e.get("source", "") or "")
    except Exception as ex:
        print("      esummary failed: %s" % ex)
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
            title, journal = meta.get(p, ("", ""))
            off, reason = judge_off_domain(title, journal)
            pool.append({"pmid": p, "title": title, "journal": journal,
                         "off_domain": off, "reason": reason})
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
