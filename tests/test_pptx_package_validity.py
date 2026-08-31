"""
A generated .pptx must be a package PowerPoint will open.

Narrated decks shipped broken and nothing caught it. python-pptx wrote the
file without complaint; the COM render used for visual verification opened it
without complaint (it repairs silently and returns a usable object); the deck
rendered to PNG correctly. The only thing that objected was PowerPoint on the
user's machine, with "PowerPoint found a problem with content" — and for the
narrated decks, an outright refusal: "The file or directory is corrupted and
unreadable" (HRESULT 0x80070570).

Root cause: `_patch_slide_xml_zip` hand-wrote `<p:audioFile>`, which is not an
element. Audio lives in the DrawingML namespace as `<a:audioFile>`. The timing
block was also malformed — `<p:audio>` nested inside the click sequence rather
than beside it, and `<p:cond evt="onPrevClick"><p:tn/></p:cond>` where the
event is `onPrev` and `<p:tn/>` needs a `val`.

The structure it emits now was read back off a file PowerPoint itself authored
over COM, rather than written from the spec by hand — three hand-authored
attempts all failed.

These tests run offline against a synthetic package: no PowerPoint, no COM, no
network, so they run in the normal suite rather than only where Office exists.
"""
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from scripts.validate_pptx import validate

MINIMAL_SLIDE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    ' xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
    '<p:cSld><p:spTree>'
    '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
    '<p:grpSpPr/>'
    '</p:spTree></p:cSld></p:sld>'
)

MINIMAL_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '</Relationships>'
)

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Default Extension="mp3" ContentType="audio/mpeg"/>'
    '<Default Extension="png" ContentType="image/png"/>'
    '</Types>'
)


def _package(tmp_path, slide_xml, slide_rels=MINIMAL_RELS, extra=None):
    """Build the smallest zip the validator can meaningfully inspect."""
    path = tmp_path / "deck.pptx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("ppt/slides/slide1.xml", slide_xml)
        z.writestr("ppt/slides/_rels/slide1.xml.rels", slide_rels)
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return str(path)


class TestValidatorAcceptsAHealthyPackage:

    def test_minimal_package_is_clean(self, tmp_path):
        assert validate(_package(tmp_path, MINIMAL_SLIDE)) == []

    def test_the_real_injected_structure_is_clean(self, tmp_path):
        """The exact XML _patch_slide_xml_zip now produces, in miniature."""
        import app
        patched = app._patch_slide_xml_zip(MINIMAL_SLIDE.encode(), 1).decode()
        rels = MINIMAL_RELS.replace(
            "</Relationships>",
            '<Relationship Id="rIdAudio1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/audio" Target="../media/narration_s1.mp3"/>'
            '<Relationship Id="rIdMedia1" Type="http://schemas.microsoft.com/office/2007/relationships/media" Target="../media/narration_s1.mp3"/>'
            '<Relationship Id="rIdAIcon1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/audio_icon.png"/>'
            "</Relationships>")
        pkg = _package(tmp_path, patched, rels, extra={
            "ppt/media/narration_s1.mp3": b"\xff\xfb\x00",
            "ppt/media/audio_icon.png": b"\x89PNG\r\n\x1a\n",
        })
        assert validate(pkg) == []


class TestTheDefectsThatShipped:
    """Each of these was in a file the user could not open."""

    def test_empty_time_node_reference_is_caught(self, tmp_path):
        bad = MINIMAL_SLIDE.replace(
            "</p:cSld>",
            "</p:cSld><p:timing><p:cond evt=\"onPrev\"><p:tn/></p:cond></p:timing>")
        problems = validate(_package(tmp_path, bad))
        assert any("<p:tn> without @val" in p for p in problems)

    def test_paragraph_build_on_a_picture_is_caught(self, tmp_path):
        bad = MINIMAL_SLIDE.replace(
            "</p:spTree>",
            '<p:pic><p:nvPicPr><p:cNvPr id="901" name="Narration 1"/>'
            '</p:nvPicPr></p:pic></p:spTree>').replace(
            "</p:cSld>",
            '</p:cSld><p:timing><p:bldLst>'
            '<p:bldP spid="901" grpId="0" build="p"/></p:bldLst></p:timing>')
        problems = validate(_package(tmp_path, bad))
        assert any("targets a picture" in p for p in problems)

    def test_dangling_relationship_is_caught(self, tmp_path):
        bad = MINIMAL_SLIDE.replace(
            "</p:spTree>",
            '<p:pic><p:blipFill><a:blip r:embed="rIdNope"/></p:blipFill></p:pic>'
            "</p:spTree>")
        problems = validate(_package(tmp_path, bad))
        assert any("undeclared relationship" in p for p in problems)

    def test_relationship_to_a_missing_part_is_caught(self, tmp_path):
        rels = MINIMAL_RELS.replace(
            "</Relationships>",
            '<Relationship Id="rIdAudio1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/audio" Target="../media/gone.mp3"/>'
            "</Relationships>")
        problems = validate(_package(tmp_path, MINIMAL_SLIDE, rels))
        assert any("not in the package" in p for p in problems)


class TestControlCharacters:
    """The other way a deck earns the repair dialog: a control character from
    a PDF-scraped abstract riding into a text run. XML 1.0 forbids these
    outright — they cannot be escaped, only removed."""

    @pytest.mark.parametrize("ch", ["\x00", "\x08", "\x0b", "\x1f"])
    def test_control_character_in_a_run_is_caught(self, tmp_path, ch):
        bad = MINIMAL_SLIDE.replace(
            "</p:spTree>",
            f"<p:sp><p:txBody><a:p><a:r><a:t>Er:YAG{ch}laser</a:t>"
            "</a:r></a:p></p:txBody></p:sp></p:spTree>")
        problems = validate(_package(tmp_path, bad))
        assert any("illegal XML char" in p for p in problems)

    def test_legal_whitespace_is_not_flagged(self, tmp_path):
        """Tab, newline and carriage return are legal and common."""
        ok = MINIMAL_SLIDE.replace(
            "</p:spTree>",
            "<p:sp><p:txBody><a:p><a:r><a:t>line\tone\r\ntwo</a:t>"
            "</a:r></a:p></p:txBody></p:sp></p:spTree>")
        assert validate(_package(tmp_path, ok)) == []


class TestInjectionUsesTheRightNamespace:
    """The fatal defect, asserted directly on the builder's output rather than
    only through the validator — `<p:audioFile>` is not an element."""

    def test_audio_file_is_in_the_drawingml_namespace(self):
        import app
        out = app._patch_slide_xml_zip(MINIMAL_SLIDE.encode(), 1).decode()
        assert "<a:audioFile" in out
        assert "<p:audioFile" not in out, (
            "p:audioFile does not exist; PowerPoint refuses the whole file")

    def test_media_extension_is_present(self):
        """Modern PowerPoint needs the p14:media extension alongside
        a:audioFile, or the shape is inert."""
        import app
        out = app._patch_slide_xml_zip(MINIMAL_SLIDE.encode(), 1).decode()
        assert "p14:media" in out and 'r:embed="rIdMedia1"' in out

    def test_audio_node_is_a_sibling_of_the_sequence(self):
        """<p:audio> belongs beside <p:seq>, not nested inside its par chain."""
        import app
        out = app._patch_slide_xml_zip(MINIMAL_SLIDE.encode(), 1).decode()
        assert "</p:seq><p:audio>" in out.replace(" ", "")
