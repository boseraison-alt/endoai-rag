"""Build one self-contained HTML deck from the canonical slide spec (§3.1).

Entry point: `build_web_deck(...) -> str`. The result is a single file: all
deck CSS and JS inline, abstracts embedded, narration audio embedded as a data
URI when a sidecar exists. reveal.js is pinned and loaded from cdnjs, and the
two Google Fonts faces from fonts.googleapis.com — everything else travels
inside the file so the deck opens from a USB stick with the app stopped.
"""
from __future__ import annotations

import html
import json
from collections import Counter

from . import assets, layouts as L, plan as P, tokens as T
from .citations import esc, extract_pmids


def _papers_index(papers_list) -> dict:
    out = {}
    for p in (papers_list or []):
        pmid = str(p.get("pmid") or "").strip()
        if pmid:
            out[pmid] = p
    return out


def tier_counts(papers_list) -> dict:
    """Per-tier paper counts for the evidence-shape bar (§1.4 #1)."""
    counts = Counter()
    for p in (papers_list or []):
        if p.get("has_retraction"):
            continue          # retracted rows are never evidence (HANDOVER.md)
        counts[T.slot_for(p.get("level_key"))] += 1
    return dict(counts)


def _section(slide, ctx) -> str:
    layout = slide["layout"]
    render = L.LAYOUT_RENDERERS[layout]

    ctx = dict(ctx)
    ctx["slide_tier"] = slide.get("_tier_slot", "other")
    ctx["module_index"] = slide.get("_module_index")
    ctx["module_total"] = slide.get("_module_total")

    inner = render(slide, ctx)

    if layout in ("title", "divider"):
        body = inner                       # these renderers own their frame
    else:
        eyebrow = slide.get("eyebrow") or ""
        if slide.get("_continued"):
            eyebrow = (eyebrow + " · CONT.").strip(" ·")
        # §1.3 puts the slide's evidence tier here, or the CURO label on
        # takeaways/references. A slide whose evidence did not resolve gets the
        # CURO label too — an "OTHER" chip in the tier position would read as a
        # tier claim about papers we could not identify.
        chip = L._curo_chip() \
            if (layout in P.CURO_CHIP_LAYOUTS or ctx["slide_tier"] == "other") \
            else L._tier_chip(ctx["slide_tier"])
        body = ('<div class="frame">'
                + L._header(eyebrow, chip)
                + inner
                # A references slide IS the citation list; repeating three of
                # its own rows in the footer is noise.
                + L._footer([] if layout == "references"
                            else (slide.get("_pmids") or []),
                            ctx["papers"], slide.get("_page", ""))
                + '</div>')

    notes = html.escape(slide.get("speaker_notes") or "")
    return (f'<section class="deck-slide layout-{layout}" data-layout="{layout}">'
            f'{body}'
            + (f'<aside class="notes">{notes}</aside>' if notes else "")
            + '</section>')


def build_web_deck(spec: dict, question: str, answer: str,
                   papers_list=None, abstracts=None, narration=None,
                   spec_hash: str = "", narration_loader=None) -> str:
    """Render the deck. `spec` is the canonical object from
    `slide_spec_cache.get_or_build` — never re-derived from `answer`, which is
    used only as the citation source and the §1.5 chart-value check."""
    papers_list = papers_list or []
    papers = _papers_index(papers_list)

    # Abstract records carry titles the scored-paper rows often lack.
    for pmid, rec in (abstracts or {}).items():
        row = papers.setdefault(str(pmid), {"pmid": str(pmid)})
        for key in ("title", "journal", "year", "authors"):
            if not row.get(key) and rec.get(key):
                row[key] = rec[key]

    planned = P.plan_deck(spec, papers, list(papers.values()), answer or "")

    ctx = {"papers": papers, "question": question,
           "tier_counts": tier_counts(papers_list)}
    sections = "\n".join(_section(s, ctx) for s in planned)

    # §3.3. The loader needs the spec→section mapping, which only exists after
    # planning, so it is injected as a callable rather than pre-loaded. Any
    # failure inside it costs the deck its audio, never the export.
    if narration is None and narration_loader is not None:
        try:
            narration = narration_loader(len((spec or {}).get("slides") or []),
                                         P.spec_to_section_map(planned))
        except Exception as e:
            print(f"  [webdeck] narration loader failed ({e}); no audio embedded")
            narration = None

    config = {
        "width": assets.SLIDE_W, "height": assets.SLIDE_H,
        "slide_count": len(planned),
        "spec_hash": spec_hash,
        "abstracts": abstracts or {},
        "narration": narration or None,
    }
    # `<` is escaped so no abstract, title or narration filename can close the
    # inline <script> and start executing. The deck is served from the app's
    # own origin, so this is the difference between an embedded abstract and
    # stored XSS against a logged-in clinician.
    config_json = json.dumps(config, ensure_ascii=False).replace("<", "\\u003c")

    title = html.escape(
        (spec or {}).get("title") or question or "Curo evidence deck")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Curo</title>
<meta name="generator" content="Curo web deck · reveal.js {assets.REVEAL_VERSION}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{T.GOOGLE_FONTS_HREF}">
<link rel="stylesheet" href="{assets.REVEAL_BASE}/reveal.min.css"
      integrity="{assets.REVEAL_CSS_SRI}" crossorigin="anonymous"
      referrerpolicy="no-referrer">
<style>
{assets.stylesheet()}
</style>
</head>
<body>
<div class="reveal"><div class="slides">
{sections}
</div></div>

<div id="abs-overlay" role="dialog" aria-modal="true" aria-labelledby="abs-title">
  <div id="abs-panel">
    <h2 id="abs-title"></h2>
    <div id="abs-meta"></div>
    <div id="abs-source"></div>
    <div id="abs-body"></div>
    <div id="abs-foot">
      <a id="abs-link" href="#" target="_blank" rel="noopener">Open in PubMed ↗</a>
      <button id="abs-close" type="button">Close</button>
    </div>
  </div>
</div>

<div id="narration">
  <span class="n-label">Narration</span>
  <audio id="n-audio" controls preload="none"></audio>
  <button id="n-sync" type="button" aria-pressed="true">Auto-advance</button>
</div>

<script src="{assets.REVEAL_BASE}/reveal.min.js"
        integrity="{assets.REVEAL_JS_SRI}" crossorigin="anonymous"
        referrerpolicy="no-referrer"></script>
<script>
{assets.runtime_js(config_json)}
</script>
</body>
</html>
"""
