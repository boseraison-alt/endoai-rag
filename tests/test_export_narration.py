"""The video and pptx exports must narrate through narration.py, not the
legacy TTS call — PRESENTATION_WORKLIST §4.1/§4.2/§4.5.

Phase 3 built the narration upgrade and wired only run_generate_audio to it.
run_generate_video's `_tts_one` and run_generate_slides' `_tts_pptx` still
called `_oai_tts.audio.speech.create(model="tts-1", voice=voice, ...)`
directly, so a demo video said "er cr ysgg" while the audio export of the same
answer said "erbium chromium Y-S-G-G", and neither job logged a cost row.

WHY THESE JOBS USE synthesize_segment AND NOT synthesize_lecture. Both do
PER-SLIDE TTS: run_generate_video pairs each mp3 with its own slide image
(ffmpeg `-loop 1 -i slide.png -i slide.mp3 -shortest`, so the clip's length IS
that slide's audio length), and run_generate_slides injects each slide's bytes
into its own pptx slide part. One continuous lecture MP3 has no per-slide
boundary to pair against, so routing them through synthesize_lecture would
destroy slide/audio sync. They take the narration PRIMITIVES instead —
dictionary, resolved voice/model, one cost row — on boundaries they own.
`test_video_audio_is_one_file_per_slide` pins that structural fact so a later
"simplification" to synthesize_lecture cannot pass silently.

The OpenAI call is stubbed; ffmpeg is NOT, so the video test assembles a real
MP4 and its durations are measured.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import endo_ai
import narration

HAVE_FFMPEG = (shutil.which("ffmpeg") is not None
               and shutil.which("ffprobe") is not None)

# Speaker notes carrying dictionary terms in their natural clinical wording,
# plus the markdown and [[PMID:N]] markers a history-loaded answer drags in.
NOTES_ONE = ("The **Er,Cr:YSGG** laser was compared against 5.25% NaOCl "
             "irrigation [[PMID:28294701]] at 500µm depth.")
NOTES_TWO = ("Nd:YAG and Er:YAG groups both received 17% EDTA, with MTA "
             "placed after apexification.")

EXPECTED_SPOKEN = [
    "erbium chromium Y-S-G-G",
    "sodium hypochlorite",
    "neodymium YAG",
    "erbium YAG",
    "E-D-T-A",
    "M-T-A",
]
FORBIDDEN_IN_SPOKEN = ["Er,Cr:YSGG", "NaOCl", "Nd:YAG", "EDTA", "[[PMID:", "**"]


@pytest.fixture(autouse=True)
def isolate_cost_log(tmp_path, monkeypatch):
    """Never let a test append to the real cost_log.jsonl."""
    monkeypatch.setattr(endo_ai, "_COST_LOG_PATH",
                        str(tmp_path / "cost_log.jsonl"))
    return tmp_path / "cost_log.jsonl"


def _silent_mp3(seconds: float, path: Path) -> bytes:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "anullsrc=r=24000:cl=mono", "-t", str(seconds),
         "-b:a", "32k", str(path)],
        check=True,
    )
    return path.read_bytes()


def _png(path: Path) -> bytes:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "color=c=navy:s=320x180:d=1", "-frames:v", "1", str(path)],
        check=True,
    )
    return path.read_bytes()


@pytest.fixture
def tts_spy(monkeypatch, tmp_path):
    """Record every synthesis request; return real mp3 bytes.

    Also poisons app._oai_tts, so a call site that reverts to the legacy
    `_oai_tts.audio.speech.create(model="tts-1", ...)` path raises instead of
    quietly producing audio the dictionary never touched.
    """
    calls = []

    def _speak(text, voice, model):
        calls.append({"text": text, "voice": voice, "model": model})
        secs = max(0.5, round(len(text) / 400.0, 2))
        return _silent_mp3(secs, tmp_path / f"seg{len(calls)}.mp3")

    monkeypatch.setattr(narration, "openai_available", lambda: True)
    monkeypatch.setattr(narration, "_speak_openai", _speak)

    import app

    class _Poisoned:
        def __getattr__(self, name):
            raise AssertionError(
                "legacy _oai_tts path used — narration dictionary, voice "
                "resolution and cost logging are all bypassed there")

    monkeypatch.setattr(app, "_oai_tts", _Poisoned())
    monkeypatch.setattr(app, "OPENAI_TTS_AVAILABLE", True)
    return calls


def _cost_rows(path: Path) -> list:
    if not Path(path).exists():
        return []
    return [json.loads(l) for l in Path(path).read_text(
        encoding="utf-8").splitlines() if l.strip()]


# ── run_generate_video ────────────────────────────────────

@pytest.fixture
def video_job(monkeypatch, tmp_path):
    """Run run_generate_video through its real route with stubbed content."""
    import app

    slides = [
        {"title": "Laser disinfection", "bullets": ["a"],
         "speaker_notes": NOTES_ONE},
        {"title": "Comparators", "bullets": ["b"],
         "speaker_notes": NOTES_TWO},
    ]
    monkeypatch.setattr(endo_ai, "generate_slides_content",
                        lambda *a, **k: {"title": "Lasers", "slides": slides})
    png = _png(tmp_path / "slide.png")
    monkeypatch.setattr(app, "_render_slide_image", lambda *a, **k: png)
    monkeypatch.setattr(app, "_apply_random_palette", lambda *a, **k: None)
    monkeypatch.setattr(app, "_persist_media", lambda *a, **k: None)

    def _run(audio_id="vid-job-1", voice=""):
        with app.audio_jobs_lock:
            app.audio_jobs[audio_id] = {
                "status": "running", "file_path": None, "error": None,
                "file_ext": "mp4", "type": "video", "question": "q",
                "length_minutes": 5, "slides_done": 0, "slides_total": 0,
            }
        app.run_generate_video(audio_id, "answer", "question", 5, voice)
        with app.audio_jobs_lock:
            return dict(app.audio_jobs[audio_id])

    return _run


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe not on PATH")
def test_video_narration_applies_the_pronunciation_dictionary(tts_spy, video_job):
    job = video_job()
    assert job["status"] == "complete", job.get("error")
    assert tts_spy, "no TTS request was made"

    spoken = "\n".join(c["text"] for c in tts_spy)
    for term in EXPECTED_SPOKEN:
        assert term in spoken, f"{term!r} never reached the speech engine"
    for raw in FORBIDDEN_IN_SPOKEN:
        assert raw not in spoken, f"raw {raw!r} was sent to the speech engine"


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe not on PATH")
def test_video_uses_the_resolved_voice_and_model_not_tts_1(tts_spy, video_job,
                                                           monkeypatch):
    monkeypatch.delenv("TTS_VOICE", raising=False)
    monkeypatch.delenv("TTS_MODEL", raising=False)
    video_job()
    assert {c["model"] for c in tts_spy} == {narration.DEFAULT_TTS_MODEL}
    assert narration.DEFAULT_TTS_MODEL != "tts-1", \
        "the legacy model — this assertion is what the fix is about"
    # voice="" used to be forwarded verbatim, which the API rejects with a 400.
    assert {c["voice"] for c in tts_spy} == {narration.DEFAULT_TTS_VOICE}


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe not on PATH")
def test_tts_voice_env_var_changes_the_video_voice(tts_spy, video_job,
                                                   monkeypatch):
    monkeypatch.setenv("TTS_VOICE", "fable")
    video_job()
    assert {c["voice"] for c in tts_spy} == {"fable"}


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe not on PATH")
def test_video_logs_exactly_one_tts_cost_row_with_the_job_id(
        tts_spy, video_job, isolate_cost_log):
    video_job(audio_id="vid-cost-7")
    rows = [r for r in _cost_rows(isolate_cost_log) if r.get("kind") == "tts"]
    assert len(rows) == 1, f"expected one cost row per export, got {len(rows)}"
    row = rows[0]
    assert row["request_id"] == "vid-cost-7"
    assert row["function"] == "run_generate_video"
    assert row["model"] == narration.DEFAULT_TTS_MODEL
    assert row["voice"] == narration.DEFAULT_TTS_VOICE
    # Characters are the SPOKEN text summed across slides, so the row prices
    # what was actually sent, not the un-expanded notes.
    assert row["characters"] == sum(len(c["text"]) for c in tts_spy)
    assert row["cost_usd"] > 0


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe not on PATH")
def test_video_audio_is_one_file_per_slide_and_stays_in_sync(tts_spy, video_job):
    """The structural reason synthesize_lecture cannot be used here.

    One TTS request per slide, and the finished MP4's duration equals the sum
    of the per-slide audio durations. A single continuous lecture file would
    give one request for the whole deck and no per-slide boundary to pair with
    each image.
    """
    job = video_job()
    assert len(tts_spy) == 2, \
        "expected one TTS request per slide; a merged script breaks sync"

    out = job["file_path"]
    total = narration.probe_duration_seconds(out)
    per_slide = [max(0.5, round(len(c["text"]) / 400.0, 2)) for c in tts_spy]
    # AAC re-encode and concat add frame-alignment padding; a whole slide's
    # worth of drift is what desync looks like.
    assert abs(total - sum(per_slide)) < 1.0, \
        f"video {total}s vs summed slide audio {sum(per_slide)}s"

    streams = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", out],
        capture_output=True, text=True).stdout
    assert "audio" in streams, "finished video has no audio stream"


# ── run_generate_slides ───────────────────────────────────

class _FakePrs:
    slides = [object(), object()]

    def save(self, path):
        Path(path).write_bytes(b"PK\x03\x04fake-pptx")


@pytest.fixture
def slides_job(monkeypatch):
    """Run run_generate_slides through its real route with stubbed content."""
    import app
    import slide_spec_cache
    import presentations.build_deck as build_deck
    import presentations.chart_data as chart_data

    deck = {"title": "Lasers", "slides": [{"title": "a"}, {"title": "b"}]}
    monkeypatch.setattr(slide_spec_cache, "get_or_build",
                        lambda *a, **k: (deck, "hash123456789", False))
    # slides_queue rows are (slide_obj, notes_text, slide_num_1based).
    queue = [(object(), NOTES_ONE, 1), (object(), NOTES_TWO, 2)]
    monkeypatch.setattr(build_deck, "build_deck_from_specs",
                        lambda *a, **k: (_FakePrs(), queue))
    monkeypatch.setattr(chart_data, "tier_counts_from_papers",
                        lambda *a, **k: {})
    monkeypatch.setattr(app, "_persist_media", lambda *a, **k: None)
    monkeypatch.setattr(app, "_inject_audio_into_pptx",
                        lambda base, audios: base)

    def _run(audio_id="pptx-job-1", voice=""):
        with app.audio_jobs_lock:
            app.audio_jobs[audio_id] = {
                "status": "running", "file_path": None, "error": None,
                "type": "pptx", "question": "q", "length_minutes": 5,
                "slides_done": 0, "slides_total": 0,
            }
        app.run_generate_slides(audio_id, "answer", "question", 5, voice, [])
        with app.audio_jobs_lock:
            return dict(app.audio_jobs[audio_id])

    return _run


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not on PATH")
def test_slides_narration_applies_the_pronunciation_dictionary(tts_spy,
                                                               slides_job):
    job = slides_job()
    assert job["status"] == "complete", job.get("error")
    assert tts_spy, "no TTS request was made"

    spoken = "\n".join(c["text"] for c in tts_spy)
    for term in EXPECTED_SPOKEN:
        assert term in spoken, f"{term!r} never reached the speech engine"
    for raw in FORBIDDEN_IN_SPOKEN:
        assert raw not in spoken, f"raw {raw!r} was sent to the speech engine"


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not on PATH")
def test_slides_use_the_resolved_voice_and_model_not_tts_1(tts_spy, slides_job,
                                                           monkeypatch):
    monkeypatch.delenv("TTS_VOICE", raising=False)
    monkeypatch.delenv("TTS_MODEL", raising=False)
    slides_job()
    assert {c["model"] for c in tts_spy} == {narration.DEFAULT_TTS_MODEL}
    assert {c["voice"] for c in tts_spy} == {narration.DEFAULT_TTS_VOICE}


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not on PATH")
def test_tts_voice_env_var_changes_the_slides_voice(tts_spy, slides_job,
                                                    monkeypatch):
    monkeypatch.setenv("TTS_VOICE", "sage")
    slides_job()
    assert {c["voice"] for c in tts_spy} == {"sage"}


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not on PATH")
def test_slides_log_exactly_one_tts_cost_row_with_the_job_id(
        tts_spy, slides_job, isolate_cost_log):
    slides_job(audio_id="pptx-cost-9")
    rows = [r for r in _cost_rows(isolate_cost_log) if r.get("kind") == "tts"]
    assert len(rows) == 1, f"expected one cost row per export, got {len(rows)}"
    assert rows[0]["request_id"] == "pptx-cost-9"
    assert rows[0]["function"] == "run_generate_slides"
    assert rows[0]["characters"] == sum(len(c["text"]) for c in tts_spy)


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not on PATH")
def test_slides_audio_is_one_segment_per_slide(tts_spy, slides_job):
    """Same structural pin as the video: per-slide bytes, per-slide part."""
    slides_job()
    assert len(tts_spy) == 2, \
        "expected one TTS request per slide; merged narration cannot be " \
        "injected into individual pptx slide parts"


# ── The shared primitive ──────────────────────────────────

def test_synthesize_segment_never_truncates_long_notes(monkeypatch):
    """The legacy call sites sent `notes[:4096]` and dropped the rest."""
    sent = []

    def _speak(text, voice, model):
        sent.append(text)
        return b"\xff\xfb" + b"\x00" * 64

    monkeypatch.setattr(narration, "openai_available", lambda: True)
    monkeypatch.setattr(narration, "_speak_openai", _speak)

    long_notes = "The canal was irrigated with NaOCl. " * 400
    seg = narration.synthesize_segment(long_notes)

    assert len(sent) > 1, "over-long notes should split, not truncate"
    assert all(len(t) <= narration.CHUNK_CHARS for t in sent)
    joined = " ".join(sent)
    assert joined.count("sodium hypochlorite") == 400
    assert seg["characters"] == len(narration.prepare_for_speech(long_notes))


def test_synthesize_segment_does_not_mutate_the_displayed_notes(monkeypatch):
    monkeypatch.setattr(narration, "openai_available", lambda: False)
    original = NOTES_ONE
    narration.synthesize_segment(original, allow_gtts=False)
    assert original == NOTES_ONE, "displayed speaker notes were rewritten"


def test_empty_notes_produce_no_request_and_no_cost(monkeypatch):
    monkeypatch.setattr(narration, "openai_available", lambda: True)
    monkeypatch.setattr(narration, "_speak_openai",
                        lambda *a: pytest.fail("spoke an empty segment"))
    seg = narration.synthesize_segment("   \n  ")
    assert seg["audio"] == b""
    assert seg["characters"] == 0


class TestPodcastBranchUsesTheDictionary:
    """The conversation/podcast export was the last path still calling the raw
    TTS API, so a podcast said "er cr ysgg" while every other export said
    "erbium chromium Y-S-G-G". Two voices are deliberate there, so it cannot
    use resolve_voice() — but the dictionary, the model and the cost row all
    apply."""

    def _source(self):
        import inspect, app
        return inspect.getsource(app.run_generate_audio)

    def test_podcast_does_not_call_the_raw_tts_api(self):
        src = self._source()
        conv = src[src.index("conversation"):src.index("LECTURE style")]
        assert "_oai_tts.audio.speech.create" not in conv, (
            "the podcast branch is back on the legacy call and will speak raw "
            "notation")

    def test_podcast_goes_through_synthesize_segment(self):
        src = self._source()
        conv = src[src.index("conversation"):src.index("LECTURE style")]
        assert "narration.synthesize_segment" in conv

    def test_podcast_logs_one_cost_row(self):
        src = self._source()
        conv = src[src.index("conversation"):src.index("LECTURE style")]
        assert "log_narration_cost" in conv

    def test_podcast_keeps_two_distinct_host_voices(self):
        """The fix must not collapse the two hosts onto one voice."""
        src = self._source()
        conv = src[src.index("conversation"):src.index("LECTURE style")]
        assert "HOST1_VOICE" in conv and "HOST2_VOICE" in conv
        assert "onyx" in conv and "nova" in conv
