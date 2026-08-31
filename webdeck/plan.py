"""Turn one canonical slide spec into a list of renderable slides.

`generate_slides_specs()` is the canonical text object (worklist §0 prime
rule): the deck consumes it and never re-derives slides from the answer
markdown. This module does three things and no others —

  1. maps each emitted PATTERN onto one of the eight approved LAYOUTS,
  2. applies the §1.3 body budget by SPLITTING onto continuation slides,
  3. attaches furniture: the eyebrow, the slide's tier chip, the page number
     and the footer citations.

It never rewrites, summarises or invents a word of clinical text. The one
place it originates text at all is furniture — "MODULE 2 OF 5", the IF /
THEN / BECAUSE chips, column headers, the page number.
"""
from __future__ import annotations

import re

from . import layouts as L
from . import tokens as T
from .citations import (esc, extract_pmids, render_inline, resolve_author_year,
                        strip_markers)

# Tier strength order for "the slide's evidence" (§1.3 header chip): the
# STRONGEST tier cited on the slide, so a chip can never overstate.
_STRENGTH = {slot: i for i, slot in enumerate(T.TIER_SLOTS)}
_STRENGTH["other"] = len(T.TIER_SLOTS)

# Layouts that carry the §1.3 furniture (header row, title, footer rule).
CONTENT_CLASS = {"content", "table", "decision", "chart", "takeaways",
                 "references", "notice"}
# Layouts whose header chip is the "CURO" label rather than a tier (§1.3).
CURO_CHIP_LAYOUTS = {"takeaways", "references"}


def strongest_slot(pmids, papers) -> str:
    slots = [T.slot_for((papers.get(str(p)) or {}).get("level_key"))
             for p in pmids]
    slots = [s for s in slots if s]
    if not slots:
        return "other"
    return min(slots, key=lambda s: _STRENGTH.get(s, 99))


# ── per-pattern adapters ─────────────────────────────────
def _plan_content(s, bullets, title, lead=None, figure=None):
    pages = L.split_by_budget(
        bullets,
        text_of=lambda b: " ".join(str(b.get(k, "")) for k in ("header", "body"))
        if isinstance(b, dict) else str(b))
    out = []
    for i, page in enumerate(pages):
        out.append({"layout": "content", "title": title,
                    "lead": lead if i == 0 else "",
                    "figure": figure if i == 0 else None,
                    "_bullets": page, "_continued": i > 0})
    return out


def _plan_table(s, title, columns, rows, notice="", notice_label=""):
    out = []
    pages = L.chunk(rows, L.TABLE_ROWS_PER_SLIDE)
    for i, page in enumerate(pages):
        last = i == len(pages) - 1
        out.append({"layout": "table", "title": title,
                    "_columns": columns, "_rows": page,
                    "_notice": notice if last else "",
                    "_notice_label": notice_label if (last and notice) else "",
                    "_continued": i > 0})
    return out


def _plan_decision(s, title, cards, caption=""):
    out = []
    pages = L.chunk(cards, L.CARDS_PER_SLIDE)
    for i, page in enumerate(pages):
        out.append({"layout": "decision", "title": title, "_cards": page,
                    "_caption": caption if i == len(pages) - 1 else "",
                    "_continued": i > 0})
    return out


def _cell(text, papers):
    return render_inline(text, papers)


