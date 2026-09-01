"""Web-deck auto-advance: the 13-vs-34 mismatch, and what closes it.

`webdeck.narration.load_narration` arms auto-advance ONLY when the sidecar's
segment count equals the spec's slide count, and says so in the deck when it
does not. That refusal is correct and is not what these tests relax — advancing
34 slides against 13 unrelated boundaries would look like it worked while
showing the clinician the wrong slide for the sentence being spoken.

What was missing is a sidecar that CAN match. A lecture render is cut on the
narration script's own structure (13 sections for a 10-minute laser answer);
nothing derivable from it describes the 25 spec slides, because `char_start`
indexes the spoken script rather than the answer. So the narration has to be
recorded against the spec, one segment per slide.

Three things have to hold for that, and each fails silently otherwise:

  * one section per slide, none dropped — `synthesize_lecture` discards a
    section with empty text, and a slide with no speaker notes would take the
    count off by one from that slide onward;
  * one TTS REQUEST per section, so every boundary is measured rather than
    interpolated by character share;
  * a map that does not match must not be used at all — falling back to the
    unsynced render is right, arming auto-advance on a near-miss is not.
"""
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import narration
from webdeck.narration import load_narration, parse_sidecar

HAVE_FFMPEG = (shutil.which("ffmpeg") is not None
               and shutil.which("ffprobe") is not None)


def _silent_mp3(seconds: float, path: str) -> bytes:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "anullsrc=r=24000:cl=mono", "-t", str(seconds),
         "-b:a", "32k", path],
        check=True,
    )
    return Path(path).read_bytes()


@pytest.fixture
def fake_tts(monkeypatch, tmp_path):
    """Stub the API call; return REAL mp3 bytes, ~1 s per 400 chars."""
    monkeypatch.setattr(narration, "openai_available", lambda: True)
    calls = []

    def _speak(text, voice, model):
        calls.append(text)
        secs = max(0.5, round(len(text) / 400.0, 2))
        return _silent_mp3(secs, str(tmp_path / f"chunk{len(calls)}.mp3"))

    monkeypatch.setattr(narration, "_speak_openai", _speak)
    return calls


