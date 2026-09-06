"""Retire the two legacy rows whose stored text is a model-written paraphrase.

THE DEFECT. `ingest_aae_guidelines.py` wrote its records with summaries that
its own docstring calls "condensed from the official documents" — paraphrases
stored as source text. `verify_citation_support` has therefore been checking
claims against a model's words, which is a hole directly under the grounding
guarantee. Two survive, kept citeable by the A2 audit because they name real
documents:

    AAE-PS-vital-pulp   ->  AAE-VPT-2021        (now carries AAE's own text)
    AAE-PS-diagnosis    ->  AAE-DIAGNOSIS-2009

WHY THEY CAN BE RETIRED NOW AND NOT BEFORE. Each is the same document as a
manifest record under a different key, and until 2026-09-07 the manifest record
was itself a bare pointer — retiring the paraphrase would have replaced text
with no text. `AAE-VPT-2021` now carries the AAE's own words, fetched through
RB's Chrome session. The exchange is a paraphrase for the document.

The redirect targets are the manifest's own: its note on AAE-DIAGNOSIS-2009
reads "'AAE-PS-diagnosis]' leaking into Case citation slots resolves to
AAE-DIAGNOSIS-2009."

MECHANISM. Exactly item A's retire, and deliberately not a new one:
`quarantine_reason` takes the row out of retrieval, `redirect_to` names its
replacement so stored citations still resolve, `guideline_id` is cleared.
Nothing is deleted.

THIS IS NOT THE INGEST'S RE-KEY STEP. That step walks manifest records; these
two rows have no manifest record of their own, which is why they were left
behind by it.

    python scripts/retire_legacy_paraphrase_rows.py            # DRY RUN
    python scripts/retire_legacy_paraphrase_rows.py --apply
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import rag  # noqa: E402

RETIRE = {
    "AAE-PS-vital-pulp": "AAE-VPT-2021",
    "AAE-PS-diagnosis": "AAE-DIAGNOSIS-2009",
}


def corpora():
    out = {}
    conn = rag.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, answer, papers FROM query_cache")
    out["query_cache"] = [("query_cache#%s" % r[0],
                           (r[1] or "") + "\n" + json.dumps(r[2] or {}))
                          for r in cur.fetchall()]
    cur.close()
    conn.close()
    for label, pat in (("answers/", "answers/*.txt"),
                       ("eval/logs/case_answers/",
                        "eval/logs/case_answers/*.md")):
        items = []
        for p in sorted(Path(".").glob(pat)):
            try:
                items.append((str(p), p.read_text(encoding="utf-8",
                                                  errors="replace")))
            except Exception:
                pass
        out[label] = items
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    print("=" * 78)
    print("RETIRE THE TWO LEGACY PARAPHRASE ROWS  (%s)"
          % ("APPLY" if args.apply else "DRY RUN"))
    print("=" * 78)

    # ── 1. MEASURE FIRST: who cites each legacy key ──
    c = corpora()
    print("  THE INPUT")
    for k, v in c.items():
        print("    %-26s %4d stored answers" % (k, len(v)))
    print("    %-26s %4d TOTAL" % ("", sum(len(v) for v in c.values())))
    print()
    print("  STORED ANSWERS CITING EACH LEGACY KEY")
    per_key = {}
    for key in RETIRE:
        rx = re.compile(r"(?<![A-Za-z0-9-])%s(?![A-Za-z0-9-])" % re.escape(key))
        hits = []
        for corpus, items in c.items():
            for name, text in items:
                n = len(rx.findall(text))
                if n:
                    hits.append((name, n))
        per_key[key] = hits
        print("    %-22s %3d answer(s), %3d citation(s)"
              % (key, len(hits), sum(n for _f, n in hits)))
        for name, n in hits[:6]:
            print("        %-58s x%d" % (name[:58], n))
        if len(hits) > 6:
            print("        ... and %d more" % (len(hits) - 6))
    print()

    # ── 2. the targets must be citeable, or the redirect breaks the citation ──
    conn = rag.get_conn()
    cur = conn.cursor()
    print("  REDIRECT TARGETS")
    ok = True
    for src, dst in RETIRE.items():
        cur.execute("""SELECT pmid, COALESCE(quarantine_reason,''),
                              COALESCE(abstract_source,''),
                              LEFT(COALESCE(abstract,''), 44), level_key
                       FROM endo_papers_rag WHERE pmid = %s""", (dst,))
        row = cur.fetchone()
        if not row:
            print("    %-22s -> %-22s TARGET MISSING" % (src, dst))
            ok = False
            continue
        _p, quar, asrc, head, lk = row
        citeable = not quar.strip()
        has_text = bool(head.strip()) and not head.startswith("GUIDELINE RECORD")
        print("    %-22s -> %-22s citeable=%-5s source=%-18s tier=%s"
              % (src, dst, citeable, asrc or "-", lk))
        print("        %s" % head.replace("\n", " ")[:70])
        if not citeable:
            print("        REFUSED: target is quarantined; the redirect would "
                  "resolve to nothing")
            ok = False
        if not has_text:
            print("        NOTE: target is still a pointer — this trades a "
                  "paraphrase for no text")
    if not ok:
        print("\n  REFUSED. Nothing written.")
        return 1
    print()

    # ── 3. the delta ──
    cur.execute("""SELECT pmid, COALESCE(quarantine_reason,''),
                          COALESCE(abstract_source,''), redirect_to
                   FROM endo_papers_rag WHERE pmid = ANY(%s)""",
                (list(RETIRE),))
    before = {r[0]: r for r in cur.fetchall()}
    cur.execute("""SELECT COUNT(*) FROM endo_papers_rag
                   WHERE abstract_source = 'model_summary_legacy'
                     AND COALESCE(quarantine_reason,'') = ''""")
    citeable_paraphrase_before = cur.fetchone()[0]

    to_write = [s for s in RETIRE
                if s in before and not before[s][1].strip()]
    print("  PLAN")
    print("    rows to retire                        %d" % len(to_write))
    for s in to_write:
        print("        %-22s -> redirect_to %s" % (s, RETIRE[s]))
    print("    citeable model_summary_legacy rows    %d -> %d"
          % (citeable_paraphrase_before,
             citeable_paraphrase_before - len(to_write)))
    already = [s for s in RETIRE if s in before and before[s][1].strip()]
    if already:
        print("    already quarantined, untouched        %s" % already)

    if args.apply and to_write:
        for s in to_write:
            cur.execute("""
                UPDATE endo_papers_rag SET
                    quarantine_reason = %s,
                    redirect_to = %s,
                    guideline_id = ''
                WHERE pmid = %s
            """, ("re-keyed: this document is %s; the text stored here was a "
                  "model-written summary, not the document's own words"
                  % RETIRE[s], RETIRE[s], s))
        conn.commit()

    # ── 4. verify ──
    cur.execute("""SELECT pmid, COALESCE(quarantine_reason,''), redirect_to,
                          COALESCE(guideline_id,'')
                   FROM endo_papers_rag WHERE pmid = ANY(%s) ORDER BY pmid""",
                (list(RETIRE),))
    print()
    print("  AFTER" if args.apply else "  CURRENT (unchanged — dry run)")
    for pmid, quar, redirect, gid in cur.fetchall():
        print("    %-22s quar=%-5s redirect_to=%-22s gid=%r"
              % (pmid, bool(quar.strip()), redirect or "-", gid))
    cur.execute("""SELECT COUNT(*) FROM endo_papers_rag
                   WHERE abstract_source = 'model_summary_legacy'
                     AND COALESCE(quarantine_reason,'') = ''""")
    print("    citeable model_summary_legacy rows: %d" % cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM endo_papers_rag")
    print("    total rows: %d" % cur.fetchone()[0])

    print()
    print("  %s" % ("APPLIED." if args.apply else
                    "DRY RUN — nothing written."))
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