def adapt(s: dict, papers: dict, source_text: str) -> list[dict]:
    """One spec slide → one or more renderable slides."""
    pattern = (s.get("pattern") or "").strip()
    layout = L.LAYOUT_FOR_PATTERN.get(pattern, L.DEFAULT_LAYOUT)
    title = strip_markers(s.get("title") or "")

    if layout == "title":
        return [dict(s, layout="title")]

    if layout == "divider":
        return [dict(s, layout="divider")]

    if pattern == "objectives_slide":
        return _plan_content(s, s.get("items") or [], title,
                             lead=s.get("closing_callout"), figure=s.get("figure"))

    if pattern == "cascade_slide":
        return _plan_content(s, s.get("steps") or [], title,
                             lead=s.get("footer_callout"), figure=s.get("figure"))

    if pattern == "two_column_compare":
        left = s.get("left_card") or {}
        right = s.get("right_card") or {}
        cols = [{"label": strip_markers(left.get("label") or "Option A"), "span": 6, "key": True},
                {"label": strip_markers(right.get("label") or "Option B"), "span": 6}]
        ll, rl = left.get("lines") or [], right.get("lines") or []
        rows = [[_cell(left.get("headline"), papers), _cell(right.get("headline"), papers)]] \
            if (left.get("headline") or right.get("headline")) else []
        for i in range(max(len(ll), len(rl))):
            rows.append([_cell(ll[i] if i < len(ll) else "", papers),
                         _cell(rl[i] if i < len(rl) else "", papers)])
        verdicts = " · ".join(
            strip_markers((c.get("verdict") or {}).get("text") or "")
            for c in (left, right) if (c.get("verdict") or {}).get("text"))
        notice = " ".join(x for x in (verdicts, strip_markers(s.get("caption") or "")) if x)
        return _plan_table(s, title, cols, rows, notice,
                           notice_label="VERDICT" if verdicts else "")

    if pattern == "evidence_summary":
        cols = [{"label": "Tier", "span": 3, "key": True},
                {"label": "What the studies are", "span": 6},
                {"label": "Reported figure", "span": 3, "source": True}]
        rows = [[_cell(r.get("tier_label"), papers),
                 _cell(r.get("description"), papers),
                 _cell(r.get("stat"), papers)]
                for r in (s.get("hierarchy_rows") or [])]
        trap = s.get("trap_callout") or {}
        notice = " ".join(strip_markers(str(trap.get(k) or ""))
                          for k in ("body", "stat", "stat_label")).strip()
        return _plan_table(s, title, cols, rows, notice,
                           notice_label=strip_markers(str(trap.get("heading") or "")))

    if pattern == "decision_table":
        cards = [{"if": r.get("finding"), "then": r.get("implication"),
                  "because": r.get("path")} for r in (s.get("rows") or [])]
        return _plan_decision(s, title, cards, s.get("footer_caption") or "")

    if pattern == "three_route_grid":
        cards = [{"label": r.get("name"), "if": r.get("when"),
                  "then": r.get("how"), "because": r.get("tagline")}
                 for r in (s.get("routes") or [])]
        return _plan_decision(s, title, cards, s.get("caption") or "")

    if pattern == "stat_panel":
        return _plan_stat(s, title, papers, source_text)

    if pattern == "takeaways_slide":
        items = s.get("items") or []
        pages = L.chunk(items, L.TAKEAWAYS_PER_SLIDE)
        notice = strip_markers(s.get("does_not_apply") or s.get("contraindication") or "")
        return [{"layout": "takeaways", "title": title, "_items": page,
                 "_notice": notice if i == len(pages) - 1 else "",
                 "_continued": i > 0, "speaker_notes": s.get("speaker_notes")}
                for i, page in enumerate(pages)]

    if layout == "notice":
        return [dict(s, layout="notice")]

    # Unknown pattern: render whatever list-ish text it carries as content
    # rather than dropping the slide, which would silently lose material.
    fallback = [v for v in (s.get("items") or s.get("bullets") or s.get("lines") or [])]
    return _plan_content(s, fallback, title or strip_markers(str(s.get("headline") or "")))


def _plan_stat(s, title, papers, source_text):
    """§1.5: a stat panel becomes a chart ONLY if every plotted number appears
    verbatim in the source text. Otherwise it renders as text — an uncited
    number must never acquire the authority of a plotted mark."""
    pairs = [(s.get("primary_label"), s.get("primary_stat")),
             (s.get("secondary_label"), s.get("secondary_stat"))]
    pairs = [(strip_markers(str(lbl or "")), str(v)) for lbl, v in pairs if v]

    plottable = [(lbl or "value", L._as_float(v), strip_markers(v))
                 for lbl, v in pairs
                 if L.value_is_cited(v, source_text) and L._as_float(v) is not None]

    if len(plottable) >= 2:
        return [{"layout": "chart", "title": title, "_series": plottable,
                 "_chart_kind": L.chart_kind([raw for _n, _v, raw in plottable]),
                 "_axis_label": strip_markers(s.get("citation") or ""),
                 "callout": s.get("callout"),
                 "speaker_notes": s.get("speaker_notes")}]

    bullets = [{"number": strip_markers(v), "header": "", "body": lbl}
               for lbl, v in pairs]
    if s.get("callout"):
        bullets.append({"number": "", "header": "", "body": s["callout"]})
    return _plan_content(s, bullets, title, lead=s.get("citation"))