def _spec_slides(n, notes_chars=300):
    return [{"title": f"Slide {i + 1} title",
             "speaker_notes": f"Sentence {i + 1}. " * (notes_chars // 16)}
            for i in range(n)]


# ── one section per slide ────────────────────────────────────────────────

class TestSectionsAreOnePerSlide:
    def test_one_section_per_spec_slide(self):
        import app
        slides = _spec_slides(34)
        secs = app.build_deck_narration_sections(slides)
        assert len(secs) == 34

    def test_a_slide_with_no_notes_still_gets_a_section(self):
        """synthesize_lecture drops an empty section. A dropped section is one
        fewer segment than slides, which disarms auto-advance for the whole
        deck — and if it did not, every slide after it would be off by one."""
        import app
        slides = _spec_slides(4)
        slides[2]["speaker_notes"] = ""
        secs = app.build_deck_narration_sections(slides)
        assert len(secs) == 4
        assert secs[2]["text"].strip()
        assert "Slide 3 title" in secs[2]["text"]

    def test_a_slide_with_neither_notes_nor_title_still_gets_a_section(self):
        import app
        secs = app.build_deck_narration_sections(
            [{"title": "", "speaker_notes": ""}, {"title": "B",
                                                  "speaker_notes": "n"}])
        assert len(secs) == 2
        assert secs[0]["text"].strip()

    def test_order_is_spec_order(self):
        import app
        secs = app.build_deck_narration_sections(_spec_slides(6))
        assert [s["title"] for s in secs] == [f"Slide {i+1} title"
                                              for i in range(6)]


# ── one request per section ──────────────────────────────────────────────

class TestPackChunksPerSection:
    def _secs(self, n, chars=80):
        return [{"index": i, "spoken": "word " * (chars // 5)}
                for i in range(n)]

    def test_merge_true_packs_several_sections_into_one_request(self):
        chunks = narration.pack_chunks(self._secs(10), limit=4000, merge=True)
        assert len(chunks) < 10, "nothing was packed — the fixture is wrong"

    def test_merge_false_gives_each_section_its_own_request(self):
        """A shared request means one measured duration for two sections, and
        the boundary between them is then interpolated by character count.
        That is close enough for a lecture and wrong for a slide cue."""
        chunks = narration.pack_chunks(self._secs(10), limit=4000, merge=False)
        assert len(chunks) == 10
        for c in chunks:
            assert len(c["spans"]) == 1

    def test_merge_false_still_splits_an_over_long_section(self):
        secs = [{"index": 0, "spoken": "word " * 3000}]
        chunks = narration.pack_chunks(secs, limit=4000, merge=False)
        assert len(chunks) > 1
        assert all(len(c["text"]) <= 4000 for c in chunks)
        assert {s["section"] for c in chunks for s in c["spans"]} == {0}

    def test_merge_defaults_to_true_so_the_lecture_path_is_unchanged(self):
        a = narration.pack_chunks(self._secs(10), limit=4000)
        b = narration.pack_chunks(self._secs(10), limit=4000, merge=True)
        assert a == b


# ── the map the deck consumes ────────────────────────────────────────────

@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe not on PATH")
class TestThePerSlideMap:
    def _build(self, tmp_path, n=12, per_section=True):
        import app
        sections = app.build_deck_narration_sections(_spec_slides(n))
        out = tmp_path / "deck.mp3"
        return narration.synthesize_lecture(
            "", str(out), audio_id="deck-1", sections=sections,
            style="deck", media_dir=str(tmp_path), per_section=per_section,
            function_name="test_deck_narration"), sections

    def test_the_map_has_exactly_one_segment_per_slide(self, fake_tts, tmp_path):
        result, sections = self._build(tmp_path, 12)
        assert len(result["timestamp_map"]["slides"]) == len(sections) == 12

    def test_every_boundary_is_measured_not_interpolated(self, fake_tts,
                                                         tmp_path):
        """One TTS request per section is what makes each boundary a probe of
        that section's own audio."""
        self._build(tmp_path, 12)
        assert len(fake_tts) == 12

    def test_the_lecture_path_still_packs(self, fake_tts, tmp_path):
        self._build(tmp_path, 12, per_section=False)
        assert len(fake_tts) < 12

    def test_the_segments_are_contiguous_and_end_with_the_audio(self, fake_tts,
                                                                tmp_path):
        result, _ = self._build(tmp_path, 8)
        tmap = result["timestamp_map"]
        slides = tmap["slides"]
        assert slides[0]["start"] == 0.0
        for a, b in zip(slides, slides[1:]):
            assert abs(b["start"] - a["end"]) < 0.01
            assert b["end"] > b["start"]
        assert abs(slides[-1]["end"] - tmap["duration_seconds"]) < 0.01, \
            "the deck would run past the end of its own soundtrack"

    def test_the_total_duration_is_sane(self, fake_tts, tmp_path):
        """The stub speaks 400 chars/second, so the file must be roughly
        total_chars/400 long. A concatenation bug that dropped or doubled a
        segment shows up here and nowhere else."""
        result, sections = self._build(tmp_path, 8)
        spoken = sum(len(narration.prepare_for_speech(s["text"]))
                     for s in sections)
        assert result["duration_seconds"] == pytest.approx(spoken / 400.0,
                                                           rel=0.25)

    def test_the_sidecar_the_deck_reads_parses_back(self, fake_tts, tmp_path):
        result, _ = self._build(tmp_path, 10)
        raw = Path(result["sidecar_path"]).read_text(encoding="utf-8")
        parsed = parse_sidecar(raw)
        assert parsed and len(parsed["cues"]) == 10


# ── arming, and refusing to arm ──────────────────────────────────────────

@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe not on PATH")
class TestAutoAdvanceArmsOnlyOnAMatch:
    def _render(self, tmp_path, n_sections):
        import app
        sections = app.build_deck_narration_sections(_spec_slides(n_sections))
        narration.synthesize_lecture(
            "", str(tmp_path / "deck-2.mp3"), audio_id="deck-2",
            sections=sections, style="deck", media_dir=str(tmp_path),
            per_section=True, function_name="test_deck_narration")

    def test_matching_counts_arm_auto_advance(self, fake_tts, tmp_path):
        self._render(tmp_path, 9)
        got = load_narration(str(tmp_path), "deck-2", spec_slide_count=9,
                             spec_to_section={i: i for i in range(9)})
        assert got and got["synced"] is True
        assert len(got["cues"]) == 9
        assert got["sync_note"] == ""

    def test_a_mismatch_still_refuses(self, fake_tts, tmp_path):
        """The property this whole item exists to preserve. A 13-segment
        lecture over a 34-slide deck must stay unsynced."""
        self._render(tmp_path, 13)
        got = load_narration(str(tmp_path), "deck-2", spec_slide_count=34,
                             spec_to_section={i: i for i in range(34)})
        assert got and got["synced"] is False
        assert got["cues"] == []
        assert "13" in got["sync_note"] and "34" in got["sync_note"]

    def test_cues_land_on_the_section_a_spec_slide_became(self, fake_tts,
                                                          tmp_path):
        """A spec slide can expand to several deck sections under the body
        budget; the cue must point at the first one, 1-based."""
        self._render(tmp_path, 3)
        got = load_narration(str(tmp_path), "deck-2", spec_slide_count=3,
                             spec_to_section={0: 0, 1: 4, 2: 9})
        assert [c["slide"] for c in got["cues"]] == [1, 5, 10]


# ── the export refuses a map it cannot trust ─────────────────────────────

class TestTheExportFallsBackRatherThanGuessing:
    def test_a_short_map_is_discarded(self, monkeypatch, tmp_path):
        """If the renderer drops a section for any reason, the resulting map
        describes different slides than the deck shows. Using it would advance
        to the wrong slide; the export must fall back to whatever unsynced
        render exists instead."""
        import app
        monkeypatch.setattr(app, "MEDIA_DIR", str(tmp_path))
        monkeypatch.setattr(narration, "synthesize_lecture",
                            lambda *a, **k: {"timestamp_map":
                                             {"slides": [{"index": 0}]},
                                             "duration_seconds": 1.0,
                                             "cost_usd": 0.0})
        got = app._build_synced_narration("id-1", _spec_slides(5), "q", 10)
        assert got == ""

    def test_a_matching_map_is_accepted(self, monkeypatch, tmp_path):
        import app
        monkeypatch.setattr(app, "MEDIA_DIR", str(tmp_path))
        monkeypatch.setattr(narration, "synthesize_lecture",
                            lambda *a, **k: {"timestamp_map":
                                             {"slides": [{"index": i}
                                                         for i in range(5)]},
                                             "duration_seconds": 30.0,
                                             "cost_usd": 0.01})
        assert app._build_synced_narration("id-1", _spec_slides(5), "q", 10) \
            == "id-1"

    def test_a_tts_failure_does_not_fail_the_export(self, monkeypatch,
                                                    tmp_path):
        import app
        monkeypatch.setattr(app, "MEDIA_DIR", str(tmp_path))

        def _boom(*a, **k):
            raise RuntimeError("no backend")

        monkeypatch.setattr(narration, "synthesize_lecture", _boom)
        assert app._build_synced_narration("id-1", _spec_slides(5), "q", 10) == ""

    def test_no_slides_records_nothing(self, monkeypatch, tmp_path):
        import app
        monkeypatch.setattr(app, "MEDIA_DIR", str(tmp_path))
        called = []
        monkeypatch.setattr(narration, "synthesize_lecture",
                            lambda *a, **k: called.append(1))
        assert app._build_synced_narration("id-1", [], "q", 10) == ""
        assert not called
