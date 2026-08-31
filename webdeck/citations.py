"""Citation handling for the web deck.

Two jobs, both governed by §1.3 of the worklist:

  * Raw `[[PMID:N]]` markers must NEVER reach a slide. They are the engine's
    provenance markers, not prose, and `templates/index.html` already turns
    them into author-style pills for the answer view. The deck does the same
    thing so the two surfaces read alike (§3.2).
  * Every content slide's footer carries the short citations for the evidence
    on that slide, in the §1.3 shape:
        "Schulte-Lünzum et al. 2017 · Photomedicine and Laser Surgery · n = 100 · PMID 28294701"

Nothing here writes clinical text. It reformats metadata that already came
from PubMed and moves markers out of the body into pills.
"""
from __future__ import annotations

import html
import re

PMID_MARKER = re.compile(r"\[\[PMID:\s*(\d+)\s*\]\]")
# The engine also emits the single-bracket form in reference blocks.
PMID_BRACKET = re.compile(r"\[PMID:\s*(\d+)\s*\]")
PMID_BARE    = re.compile(r"\bPMID[:\s]+(\d+)\b", re.I)


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def extract_pmids(value) -> list[str]:
    """Every PMID mentioned anywhere in a nested spec value, in first-seen order."""
    found: list[str] = []
    seen: set[str] = set()

    def walk(v):
        if isinstance(v, str):
            for pat in (PMID_MARKER, PMID_BRACKET, PMID_BARE):
                for m in pat.finditer(v):
                    p = m.group(1)
                    if p not in seen:
                        seen.add(p)
                        found.append(p)
        elif isinstance(v, dict):
            for item in v.values():
                walk(item)
        elif isinstance(v, (list, tuple)):
            for item in v:
                walk(item)

    walk(value)
    return found


def format_cite(pmid: str, papers: dict) -> str:
    """The app's inline pill label, ported from `formatCite` in index.html.

    Kept deliberately close to the JS so a clinician reading the deck sees the
    same string the answer view showed them. Falls back to "PMID N" when the
    metadata is missing, exactly as the app does.
    """
    p = papers.get(str(pmid)) or {}
    authors = (p.get("authors") or "").strip()
    journal = (p.get("journal_abbrev") or p.get("journal") or "").strip()
    if not (authors or journal):
        return f"PMID {pmid}"

    auth = ""
    if authors:
        has_et_al = bool(re.search(r"et al", authors, re.I))
        names = [a.strip() for a in
                 re.split(r"[;,]", re.sub(r",?\s*et al\.?", "", authors, flags=re.I))
                 if a.strip()]
        auth = (f"{names[0]} et al." if names else "et al.") \
            if (has_et_al or len(names) > 3) else ", ".join(names)

    if len(journal) > 28:
        journal = journal[:26] + "…"

    tail = ""
    year = str(p.get("year") or "").strip()
    if year and year.lower() != "unknown":
        tail = year
        if p.get("volume"):
            tail += f";{p['volume']}" + (f"({p['issue']})" if p.get("issue") else "")
            if p.get("pages"):
                tail += f":{p['pages']}"

    parts = [auth, f"{journal}." if journal else "", tail]
    return re.sub(r"\.,", ".,", ", ".join(x for x in parts if x))


def footer_citation(pmid: str, papers: dict) -> str:
    """The §1.3 footer form: authors, year, full journal, n, PMID."""
    p = papers.get(str(pmid)) or {}
    bits: list[str] = []

    authors = (p.get("authors") or "").strip()
    year = str(p.get("year") or "").strip()
    if authors:
        names = [a.strip() for a in
                 re.split(r"[;,]", re.sub(r",?\s*et al\.?", "", authors, flags=re.I))
                 if a.strip()]
        lead = names[0] if names else authors
        head = lead if (len(names) == 1 and not re.search(r"et al", authors, re.I)) \
            else f"{lead} et al."
        bits.append(f"{head} {year}".strip())
    elif year:
        bits.append(year)

    journal = (p.get("journal") or p.get("journal_abbrev") or "").strip()
    if journal:
        bits.append(journal)

    n = p.get("sample_size")
    if n:
        bits.append(f"n = {n}")

    bits.append(f"PMID {pmid}")
    return " · ".join(bits)


