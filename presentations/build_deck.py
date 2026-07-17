"""
Endo AI — Deck Dispatcher
==========================
Maps "pattern" key in slide specs to pattern functions and builds a complete
python-pptx Presentation. Also handles the legacy "type" key format produced
by generate_slides_content() so the dispatcher is forward/backward compatible.

Usage
-----
    from presentations.build_deck import build_deck_from_specs

    deck = generate_slides_specs(answer, question, length_minutes)
    prs, slides_queue = build_deck_from_specs(deck)
    prs.save(output_path)
    # slides_queue: [(slide_obj, speaker_notes_str, slide_num_1based), ...]
    # Use slides_queue for TTS pipeline in app.py.
"""

from __future__ import annotations

import warnings
from pptx.presentation import Presentation

from presentations.slide_helpers import new_presentation, blank_slide
from presentations.design_tokens import COLORS, SIZES, LAYOUT
from presentations.slide_patterns import (
    title_slide,
    section_divider,
    objectives_slide,
    two_column_compare,
    cascade_slide,
    decision_table,
    three_route_grid,
    stat_panel,
    takeaways_slide,
    evidence_summary,
)

# ── Pattern dispatch table ────────────────────────────────────────────────────
PATTERN_DISPATCH: dict[str, callable] = {
    "title_slide":       title_slide,
    "section_divider":   section_divider,
    "objectives_slide":  objectives_slide,
    "two_column_compare": two_column_compare,
    "cascade_slide":     cascade_slide,
    "decision_table":    decision_table,
    "three_route_grid":  three_route_grid,
    "stat_panel":        stat_panel,
    "takeaways_slide":   takeaways_slide,
    "evidence_summary":  evidence_summary,
}

# ── Legacy "type" → pattern fallback mapping ─────────────────────────────────
# When generate_slides_content() (old format) is used instead of
# generate_slides_specs(), we map the old type names to the closest pattern.
_LEGACY_TYPE_MAP: dict[str, str] = {
    "title":             "title_slide",
    "summary":           "takeaways_slide",
    "stat_cards":        "stat_panel",
    "type_cards":        "objectives_slide",
    "numbered_grid":     "objectives_slide",
    "bullets":           "objectives_slide",
    "comparison_table":  "decision_table",
    "references":        "takeaways_slide",
    "chart_bar":         "stat_panel",
}

_DEFAULT_PATTERN = "objectives_slide"


def _coerce_legacy_slide(spec: dict, deck: dict) -> dict:
    """Convert an old-format slide dict to best-effort new-pattern fields."""
    stype = spec.get("type", "").lower()
    pattern = _LEGACY_TYPE_MAP.get(stype, _DEFAULT_PATTERN)

    if pattern == "title_slide":
        return {
            "pattern":       "title_slide",
            "eyebrow":       spec.get("eyebrow", deck.get("footer", "ENDO AI")),
            "title":         spec.get("title", deck.get("title", "")),
            "subtitle":      spec.get("subtitle", deck.get("subtitle", "")),
            "tagline":       "",
            "footer_metadata": "",
            "speaker_notes": spec.get("speaker_notes", ""),
        }

    if pattern == "stat_panel":
        cards = spec.get("cards") or spec.get("categories") or []
        primary_stat  = str(cards[0].get("value", "") if cards else spec.get("values", [""])[0])
        primary_label = str(cards[0].get("label", "") if cards else "")
        secondary_stat  = str(cards[1].get("value", "")) if len(cards) > 1 else None
        secondary_label = str(cards[1].get("label", "")) if len(cards) > 1 else None
        return {
            "pattern":        "stat_panel",
            "eyebrow":        spec.get("eyebrow", ""),
            "title":          spec.get("title", ""),
            "primary_stat":   primary_stat,
            "primary_label":  primary_label,
            "secondary_stat":  secondary_stat,
            "secondary_label": secondary_label,
            "speaker_notes":  spec.get("speaker_notes", ""),
        }

    if pattern == "decision_table":
        headers = spec.get("headers", ["Finding", "Detail", "Path"])
        rows_raw = spec.get("rows", [])
        rows = []
        for row in rows_raw:
            if isinstance(row, list):
                rows.append({
                    "finding":      row[0] if len(row) > 0 else "",
                    "implication":  row[1] if len(row) > 1 else "",
                    "path":         row[2] if len(row) > 2 else "",
                    "severity_color": "accent_teal",
                })
            elif isinstance(row, dict):
                rows.append({
                    "finding":      row.get("finding", ""),
                    "implication":  row.get("implication", ""),
                    "path":         row.get("path", ""),
                    "severity_color": row.get("severity_color", "accent_teal"),
                })
        return {
            "pattern":        "decision_table",
            "eyebrow":        spec.get("eyebrow", ""),
            "title":          spec.get("title", ""),
            "rows":           rows,
            "speaker_notes":  spec.get("speaker_notes", ""),
        }

    if pattern == "takeaways_slide":
        bullets = spec.get("bullets") or spec.get("items") or []
        items = []
        for j, b in enumerate(bullets[:5]):
            if isinstance(b, str):
                items.append({"number": f"{j+1:02d}", "header": b, "body": ""})
            elif isinstance(b, dict):
                items.append({
                    "number": b.get("number", f"{j+1:02d}"),
                    "header": b.get("header", b.get("heading", str(b))),
                    "body":   b.get("body", ""),
                })
        return {
            "pattern":       "takeaways_slide",
            "eyebrow":       spec.get("eyebrow", "KEY TAKEAWAYS"),
            "title":         spec.get("title", ""),
            "items":         items,
            "speaker_notes": spec.get("speaker_notes", ""),
        }

    # Default → objectives_slide (handles bullets, numbered_grid, type_cards)
    bullets = (spec.get("bullets") or spec.get("items") or
               spec.get("cards") or [])
    items = []
    icons = ["check", "arrow_right", "info", "star", "diamond", "circle"]
    for j, b in enumerate(bullets[:4]):
        if isinstance(b, str):
            items.append({"icon": icons[j % len(icons)],
                          "number": f"{j+1:02d}", "header": b, "body": ""})
        elif isinstance(b, dict):
            items.append({
                "icon":   b.get("icon", icons[j % len(icons)]),
                "number": b.get("n", b.get("number", f"{j+1:02d}")),
                "header": b.get("heading", b.get("header", b.get("label", str(b)))),
                "body":   b.get("body", b.get("description", "")),
            })
    return {
        "pattern":       "objectives_slide",
        "eyebrow":       spec.get("eyebrow", ""),
        "title":         spec.get("title", ""),
        "items":         items,
        "speaker_notes": spec.get("speaker_notes", ""),
    }


