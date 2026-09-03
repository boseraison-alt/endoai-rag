"""Narration synthesis (PRESENTATION_WORKLIST §4.1, §4.3, §4.5).

Two entry points, one for each shape of narration job.

`synthesize_lecture()` — the audio export. Takes a lecture script and produces:

  * an MP3, spoken by OpenAI TTS (primary) or gTTS (fallback only);
  * a sidecar timestamp map, so the web deck can auto-advance slides against
    the audio;
  * a line in cost_log.jsonl, priced per character like every other API call.

`synthesize_segment()` — the video and pptx exports. Those do PER-SLIDE TTS,
because each clip must be paired with its own slide, so they cannot take one
continuous file. It applies the same dictionary and the same voice/model
resolution to a segment whose boundary the caller already owns, and hands back
the character count so the job can log ONE cost row (`log_narration_cost`).

The pronunciation dictionary is applied here, at the boundary between the
written script and the speech engine — the script object the caller holds is
never mutated, so displayed text keeps its clinical notation.

Why the call sites live in app.py but the logic lives here: app.py's
run_generate_audio / run_generate_video / run_generate_slides all reimplemented
the same chunk-synthesise-concatenate loop with no timing, no dictionary and no
cost record. This module is the single implementation they can share.
"""

import io
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime

from pronunciation import apply_pronunciation

# app.py loads .env before importing anything, but this module is also driven
# from scripts and tests. Without its own load_dotenv, OPENAI_API_KEY is unset,
# openai_available() returns False and the export silently degrades to gTTS —
# which is exactly the regression §4.1 exists to prevent.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ── Voice and model selection (§4.1) ──────────────────────
# onyx is the chosen professional voice: the deepest and most level of the
# OpenAI set, and the one that reads long-form clinical prose without the
# upward inflection that makes nova/shimmer sound conversational. A continuing
# education lecture wants a lecturer. Override per install with TTS_VOICE.
DEFAULT_TTS_VOICE = "onyx"

# tts-1-hd is what the lecture path already used; keeping it preserves the
# current audio quality. TTS_MODEL can drop an install to tts-1 for half the
# cost (see endo_ai.TTS_PRICING).
DEFAULT_TTS_MODEL = "tts-1-hd"

# The OpenAI speech API rejects unknown voices with a 400. An install that
# typos TTS_VOICE should get the default and a warning, not a dead export.
OPENAI_VOICES = {"alloy", "ash", "ballad", "coral", "echo", "fable",
                 "nova", "onyx", "sage", "shimmer", "verse"}

# The speech endpoint caps input at 4096 characters. 4000 leaves headroom for
# the pronunciation dictionary, whose substitutions are net-expanding
# ("NaOCl" -> "sodium hypochlorite").
CHUNK_CHARS = 4000

TIMESTAMP_MAP_VERSION = 1

MEDIA_DIR = os.environ.get(
    "NARRATION_MEDIA_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_media"),
)


def resolve_voice(requested: str = None) -> str:
    """Voice precedence: explicit request > TTS_VOICE env > DEFAULT_TTS_VOICE."""
    for candidate in (requested, os.environ.get("TTS_VOICE"), DEFAULT_TTS_VOICE):
        if not candidate:
            continue
        candidate = candidate.strip()
        if candidate in OPENAI_VOICES:
            return candidate
        print(f"  [narration] Unknown TTS voice {candidate!r} — ignoring")
    return DEFAULT_TTS_VOICE


def resolve_model(requested: str = None) -> str:
    """Model precedence: explicit request > TTS_MODEL env > DEFAULT_TTS_MODEL."""
    return (requested or os.environ.get("TTS_MODEL") or DEFAULT_TTS_MODEL).strip()


# ── Script sectioning ─────────────────────────────────────