# ── deck assembly ────────────────────────────────────────
def build_reference_slides(papers_list, cited_pmids) -> list[dict]:
    """§1.4 #8. Built from PubMed metadata already attached to the run — the
    titles, journals, years and tiers are quoted, not written."""
    by_pmid = {str(p.get("pmid")): p for p in (papers_list or []) if p.get("pmid")}
    ordered = [by_pmid[p] for p in cited_pmids if p in by_pmid]
    if not ordered:
        return []
    refs = []
    for i, p in enumerate(ordered, 1):
        meta = " · ".join(x for x in [
            (p.get("journal") or p.get("journal_abbrev") or "").strip(),
            str(p.get("year") or "").strip(),
            (f"n = {p['sample_size']}" if p.get("sample_size") else ""),
        ] if x)
        refs.append({"n": i, "pmid": str(p.get("pmid")),
                     "title": (p.get("title") or "").strip(),
                     "meta": meta, "level_key": p.get("level_key"),
                     "score": p.get("score")})
    pages = L.chunk(refs, L.REFERENCE_ROWS_PER_SLIDE)
    return [{"layout": "references", "title": "References", "_refs": page,
             "eyebrow": "CURO · EVIDENCE BASE", "_continued": i > 0}
            for i, page in enumerate(pages)]


_CITATION_KEYS = ("citation", "footer_caption", "footer_metadata", "caption",
                  "footer", "closing_callout", "footer_callout")


def _citation_fields(spec_slide: dict):
    """The fields that carry a written-out citation. Deliberately NOT the body
    text: an author name inside a clinical sentence is not a citation, and
    pinning a pill to it would over-claim."""
    out = []
    for k in _CITATION_KEYS:
        v = spec_slide.get(k)
        if isinstance(v, str) and v:
            out.append(v)
    for key in ("routes", "rows", "items", "steps", "hierarchy_rows"):
        for row in (spec_slide.get(key) or []):
            if isinstance(row, dict) and isinstance(row.get("citation"), str):
                out.append(row["citation"])
    # evidence_summary is the one pattern whose row `description` IS a citation
    # ("14 clinical studies, PROSPERO-registered, GRADE-assessed, Meire 2023")
    # rather than clinical prose about a patient.
    if spec_slide.get("pattern") == "evidence_summary":
        for row in (spec_slide.get("hierarchy_rows") or []):
            if isinstance(row, dict) and isinstance(row.get("description"), str):
                out.append(row["description"])
    return out


def plan_deck(spec: dict, papers: dict, papers_list, source_text: str) -> list[dict]:
    raw = (spec or {}).get("slides") or []
    planned: list[dict] = []
    for spec_index, s in enumerate(raw):
        for out in adapt(s, papers, source_text):
            out.setdefault("pattern", s.get("pattern"))
            out.setdefault("eyebrow", s.get("eyebrow") or "")
            out.setdefault("speaker_notes", s.get("speaker_notes") or "")
            out["_source"] = s
            # Which spec slide this section came from. A spec slide can expand
            # to several sections under the §1.3 body budget, so narration
            # timings keyed on spec slides need this to find a section.
            out["_spec_index"] = spec_index
            planned.append(out)

    # §1.4 #8 lists the deck's evidence base, which is the answer's citations —
    # the generator keeps markers out of the slides themselves, so reading them
    # off the spec alone would produce a near-empty reference section.
    cited = list(dict.fromkeys(extract_pmids(source_text) + extract_pmids(raw)))
    planned.extend(build_reference_slides(papers_list, cited))

    # Divider tick lines (§1.4 #2) are the titles of the slides that module
    # actually contains — existing text, reordered, never new text.
    dividers = [i for i, s in enumerate(planned) if s["layout"] == "divider"]
    for n, i in enumerate(dividers, 1):
        end = dividers[n] if n < len(dividers) else len(planned)
        topics, seen = [], set()
        for s in planned[i + 1:end]:
            t = strip_markers(s.get("title") or "")
            if t and t not in seen:
                seen.add(t)
                topics.append(t)
        planned[i]["topics"] = topics[:3]
        planned[i]["_module_index"] = n
    for i in dividers:
        planned[i]["_module_total"] = len(dividers)

    # Furniture pass.
    page = 0
    for s in planned:
        src = s.get("_source") or s
        pmids = extract_pmids(src)
        if not pmids:
            # The generator writes "Meire et al., J Endod 2023" into its
            # citation fields without a marker. Resolving those (strictly, see
            # resolve_author_year) is what keeps the footer from going blank
            # on most slides.
            pmids = resolve_author_year(
                " \n".join(str(v) for v in _citation_fields(src)), papers)
        if s["layout"] == "references":
            pmids = [r["pmid"] for r in s.get("_refs") or []]
        s["_pmids"] = pmids
        s["_tier_slot"] = strongest_slot(pmids, papers)
        if s["layout"] in CONTENT_CLASS:
            page += 1
            s["_page"] = page
    return planned


def spec_to_section_map(planned) -> dict:
    """spec-slide index → the FIRST deck section it produced."""
    out = {}
    for i, s in enumerate(planned):
        idx = s.get("_spec_index")
        if isinstance(idx, int) and idx not in out:
            out[idx] = i
    return out
