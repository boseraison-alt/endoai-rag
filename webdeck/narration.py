"""Narration sync (§3.3) — the consumer half.

Agent C emits a per-slide timestamp map at TTS time. This module reads it.
The two halves are being built concurrently, so this is written to be tolerant
of the producer that does not exist yet: a missing, empty, malformed or
mismatched sidecar means the deck is built WITHOUT audio, never that the
export fails. §3.3's own words: "graceful without audio".

THE SHAPE THIS CONSUMES (state it in the phase report so the producer can be
reconciled against it):

    {
      "version": 1,
      "audio_file": "9be11f16-....mp3",   # basename, resolved next to the JSON
      "duration_sec": 612.4,
      "voice": "onyx",
      "spec_hash": "<slide_spec_cache.content_hash(spec)>",
      "slides": [
        {"slide_number": 1, "start_sec": 0.0, "end_sec": 31.2},
        {"slide_number": 2, "start_sec": 31.2, "end_sec": 68.9}
      ]
    }

Tolerated variations, because guessing wrong about a sibling agent's field
names is cheaper to absorb here than to renegotiate later:
  * the segment list may be called `slides`, `segments`, `cues` or `timings`;
  * a segment's start may be `start_sec`, `start`, `time`, or `start_ms`
    (milliseconds, converted); likewise `end_sec` / `end` / `end_ms`;
  * `slide_number` may be `slide`, `index` or `n`, 1- or 0-based — a list that
    starts at 0 is shifted up by one;
  * a missing `end` is inferred from the next segment's start, and the last
    segment's from `duration_sec`.

`spec_hash` is the reliable link between an audio render and a deck: it is the
§5.1 content hash of the same canonical spec. When it is present and does not
match, the sidecar is IGNORED — playing one answer's narration over another
answer's slides is worse than silence.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SIDECAR_SUFFIXES = (".timings.json", ".narration.json", ".sync.json")

_SEG_LISTS = ("slides", "segments", "cues", "timings")
_START_KEYS = (("start_sec", 1.0), ("start", 1.0), ("time", 1.0), ("start_ms", 0.001))
_END_KEYS = (("end_sec", 1.0), ("end", 1.0), ("stop", 1.0), ("end_ms", 0.001))
_NUM_KEYS = ("slide_number", "slide", "index", "n")


def _num(seg, keys):
    for key, scale in keys:
        v = seg.get(key)
        if isinstance(v, (int, float)):
            return float(v) * scale
    return None


def parse_sidecar(raw) -> dict | None:
    """Normalise a sidecar into {"audio_file", "duration_sec", "spec_hash",
    "cues": [{"slide": int, "start": float, "end": float}]} or None."""
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw)
        except Exception:
            return None
    if not isinstance(raw, dict):
        return None

    segs = None
    for key in _SEG_LISTS:
        if isinstance(raw.get(key), list) and raw[key]:
            segs = raw[key]
            break
    if not segs:
        return None

    cues = []
    for i, seg in enumerate(segs):
        if not isinstance(seg, dict):
            return None
        start = _num(seg, _START_KEYS)
        if start is None:
            return None
        number = next((seg[k] for k in _NUM_KEYS
                       if isinstance(seg.get(k), int)), i)
        cues.append({"slide": int(number), "start": start,
                     "end": _num(seg, _END_KEYS)})

    if min(c["slide"] for c in cues) == 0:      # 0-based producer
        for c in cues:
            c["slide"] += 1

    cues.sort(key=lambda c: c["start"])
    duration = raw.get("duration_sec") or raw.get("duration")
    duration = float(duration) if isinstance(duration, (int, float)) else None
    for i, c in enumerate(cues):
        if c["end"] is None:
            c["end"] = cues[i + 1]["start"] if i + 1 < len(cues) else duration
    if cues[-1]["end"] is None:
        cues[-1]["end"] = cues[-1]["start"] + 30.0   # last slide, unknown tail

    return {"audio_file": raw.get("audio_file") or raw.get("audio") or "",
            "duration_sec": duration,
            "spec_hash": raw.get("spec_hash") or "",
            "voice": raw.get("voice") or "",
            "cues": cues}


def find_sidecar(media_dir, spec_hash: str = "", audio_id: str = "") -> Path | None:
    """Locate the sidecar for this deck.

    An explicit `audio_id` wins (the caller knows which render it wants).
    Otherwise the `spec_hash` link is used, which is the only match that is
    actually PROVABLY about the same answer. Nothing is matched on the
    question string: two exports of the same question at different lengths
    have different slides.
    """
    d = Path(media_dir)
    if not d.is_dir():
        return None

    if audio_id:
        for suffix in SIDECAR_SUFFIXES:
            p = d / f"{audio_id}{suffix}"
            if p.is_file():
                return p

    if not spec_hash:
        return None
    candidates = []
    for suffix in SIDECAR_SUFFIXES:
        candidates.extend(d.glob(f"*{suffix}"))
    for p in sorted(candidates, key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("spec_hash") == spec_hash:
            return p
    return None


def load_narration(media_dir, spec_hash: str = "", audio_id: str = "",
                   slide_count: int = 0) -> dict | None:
    """Return {"audio_data_uri" | "audio_src", "cues": [...]}, or None.

    Audio is embedded as a data URI so the deck stays a single self-contained
    file (§3.1). A render over ~24 MB is left as a relative src instead: past
    that the base64 payload makes the HTML unusable, and a deck that opens
    without audio beats a deck that will not open.
    """
    path = find_sidecar(media_dir, spec_hash=spec_hash, audio_id=audio_id)
    if path is None:
        return None
    try:
        parsed = parse_sidecar(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not parsed:
        return None

    if slide_count and max(c["slide"] for c in parsed["cues"]) > slide_count:
        # The narration was cut against a different deck. Refuse rather than
        # advancing slides to timings that do not describe these slides.
        return None

    audio_path = None
    if parsed["audio_file"]:
        cand = Path(media_dir) / os.path.basename(parsed["audio_file"])
        if cand.is_file():
            audio_path = cand
    if audio_path is None:
        for ext in (".mp3", ".m4a", ".wav"):
            cand = path.parent / (path.name.split(".")[0] + ext)
            if cand.is_file():
                audio_path = cand
                break
    if audio_path is None:
        return None

    result = {"cues": parsed["cues"], "duration_sec": parsed["duration_sec"],
              "audio_src": "", "audio_mime": _mime(audio_path.suffix)}
    try:
        if audio_path.stat().st_size <= 24 * 1024 * 1024:
            import base64
            b64 = base64.b64encode(audio_path.read_bytes()).decode("ascii")
            result["audio_src"] = f"data:{result['audio_mime']};base64,{b64}"
        else:
            result["audio_src"] = audio_path.name
    except Exception:
        return None
    return result


def _mime(suffix: str) -> str:
    return {".mp3": "audio/mpeg", ".m4a": "audio/mp4",
            ".wav": "audio/wav"}.get(suffix.lower(), "audio/mpeg")
