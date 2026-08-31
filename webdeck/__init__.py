"""Curo web-deck export — PRESENTATION_WORKLIST.md §3.

One self-contained HTML file per answer, rendered from the SAME canonical
slide spec the PPTX export consumes (`slide_spec_cache.get_or_build`). The
prime rule holds throughout: this package renders, it never authors. Every
clinical word on every slide is copied out of the spec; the only strings these
modules originate are furniture — page numbers, "MODULE 2 OF 6", column
headers, the IF / THEN / BECAUSE chips.
"""
from .assets import REVEAL_VERSION
from .builder import build_web_deck, tier_counts
from .narration import load_narration, parse_sidecar

__all__ = ["build_web_deck", "tier_counts", "load_narration",
           "parse_sidecar", "REVEAL_VERSION"]