_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*\S)\s*$")
# "Module 3 — Clinical protocols", "Module 3: ...", "Module 3 - ..."
_MODULE_LINE = re.compile(r"^\s*(Module\s+\d+\b.*)$", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# Below this, a paragraph is folded into the one before it rather than becoming
# its own slide — a two-line transition is not a section.
MIN_SECTION_CHARS = 320


def _title_from(text: str, limit: int = 70) -> str:
    """First clause of a passage, as a slide-sized title."""
    first = _SENTENCE_END.split(text.strip(), 1)[0].strip()
    first = re.sub(r"\s+", " ", first)
    if len(first) <= limit:
        return first.rstrip(".")
    return first[:limit].rsplit(" ", 1)[0] + "…"


def split_script_sections(script: str) -> list:
    """Split a lecture script into narration sections.

    Prefers explicit structure — markdown headings, or "Module N" lines, which
    is what the curriculum stitcher emits — and falls back to paragraph
    boundaries for the plain prose that generate_audio_script() returns.

    Returns [{"title": str, "text": str}]. Callers that already know the slide
    boundaries (slide speaker notes, curriculum modules) should pass those to
    synthesize_lecture(sections=...) instead of relying on this.
    """
    if not script or not script.strip():
        return []

    blocks = []          # [{"title": str|None, "text": str}]
    pending_title = None
    for para in re.split(r"\n\s*\n", script):
        para = para.strip()
        if not para:
            continue
        lines = para.splitlines()
        head = _HEADING.match(lines[0]) or _MODULE_LINE.match(lines[0])
        if head and len(lines) == 1:
            # A heading alone in its paragraph titles whatever comes next.
            pending_title = head.group(2) if head.re is _HEADING else head.group(1)
            continue
        if head:
            title = head.group(2) if head.re is _HEADING else head.group(1)
            body = "\n".join(lines[1:]).strip()
            blocks.append({"title": title, "text": body or title})
            pending_title = None
            continue
        blocks.append({"title": pending_title, "text": para})
        pending_title = None

    # Fold runt paragraphs into their predecessor so a "Let's move on." line
    # does not become a slide of its own.
    merged = []
    for b in blocks:
        if (merged and b["title"] is None
                and len(b["text"]) < MIN_SECTION_CHARS
                and len(merged[-1]["text"]) < CHUNK_CHARS):
            merged[-1]["text"] += "\n\n" + b["text"]
        else:
            merged.append(dict(b))

    for i, b in enumerate(merged):
        if not b["title"]:
            b["title"] = _title_from(b["text"])
        b["index"] = i
    return merged


# ── Speech cleanup ────────────────────────────────────────
# generate_audio_script() is prompted to emit plain prose, but narration can
# also be driven straight from a curriculum answer (history-loaded exports), and
# that text carries markdown and raw [[PMID:N]] markers. Spoken aloud they
# become "star star" and "bracket bracket P M I D". Stripped for speech only —
# the displayed text keeps every marker.
_PMID_MARKER = re.compile(r"\[\[PMID:\s*\d+\s*\]\]")
# A marker whose closing brackets a truncation removed. The DOUBLE bracket is
# what makes this safe: prose that mentions "a PMID marker" has no `[[`, so
# this can only ever eat a fragment. Whole markers are already gone by the
# time it runs.
_PARTIAL_PMID_MARKER = re.compile(r"\[\[\s*PMID\s*:?\s*\d*\s*\]?")
# The REFERENCES list uses the SINGLE-bracket bibliographic form on purpose —
# the synthesis prompt mandates `[PMID: N]` there and the renderer relies on it
# to tell a reference key from an inline marker. Both patterns above require
# DOUBLE brackets, so every reference line was read aloud as "P M I D three six
# one five six eight oh four".
#
# Found by test_narration when a curriculum generated during the A30d eval
# became the newest file in learn_history/ and carried a REFERENCES block the
# older fixture did not have. The digits are required, so this can only match a
# real key.
_REF_PMID_KEY = re.compile(r"\[PMID:\s*\d+\s*\]")
_HRULE       = re.compile(r"^\s*([-*_])\s*(?:\1\s*){2,}$", re.MULTILINE)
_ATX         = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_BULLET      = re.compile(r"^\s{0,3}[-*+]\s+", re.MULTILINE)
_EMPHASIS    = re.compile(r"(\*{1,3}|_{2,})(?=\S)(.+?)(?<=\S)\1", re.DOTALL)
_MDLINK      = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def strip_markdown_for_speech(text: str) -> str:
    """Remove markup and citation markers that a TTS engine would read aloud."""
    if not text:
        return text
    text = _PMID_MARKER.sub("", text)
    # A marker cut in half by a character-count truncation upstream. The
    # citation-support block quotes a claim at 140 characters and a merged
    # claim carries markers INSIDE it, so a real curriculum ended a quoted
    # claim with a bare "[[PMID:". `_PMID_MARKER` needs the closing brackets
    # and cannot see that, and a TTS engine reads it aloud letter by letter.
    # Fixed at the source in `endo_ai._quote_claim`; belt and braces here
    # because narration is the last thing between a marker and a clinician's
    # ears.
    text = _PARTIAL_PMID_MARKER.sub("", text)
    text = _REF_PMID_KEY.sub("", text)
    text = _MDLINK.sub(r"\1", text)
    text = _HRULE.sub("", text)
    text = _ATX.sub("", text)
    text = _BULLET.sub("", text)
    text = _EMPHASIS.sub(r"\2", text)
    text = re.sub(r"`+", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # " ." / " ," left behind where a marker sat mid-sentence.
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return text.strip()


def prepare_for_speech(text: str) -> str:
    """Full narration-script preparation: strip markup, then pronounce.

    The only place the pronunciation dictionary is applied. Order matters —
    emphasis markers around a term ("**Er:YAG**") must go before the dictionary
    tries to match it.
    """
    return apply_pronunciation(strip_markdown_for_speech(text))


def _split_long_text(text: str, limit: int) -> list:
    """Break an over-long passage at sentence boundaries, then hard-wrap."""
    parts, current = [], ""
    for sentence in _SENTENCE_END.split(text):
        if not sentence:
            continue
        candidate = (current + " " + sentence).strip() if current else sentence
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                parts.append(current)
            while len(sentence) > limit:
                parts.append(sentence[:limit])
                sentence = sentence[limit:]
            current = sentence
    if current:
        parts.append(current)
    return parts or [""]


def pack_chunks(sections: list, limit: int = CHUNK_CHARS,
                merge: bool = True) -> list:
    """Pack spoken section text into TTS requests on section boundaries.

    Packing whole sections into each request (rather than slicing the script
    every `limit` characters) is what makes the timestamp map accurate: each
    request's MP3 is probed individually, so a chunk that holds exactly one
    section gives that section an exact, measured start and end.

    `merge=False` takes that to its conclusion: never put two sections in one
    request, so EVERY boundary is measured rather than interpolated by
    character share. That is what a deck needs — the web deck arms
    auto-advance only when the sidecar has one segment per slide, and a
    boundary estimated from character count would advance the slide at
    roughly, not exactly, the sentence that belongs to it. It costs more
    requests for the same characters, so the bill is unchanged and the wall
    time is longer.

    Returns [{"text": str, "spans": [{"section": i, "chars": n}]}].
    """
    chunks = []
    cur_text, cur_spans = "", []

    def flush():
        nonlocal cur_text, cur_spans
        if cur_text.strip():
            chunks.append({"text": cur_text, "spans": cur_spans})
        cur_text, cur_spans = "", []

    for sec in sections:
        text = sec["spoken"]
        if not text.strip():
            continue
        if len(text) > limit or not merge:
            flush()
            pieces = (_split_long_text(text, limit) if len(text) > limit
                      else [text])
            for piece in pieces:
                chunks.append({"text": piece,
                               "spans": [{"section": sec["index"],
                                          "chars": len(piece)}]})
            continue
        joiner = "\n\n" if cur_text else ""
        if len(cur_text) + len(joiner) + len(text) > limit:
            flush()
            joiner = ""
        cur_text += joiner + text
        cur_spans.append({"section": sec["index"], "chars": len(text)})
    flush()
    return chunks


# ── Duration probing ──────────────────────────────────────

def probe_duration_seconds(path: str) -> float:
    """True duration of an audio file via ffprobe. 0.0 if it cannot be read."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=60,
        )
        return round(float(out.stdout.strip()), 3)
    except Exception as e:
        print(f"  [narration] ffprobe failed on {os.path.basename(path)}: {e}")
        return 0.0


def _probe_bytes(data: bytes) -> float:
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    try:
        tmp.write(data)
        tmp.close()
        return probe_duration_seconds(tmp.name)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


# ── Timestamp map (§4.3) ──────────────────────────────────

def build_timestamp_map(audio_id: str, sections: list, chunks: list,
                        chunk_durations: list, total_duration: float,
                        *, voice: str, model: str, backend: str,
                        style: str = "lecture") -> dict:
    """Map section boundaries onto audio timestamps.

    Chunk durations are measured, not estimated. Where a chunk holds several
    sections the boundary inside it is interpolated by character count, which
    is the best available proxy for speech time at constant voice and rate.

    Measured chunk durations are rescaled to the probed duration of the final
    concatenated file, so the last section always ends exactly at the end of
    the audio and the deck never runs past its own soundtrack.
    """
    measured_total = sum(chunk_durations) or 0.0
    scale = (total_duration / measured_total) if measured_total > 0 else 1.0

    bounds = {}          # section index -> [start, end]
    cursor = 0.0
    for chunk, dur in zip(chunks, chunk_durations):
        dur = dur * scale
        chunk_chars = sum(s["chars"] for s in chunk["spans"]) or 1
        offset = cursor
        for span in chunk["spans"]:
            share = dur * (span["chars"] / chunk_chars)
            idx = span["section"]
            if idx in bounds:
                bounds[idx][1] = offset + share
            else:
                bounds[idx] = [offset, offset + share]
            offset += share
        cursor += dur

    slides = []
    for sec in sections:
        if sec["index"] not in bounds:
            continue
        start, end = bounds[sec["index"]]
        slides.append({
            "index":      len(slides),
            "title":      sec["title"],
            "start":      round(max(0.0, start), 3),
            "end":        round(min(total_duration or end, end), 3),
            "char_start": sec.get("char_start", 0),
            "char_end":   sec.get("char_end", 0),
            "preview":    re.sub(r"\s+", " ", sec["text"]).strip()[:240],
        })
    if slides and total_duration:
        slides[-1]["end"] = round(total_duration, 3)

    return {
        "version":          TIMESTAMP_MAP_VERSION,
        "audio_id":         audio_id,
        "style":            style,
        "backend":          backend,
        "voice":            voice,
        "model":            model,
        "duration_seconds": round(total_duration, 3),
        "total_chars":      sum(len(s["spoken"]) for s in sections),
        "created_at":       datetime.now().isoformat(),
        "slides":           slides,
    }


def sidecar_path(audio_id: str, media_dir: str = None) -> str:
    return os.path.join(media_dir or MEDIA_DIR, f"{audio_id}.timestamps.json")


def write_timestamp_map(tmap: dict, media_dir: str = None) -> str:
    """Persist the map next to the MP3. Returns the path, or '' on failure."""
    path = sidecar_path(tmap.get("audio_id", "unknown"), media_dir)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(tmap, fh, indent=2)
        return path
    except Exception as e:
        print(f"  [narration] timestamp map write failed: {e}")
        return ""


def load_timestamp_map(audio_id: str, media_dir: str = None) -> dict:
    """Read a sidecar map back. Returns {} when there is none."""
    try:
        with open(sidecar_path(audio_id, media_dir), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


# ── Speech backends ───────────────────────────────────────

_client_cache = {}


def openai_client():
    """Lazy OpenAI client. None when the SDK or the key is missing."""
    if "c" not in _client_cache:
        client = None
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            # Loud, because the consequence is a silent quality downgrade to
            # gTTS rather than a failure anyone would notice.
            print("  [narration] OPENAI_API_KEY not set — narration will use "
                  "the gTTS fallback voice")
        else:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=key)
            except Exception as e:
                print(f"  [narration] OpenAI client unavailable ({e}) — "
                      "falling back to gTTS")
        _client_cache["c"] = client
    return _client_cache["c"]


def openai_available() -> bool:
    return openai_client() is not None


def _speak_openai(text: str, voice: str, model: str) -> bytes:
    resp = openai_client().audio.speech.create(model=model, voice=voice,
                                               input=text[:4096])
    return resp.content


def _speak_gtts(text: str) -> bytes:
    from gtts import gTTS
    buf = io.BytesIO()
    gTTS(text=text[:5000], lang="en", slow=False).write_to_fp(buf)
    return buf.getvalue()


# ── Per-segment synthesis (video + pptx narration) ────────
# synthesize_lecture() speaks one continuous script and derives a timestamp map
# from it. That is right for the audio export, which is a single MP3, and wrong
# for the video and pptx exports: those do PER-SLIDE TTS, because each clip has
# to be paired with its own slide image (ffmpeg `-shortest` against the slide's
# own mp3) or embedded in its own pptx slide part. One continuous file has no
# per-slide boundary to pair against, so routing those jobs through
# synthesize_lecture would destroy slide/audio sync.
#
# What they actually need is the narration PRIMITIVES — dictionary, resolved
# voice/model, one cost row — applied to a segment whose boundary the caller
# already knows. That is this function.


def synthesize_segment(text: str, *, voice: str = None, model: str = None,
                       label: str = "", allow_gtts: bool = True) -> dict:
    """Speak ONE caller-bounded passage (a slide's speaker notes) to MP3 bytes.

    The caller owns the boundary — this never merges or re-splits segments
    across slides — so the audio it returns lines up with exactly one slide.

    Over-long passages are split at sentence boundaries and the resulting MP3s
    concatenated, which is what synthesize_lecture does within a chunk. The
    legacy call sites truncated at `notes[:4096]` instead, silently dropping the
    tail of any slide whose notes ran long.

    Returns {"audio", "backend", "voice", "model", "characters", "spoken"}.
    `audio` is b"" and `backend` "" when no backend produced anything; callers
    treat that as "this slide gets no narration", never as a hard failure.
    """
    voice = resolve_voice(voice)
    model = resolve_model(model)

    # The dictionary is applied HERE and nowhere else. `text` — the speaker
    # notes shown in the deck — is not mutated.
    spoken = prepare_for_speech(text or "")
    empty = {"audio": b"", "backend": "", "voice": voice, "model": model,
             "characters": 0, "spoken": spoken}
    if not spoken.strip():
        return empty

    pieces = _split_long_text(spoken, CHUNK_CHARS) if len(spoken) > CHUNK_CHARS \
        else [spoken]

    if openai_available():
        try:
            audio = b""
            for piece in pieces:
                audio += _speak_openai(piece, voice, model)
            if audio:
                return {"audio": audio, "backend": "openai", "voice": voice,
                        "model": model, "characters": len(spoken),
                        "spoken": spoken}
        except Exception as e:
            print(f"  [narration] OpenAI TTS failed for {label or 'segment'} "
                  f"({e}); falling back to gTTS")

    if allow_gtts:
        try:
            # gTTS is fallback only, and it is not billed — `characters` stays
            # 0 so a fallback segment never inflates the OpenAI cost row.
            return {"audio": _speak_gtts(spoken), "backend": "gtts",
                    "voice": voice, "model": model, "characters": 0,
                    "spoken": spoken}
        except Exception as e:
            print(f"  [narration] gTTS failed for {label or 'segment'}: {e}")

    return empty


def log_narration_cost(function_name: str, model: str, characters: int, *,
                       request_id: str, voice: str,
                       duration_seconds: float = None,
                       mode: str = "export") -> float:
    """One cost row for a whole per-slide narration job.

    Per-slide jobs make one API call per slide but are one billable export, so
    the characters are summed and logged once — /admin/costs then shows one
    line per export, matching what the audio path already writes. Logging can
    never break an export (HANDOVER bug class (d) cuts the other way here: the
    failure is printed, not swallowed silently).
    """
    if characters <= 0:
        return 0.0
    try:
        from endo_ai import log_tts_call
        cost = log_tts_call(function_name, model, characters, mode=mode,
                            request_id=request_id, voice=voice,
                            duration_seconds=duration_seconds)
        print(f"  [narration] {characters} chars, ${cost:.4f} "
              f"({model}, voice={voice})")
        return cost
    except Exception as e:
        print(f"  [narration] cost logging skipped: {e}")
        return 0.0


# ── Entry point ───────────────────────────────────────────

def synthesize_lecture(script: str, out_path: str, *, audio_id: str,
                       voice: str = None, model: str = None,
                       sections: list = None, style: str = "lecture",
                       mode: str = "export",
                       function_name: str = "run_generate_audio",
                       media_dir: str = None,
                       write_sidecar: bool = True,
                       per_section: bool = False) -> dict:
    """Speak `script` into `out_path` and emit its timestamp map.

    `sections` — optional [{"title", "text"}] to pin the map to known slide
    boundaries. Omitted, the script is split on its own structure.

    `per_section` — one TTS request per section, so every boundary in the map
    is measured rather than interpolated, and the map has exactly one entry
    per section supplied. This is what makes a sidecar the web deck can
    auto-advance on: `webdeck.narration.load_narration` arms auto-advance only
    when the segment count equals the slide count, and refuses to guess
    otherwise. A caller that wants a per-slide map must therefore pass one
    section per slide AND set this.

    Returns a summary dict: backend, voice, model, duration_seconds,
    characters, cost_usd, timestamp_map, sidecar_path.
    """
    voice = resolve_voice(voice)
    model = resolve_model(model)

    secs = []
    source = sections if sections else split_script_sections(script)
    cursor = 0
    for i, sec in enumerate(source):
        text = (sec.get("text") or "").strip()
        if not text:
            continue
        secs.append({
            "index":      len(secs),
            "title":      sec.get("title") or _title_from(text),
            "text":       text,
            # The dictionary is applied HERE and nowhere else: `text` above is
            # still the clinician-facing wording.
            "spoken":     prepare_for_speech(text),
            "char_start": cursor,
            "char_end":   cursor + len(text),
        })
        cursor += len(text)
    if not secs:
        raise ValueError("narration script is empty")

    chunks = pack_chunks(secs, merge=not per_section)
    total_chars = sum(len(c["text"]) for c in chunks)

    backend = ""
    chunk_durations = []
    audio = b""

    if openai_available():
        try:
            print(f"  [narration] OpenAI TTS: voice={voice} model={model} "
                  f"{len(chunks)} chunk(s), {total_chars} chars")
            for i, chunk in enumerate(chunks):
                data = _speak_openai(chunk["text"], voice, model)
                audio += data
                chunk_durations.append(_probe_bytes(data))
                print(f"    [{i+1}/{len(chunks)}] {len(chunk['text'])} chars "
                      f"-> {chunk_durations[-1]:.1f}s")
            backend = "openai"
        except Exception as e:
            print(f"  [narration] OpenAI TTS failed ({e}); falling back to gTTS")
            audio, chunk_durations, backend = b"", [], ""

    if not backend:
        # gTTS is fallback only. It has no per-request duration to measure, so
        # the whole script goes in one piece and section timings come from
        # character share of the probed total.
        print("  [narration] gTTS fallback")
        audio = _speak_gtts("\n\n".join(c["text"] for c in chunks))
        chunks = [{"text": "\n\n".join(c["text"] for c in chunks),
                   "spans": [{"section": s["index"], "chars": len(s["spoken"])}
                             for s in secs]}]
        chunk_durations = [0.0]
        backend = "gtts"

    if not audio:
        raise RuntimeError("No TTS backend produced audio")

    with open(out_path, "wb") as fh:
        fh.write(audio)

    total_duration = probe_duration_seconds(out_path)
    if backend == "gtts":
        chunk_durations = [total_duration]

    tmap = build_timestamp_map(audio_id, secs, chunks, chunk_durations,
                               total_duration, voice=voice, model=model,
                               backend=backend, style=style)

    written = write_timestamp_map(tmap, media_dir) if write_sidecar else ""

    cost = 0.0
    if backend == "openai":
        try:
            from endo_ai import log_tts_call
            cost = log_tts_call(function_name, model, total_chars, mode=mode,
                                request_id=audio_id,
                                duration_seconds=total_duration, voice=voice)
            print(f"  [narration] {total_chars} chars, {total_duration:.1f}s, "
                  f"${cost:.4f}")
        except Exception as e:
            print(f"  [narration] cost logging skipped: {e}")

    return {
        "backend":          backend,
        "voice":            voice,
        "model":            model,
        "duration_seconds": total_duration,
        "characters":       total_chars,
        "cost_usd":         cost,
        "timestamp_map":    tmap,
        "sidecar_path":     written,
        "file_path":        out_path,
    }