def strip_markers(text: str) -> str:
    """Remove provenance markers and tidy the whitespace they leave behind.

    §1.3 forbids a raw marker on a slide outright, so this is not cosmetic:
    it is the rule, and `tests/test_webdeck.py` asserts no rendered deck
    contains one.
    """
    out = PMID_MARKER.sub("", text or "")
    out = PMID_BRACKET.sub("", out)
    out = re.sub(r"\s+([.,;:)])", r"\1", out)
    out = re.sub(r"\(\s*\)", "", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def render_inline(text: str, papers: dict) -> str:
    """Body text for a slide: markers become clickable pills, everything else
    is escaped. Markdown bold survives because the generator uses it for key
    phrases on the takeaways layout (§1.4 #7)."""
    if not text:
        return ""

    pills: list[str] = []

    def stash(m):
        pills.append(pill_html(m.group(1), papers))
        return f"\x00{len(pills) - 1}\x00"

    staged = PMID_MARKER.sub(stash, str(text))
    staged = PMID_BRACKET.sub(stash, staged)
    staged = re.sub(r"\s+([.,;:)])", r"\1", staged)
    out = esc(staged)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"\x00(\d+)\x00", lambda m: pills[int(m.group(1))], out)
    return out.strip()


# "Meire et al., J Endod 2023" — the shape `generate_slides_specs` puts in its
# `citation` / `footer_caption` fields, where it does NOT emit a PMID marker.
# The gap class must admit "." because "et al." sits inside almost every one of
# these; it is bounded at 40 characters so a year cannot reach back across a
# sentence to a name that has nothing to do with it.
_AUTHOR_YEAR = re.compile(r"\b([A-ZÀ-Ý][\w'’\-]{2,})\b[^;\n]{0,40}?\b(19|20)(\d{2})\b")


def _surname(authors: str) -> str:
    first = re.split(r"[;,]", re.sub(r",?\s*et al\.?", "", authors or "",
                                     flags=re.I))[0].strip()
    parts = first.split()
    return (parts[0] if parts else "").lower()


def resolve_author_year(text: str, papers: dict) -> list[str]:
    """PMIDs for "Surname … YEAR" citations that resolve UNAMBIGUOUSLY.

    Deliberately strict. A pill is a claim that this sentence rests on that
    paper, so a near-miss is worse than no pill at all: it would attribute a
    clinical statement to the wrong study. Surname and year must both match
    exactly and exactly one paper in the run may match — two candidates yield
    nothing rather than a coin flip.
    """
    if not text:
        return []
    hits, seen = [], set()
    for m in _AUTHOR_YEAR.finditer(str(text)):
        surname = m.group(1).lower()
        year = m.group(2) + m.group(3)
        cands = {pmid for pmid, p in papers.items()
                 if str(p.get("year") or "") == year
                 and _surname(p.get("authors") or "") == surname}
        if len(cands) == 1:
            pmid = cands.pop()
            if pmid not in seen:
                seen.add(pmid)
                hits.append(pmid)
    return hits


def pill_html(pmid: str, papers: dict, label: str | None = None,
              extra_class: str = "") -> str:
    """One citation pill. `data-pmid` is what the overlay handler reads, and
    what the browser test clicks."""
    text = label if label is not None else format_cite(pmid, papers)
    cls = ("cite-pill " + extra_class).strip()
    return (f'<button type="button" class="{cls}" data-pmid="{esc(pmid)}" '
            f'title="Show source abstract (PMID {esc(pmid)})">{esc(text)}</button>')