def build_deck_from_specs(
    deck: dict,
    *,
    section_label: str | None = None,
) -> tuple[Presentation, list[tuple]]:
    """
    Build a Presentation from a pattern-based (or legacy) deck spec.

    Parameters
    ----------
    deck : dict
        Output of generate_slides_specs() or generate_slides_content().
        Must have a "slides" list.
    section_label : str, optional
        Override the footer section label for all slides.

    Returns
    -------
    prs : Presentation
        Fully built python-pptx Presentation (not yet saved).
    slides_queue : list of (slide_obj, speaker_notes_str, slide_num_1based)
        For the TTS pipeline in app.py.
    """
    slides_list = deck.get("slides", []) or []
    total       = len(slides_list)
    footer_base = section_label or deck.get("footer", "ENDO AI")

    prs          = new_presentation()
    slides_queue = []

    for i, raw_spec in enumerate(slides_list):
        page_num = i + 1
        spec     = dict(raw_spec)  # shallow copy — we'll pop keys

        # ── Determine pattern ──────────────────────────────────────────────
        pattern_name = spec.pop("pattern", None)
        if pattern_name is None:
            # Legacy "type" key
            spec = _coerce_legacy_slide(spec, deck)
            pattern_name = spec.pop("pattern", _DEFAULT_PATTERN)

        pattern_fn = PATTERN_DISPATCH.get(pattern_name)
        if pattern_fn is None:
            warnings.warn(
                f"[build_deck] Unknown pattern '{pattern_name}' on slide {page_num} "
                f"— falling back to {_DEFAULT_PATTERN}",
                stacklevel=2,
            )
            pattern_fn = PATTERN_DISPATCH[_DEFAULT_PATTERN]

        # ── Extract speaker notes (not a pattern field) ────────────────────
        notes = str(spec.pop("speaker_notes", "") or "")

        # ── Inject page metadata ───────────────────────────────────────────
        spec["_page_num"]    = page_num
        spec["_total_pages"] = total

        # ── Call pattern ───────────────────────────────────────────────────
        try:
            slide = pattern_fn(prs, **spec)
        except Exception as e:
            warnings.warn(
                f"[build_deck] Pattern '{pattern_name}' failed on slide {page_num}: {e} "
                f"— falling back to {_DEFAULT_PATTERN}",
                stacklevel=2,
            )
            # Minimal fallback: blank objectives slide with error title
            from presentations.slide_helpers import add_filled_rect, add_title, add_body
            from presentations.slide_helpers import blank_slide as _blank
            slide = _blank(prs)
            add_filled_rect(slide, 0, 0, LAYOUT["slide_w_in"], LAYOUT["slide_h_in"],
                            COLORS["bg_light"])
            add_title(slide, spec.get("title", f"Slide {page_num}"),
                      color=COLORS["ink_primary"])
            add_body(slide, f"[Layout error: {e}]",
                     LAYOUT["margin_x_in"], 2.5,
                     LAYOUT["slide_w_in"] - 2 * LAYOUT["margin_x_in"], 1.0,
                     color=COLORS["accent_red"])

        # ── Attach notes (visible in PowerPoint + used for TTS) ───────────
        if notes:
            try:
                slide.notes_slide.notes_text_frame.text = notes
            except Exception:
                pass

        slides_queue.append((slide, notes, page_num))

    return prs, slides_queue


__all__ = ["build_deck_from_specs", "PATTERN_DISPATCH"]
