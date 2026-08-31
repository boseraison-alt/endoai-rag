"""
One canonical slide spec per answer, shared by every deck export.

PRESENTATION_WORKLIST.md §0 states the prime rule — "rendering only, never
authoring" — and §5.1 requires that the PPTX and web-deck exports "consume one
canonical text object and assert its content hash matches between builds".

That assertion is unsatisfiable as the code stands. `generate_slides_specs()`
is an LLM call: it asks Claude to lay the answer out across slides, and two
calls with identical arguments return different wording, different slide counts
and a different hash. If each export called it separately, the two decks would
disagree about what the deck says — not because either invented content, but
because they asked twice.

So the spec is generated ONCE per (answer, question, length) and cached. Both
exports read the same object, and the hash comparison becomes meaningful
instead of guaranteed-false.

The cache key is a hash of the INPUTS, so:
  * the same answer exported to pptx and to a web deck reuses one spec;
  * regenerating after the answer changes correctly produces a new spec;
  * a history-loaded answer keys identically to the live one it came from.

Persisted to disk because the two exports are separate HTTP requests, and on a
restart (the single-worker constraint in DEPLOYMENT.md) an in-memory cache
would silently start returning mismatched specs.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "slide_specs"
CACHE_TTL_DAYS = 30

_lock = threading.Lock()


def spec_key(answer: str, question: str, length_minutes: int) -> str:
    """Stable id for one (answer, question, length) triple.

    Hashes the inputs rather than the output: the output is what we are trying
    to keep stable, so it cannot also be the key.
    """
    h = hashlib.sha256()
    for part in (question or "", answer or "", str(length_minutes)):
        h.update(part.encode("utf-8", "replace"))
        h.update(b"\x00")          # domain separator; prevents field-splice collisions
    return h.hexdigest()[:32]


def content_hash(spec: dict) -> str:
    """Hash of the slide CONTENT, for the §5.1 cross-export assertion.

    Covers only the text that reaches a slide, with keys sorted so a dict
    reordering does not read as a content change. Rendering metadata added by
    one exporter and not the other must not shift this hash — that is the whole
    point of the check.
    """
    slides = (spec or {}).get("slides") or []
    return hashlib.sha256(
        json.dumps(slides, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def load(key: str) -> dict | None:
    """Return the cached spec, or None. Never raises: a cache miss and a
    corrupt cache file must both simply mean 'generate it'."""
    try:
        p = _path(key)
        if not p.exists():
            return None
        age_days = (time.time() - p.stat().st_mtime) / 86400.0
        if age_days > CACHE_TTL_DAYS:
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if (data or {}).get("slides") else None
    except Exception as e:
        print(f"  [slide_spec] cache read failed ({e}); regenerating")
        return None


def save(key: str, spec: dict) -> None:
    """Persist a spec. Never raises — failing to cache must not fail an export.

    Writes to a temp file and replaces, so a crash mid-write cannot leave a
    truncated JSON that later reads as a valid-but-wrong spec.
    """
    if not (spec or {}).get("slides"):
        return
    try:
        with _lock:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            p = _path(key)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(spec, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            os.replace(tmp, p)
    except Exception as e:
        print(f"  [slide_spec] cache write failed ({e}); export continues")


def get_or_build(answer: str, question: str, length_minutes: int,
                 builder=None) -> tuple[dict, str, bool]:
    """The entry point every deck exporter should call.

    Returns (spec, content_hash, from_cache). `builder` defaults to
    endo_ai.generate_slides_specs and is injectable so tests never need the
    network or an API key.
    """
    key = spec_key(answer, question, length_minutes)
    cached = load(key)
    if cached is not None:
        return cached, content_hash(cached), True

    if builder is None:
        from endo_ai import generate_slides_specs as builder   # local: heavy import
    spec = builder(answer, question, length_minutes)
    save(key, spec)
    return spec, content_hash(spec), False
