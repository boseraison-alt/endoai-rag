"""Item E (2026-09-08) — the harm already in the archive.

The label and the prompt sentence change what Curo writes NEXT. This measures
what it already wrote: stored answers that cite one of the 86 animal-subject
rows in a sentence that never says the subjects were animals.

That is the harm in its exact form. Not "an animal study was cited" — citing one
is legitimate and often the only evidence there is — but "an animal study was
cited as though it were clinical evidence", where a clinician would have to open
the reference to discover the finding came from a rat.

Every corpus is counted OUT LOUD before anything is reported. On 2026-09-06 a
measurement of stored answers missed `answers/` entirely — 170 files — and
reported a clean zero. A zero is only meaningful beside the size of the input
that produced it (rule 34).

    python scripts/measure_animal_citation_harm.py
"""
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

# Words that, in the citing sentence, tell the reader the subjects were animals.
SPECIES_WORDS = re.compile(
    r"\b(animal|animals|in vivo model|dog|dogs|canine|beagle|rat|rats|mouse|"
    r"mice|murine|monkey|monkeys|primate|primates|macaque|baboon|bovine|cow|"
    r"cows|cattle|calf|calves|pig|pigs|porcine|swine|minipig|sheep|ovine|lamb|"
    r"rabbit|rabbits|cat|cats|feline|ferret|ferrets|horse|equine|guinea pig|"
    r"hamster|preclinical|pre-clinical)\b", re.I)

CITE = re.compile(r"\[\[PMID:(\d+)\]\]|\[PMID:\s*(\d+)\]")

# A REFERENCE-LIST LINE IS NOT A CLAIM.
#
# The bibliography names every cited paper by title and authors; a species word
# is not expected there and its absence harms nobody. Counting those lines
# alongside prose inflates the harm and would let the fix look bigger than it
# is. They are counted separately and reported separately.
REF_LINE = re.compile(
    r"^\s*(\d+[.)]\s*)?\[PMID:\s*\d+\]"      # "1. [PMID: n] Author..."
    r"|^\s*\[PMID:\s*\d+\]", re.I)


def sentences(text):
    return re.split(r"(?<=[.!?])\s+", text or "")


def corpora():
    """Every place a served answer is stored. Named and counted individually."""
    out = {}
    d = ROOT / "answers"
    out["answers/"] = sorted(d.glob("*.txt")) if d.exists() else []
    d = ROOT / "eval" / "logs" / "case_answers"
    out["eval/logs/case_answers/"] = sorted(d.glob("*")) if d.exists() else []
    d = ROOT / "eval" / "logs" / "curricula"
    out["eval/logs/curricula/"] = sorted(d.glob("*")) if d.exists() else []
    return out


RENDERED = "--rendered" in sys.argv


def _maybe_render(text):
    """Item C: measure the text as SERVED, not as stored.

    Stored answers are never rewritten — the archive is a record of what was
    said. The species label is applied by the finaliser on the way out, so the
    only honest "after" number is the one taken from rendered text.
    """
    if not RENDERED:
        return text
    try:
        import endo_ai as _E
        out = _E.finalise_answer_text(text)
        return out[0] if isinstance(out, tuple) else out
    except Exception:
        return text


def main():
    conn = rag.get_conn()
    cur = conn.cursor()
    cur.execute("""SELECT pmid, animal_subject, title FROM endo_papers_rag
                   WHERE COALESCE(animal_subject,'') <> ''""")
    animal = {p: (s, t) for p, s, t in cur.fetchall()}

    print("=" * 78)
    print("ITEM E — ANIMAL STUDIES CITED WITHOUT SAYING SO")
    print("=" * 78)
    print("  animal-subject rows in the library: %d" % len(animal))
    print()
    print("  CORPORA COUNTED (rule 34 — a zero means nothing without these)")
    files = corpora()
    for name, fs in files.items():
        print("    %-28s %4d files" % (name, len(fs)))
    cur.execute("SELECT COUNT(*) FROM query_cache")
    n_cache = cur.fetchone()[0]
    print("    %-28s %4d rows" % ("query_cache", n_cache))
    print()

    hits, refs, cited_total, docs = [], [], 0, 0

    def scan(label, ident, text):
        nonlocal cited_total, docs
        docs += 1
        text = _maybe_render(text)
        for sent in sentences(text):
            for m in CITE.finditer(sent):
                pmid = m.group(1) or m.group(2)
                if pmid not in animal:
                    continue
                cited_total += 1
                if REF_LINE.match(sent):
                    refs.append(pmid)
                    continue
                if not SPECIES_WORDS.search(sent):
                    hits.append({"corpus": label, "id": ident, "pmid": pmid,
                                 "species": animal[pmid][0],
                                 "title": animal[pmid][1][:70],
                                 "sentence": " ".join(sent.split())[:220]})

    for name, fs in files.items():
        for f in fs:
            try:
                scan(name, f.name, f.read_text(encoding="utf-8",
                                               errors="replace"))
            except Exception:
                pass
    cur.execute("SELECT id, question_text, answer FROM query_cache")
    for rid, q, ans in cur.fetchall():
        scan("query_cache", "id=%s" % rid, ans or "")

    print("  documents scanned                      : %d" % docs)
    print("  citations OF an animal-subject row     : %d" % cited_total)
    print("    of those, reference-list lines       : %d  (not a claim)"
          % len(refs))
    print("    of those, PROSE CLAIMS               : %d"
          % (cited_total - len(refs)))
    print("  PROSE CLAIMS WITH NO SPECIES WORD      : %d" % len(hits))
    print()
    if hits:
        print("  THE HARM, in the citing sentence:")
        for h in hits[:25]:
            print("    %s  %s  (%s)" % (h["pmid"], h["corpus"], h["species"]))
            print("      %s" % h["title"])
            print("      \"%s\"" % h["sentence"])
            print()
    else:
        print("  None found. Note the denominator above: this is a real zero")
        print("  only if `citations OF an animal-subject row` is non-zero.")

    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump({"animal_rows": len(animal), "documents": docs,
               "citations_of_animal_rows": cited_total,
               "reference_list_lines": len(refs),
               "prose_claims": cited_total - len(refs),
               "without_species_word": len(hits), "hits": hits},
              open("eval/reports/night10_animal_harm.json", "w",
                   encoding="utf-8"), indent=1)
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
