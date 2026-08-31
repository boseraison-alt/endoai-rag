"""Narration sync (§3.3) — the consumer half.

Agent C's Phase 3 emits the map. This reads it.

THE SHAPE CONSUMED — `generated_media/<audio_id>.timestamps.json`, written by
`narration.build_timestamp_map`:

    {"version": 1, "audio_id": "…", "style": "lecture", "backend": "openai",
     "voice": "onyx", "model": "tts-1-hd", "duration_seconds": 606.024,
     "total_chars": 9404, "created_at": "…",
     "slides": [{"index": 0, "title": "…", "start": 0.0, "end": 5.016,
                 "char_start": 0, "char_end": 78, "preview": "…"}]}

with `slides` contiguous and gapless, `index` running 0..n-1,
`slides[0].start == 0.0` and `slides[-1].end == duration_seconds`.

THE MISMATCH THIS MODULE REFUSES TO PAPER OVER. Those segments are NARRATION
SECTIONS, not slides. A 10-minute lecture over the laser answer cuts into 13;
`generate_slides_specs` cuts the same answer into 25 slide specs, which the
web deck's §1.3 body budget expands to 34 sections. `char_start` is an offset
into the spoken script, not into the answer, so it cannot be mapped back onto
a slide either.

So auto-advance is armed ONLY when the segment count equals the number of
spec slides — the case where the narration really was cut per slide (the
pptx/video path, and what §5.1 will produce). Otherwise the audio still
attaches and plays, auto-advance is off, and the deck SAYS why. Advancing 34
slides against 13 unrelated boundaries would look like it worked while showing
the clinician the wrong slide for the sentence they are hearing — the failure
`HANDOVER.md` calls bug class (d), dressed up as a feature.

Everything here fails soft: a missing, empty, malformed or mismatched sidecar
means a deck without audio, never a failed export (§3.3 "graceful without
audio").
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

# `.timestamps.json` is Agent C's; the others are accepted because an earlier
# draft of the producer used them and a stale sidecar should still be read.
SIDECAR_SUFFIXES = (".timestamps.json", ".timings.json", ".narration.json")

_SEG_LISTS = ("slides", "segments", "cues", "timings")
_START_KEYS = (("start", 1.0), ("start_sec", 1.0), ("time", 1.0), ("start_ms", 0.001))
_END_KEYS = (("end", 1.0), ("end_sec", 1.0), ("stop", 1.0), ("end_ms", 0.001))
_NUM_KEYS = ("index", "slide_number", "slide", "n")
_DURATION_KEYS = ("duration_seconds", "duration_sec", "duration")

MAX_EMBEDDED_AUDIO_BYTES = 24 * 1024 * 1024


def _num(seg, keys):
    for key, scale in keys:
        v = seg.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v) * scale
    return None


def parse_sidecar(raw) -> dict | None:
    """Normalise a sidecar to {"duration_sec", "audio_file", "cues"} or None.

    `cues` are 0-based segment indices in the producer's own numbering — this
    function does not decide what they mean, `load_narration` does.
    """
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
        idx = next((seg[k] for k in _NUM_KEYS
                    if isinstance(seg.get(k), int) and not isinstance(seg.get(k), bool)),
                   i)
        cues.append({"index": int(idx), "start": start, "end": _num(seg, _END_KEYS)})

    base = min(c["index"] for c in cues)
    if base:                       # a 1-based producer
        for c in cues:
            c["index"] -= base

    cues.sort(key=lambda c: c["start"])
    duration = next((float(raw[k]) for k in _DURATION_KEYS
                     if isinstance(raw.get(k), (int, float))), None)
    for i, c in enumerate(cues):
        if c["end"] is None:
            c["end"] = cues[i + 1]["start"] if i + 1 < len(cues) else duration
    if cues[-1]["end"] is None:
        cues[-1]["end"] = cues[-1]["start"] + 30.0

    return {"audio_file": raw.get("audio_file") or raw.get("audio") or "",
            "duration_sec": duration,
            "voice": raw.get("voice") or "",
            "style": raw.get("style") or "",
            "cues": cues}


def find_sidecar(media_dir, audio_id: str) -> Path | None:
    """The sidecar for one audio render. `audio_id` is required: nothing else
    in the file identifies which answer it narrates, so guessing from
    modification time would eventually play one answer over another's slides."""
    if not audio_id:
        return None
    d = Path(media_dir)
    if not d.is_dir():
        return None
    for suffix in SIDECAR_SUFFIXES:
        p = d / f"{audio_id}{suffix}"
        if p.is_file():
            return p
    return None


def _find_audio(media_dir, audio_id: str, named: str) -> Path | None:
    d = Path(media_dir)
    if named:
        cand = d / os.path.basename(named)
        if cand.is_file():
            return cand
    for ext in (".mp3", ".m4a", ".wav"):
        cand = d / f"{audio_id}{ext}"
        if cand.is_file():
            return cand
    return None


def _mime(suffix: str) -> str:
    return {".mp3": "audio/mpeg", ".m4a": "audio/mp4",
            ".wav": "audio/wav"}.get(suffix.lower(), "audio/mpeg")


def load_narration(media_dir, audio_id: str, spec_slide_count: int = 0,
                   spec_to_section=None) -> dict | None:
    """Return the deck's narration block, or None.

    `spec_to_section` maps a spec-slide index onto the deck section that slide
    became (a spec slide can expand to several sections under the §1.3 body
    budget; the FIRST is the one to land on). Auto-advance is armed only when
    the sidecar's segment count matches `spec_slide_count`, and `sync_note`
    always states which it is.

    Audio is embedded as a data URI so the deck stays one file (§3.1); a render
    over 24 MB is left as a relative src instead, because a base64 payload that
    large makes the HTML unusable and a deck that opens without audio beats a
    deck that will not open.
    """
    path = find_sidecar(media_dir, audio_id)
    if path is None:
        return None
    try:
        parsed = parse_sidecar(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [webdeck] narration sidecar unreadable ({e}); deck built without audio")
        return None
    if not parsed:
        return None

    audio_path = _find_audio(media_dir, audio_id, parsed["audio_file"])
    if audio_path is None:
        return None

    n = len(parsed["cues"])
    synced = bool(spec_slide_count) and n == spec_slide_count
    if synced:
        mapping = spec_to_section or {}
        cues = [{"slide": int(mapping.get(c["index"], c["index"])) + 1,
                 "start": c["start"], "end": c["end"]}
                for c in parsed["cues"]]
        note = ""
    else:
        cues = []
        note = (f"Auto-advance off — this narration is cut into {n} sections "
                f"and the deck has {spec_slide_count} slides, so the timings "
                f"do not describe these slides.")

    result = {"cues": cues, "synced": synced, "sync_note": note,
              "duration_sec": parsed["duration_sec"],
              "voice": parsed["voice"], "style": parsed["style"],
              "audio_mime": _mime(audio_path.suffix), "audio_src": ""}
    try:
        if audio_path.stat().st_size <= MAX_EMBEDDED_AUDIO_BYTES:
            b64 = base64.b64encode(audio_path.read_bytes()).decode("ascii")
            result["audio_src"] = f"data:{result['audio_mime']};base64,{b64}"
        else:
            result["audio_src"] = audio_path.name
            result["external_audio"] = True
    except Exception as e:
        print(f"  [webdeck] narration audio unreadable ({e}); deck built without audio")
        return None
    return result
