"""
X-ray vision path gating (WORKLIST 4.4).

The vision path (/api/analyze-xray) sends a patient radiograph to a
third-party vision API (Gemini / GPT-4o). Radiographs are PHI, so:

  1. The route is OFF by default — ENABLE_XRAY unset or falsy -> 403.
     (Decision recorded in WORKLIST §5; enabling requires a BAA.)
  2. When on, the image is re-encoded to strip EXIF/GPS/PNG-text metadata
     (radiograph exports routinely embed patient name/DOB there). Stripping
     failure rejects the upload — it never forwards raw bytes (HANDOVER.md
     bug class (d): a check must not fail open).
  3. Only a sanitized tooth designation accompanies the image — free-text
     case narrative in the tooth_hint field is dropped, so case text is
     never sent alongside the image.
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


@pytest.fixture
def client():
    import app as app_mod
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


def _jpeg_with_exif() -> bytes:
    """A real JPEG carrying EXIF fields of the kind DICOM->JPEG exporters
    write (device make + description that could hold patient identifiers)."""
    from PIL import Image
    img = Image.new("RGB", (12, 12), "white")
    exif = img.getexif()
    exif[0x010F] = "TestPanoramicUnit"          # Make
    exif[0x010E] = "PATIENT: DOE, JOHN 1/2/34"  # ImageDescription
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _png_with_text() -> bytes:
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    img = Image.new("RGB", (12, 12), "white")
    info = PngInfo()
    info.add_text("PatientName", "John Doe")
    buf = io.BytesIO()
    img.save(buf, format="PNG", pnginfo=info)
    return buf.getvalue()


class TestGateOffByDefault:

    def test_unset_env_returns_403(self, client, monkeypatch):
        monkeypatch.delenv("ENABLE_XRAY", raising=False)
        resp = client.post("/api/analyze-xray", data={})
        assert resp.status_code == 403
        assert "BAA" in (resp.get_json() or {}).get("error", "")

    @pytest.mark.parametrize("value", ["false", "0", "no", "off", ""])
    def test_falsy_values_return_403(self, client, monkeypatch, value):
        monkeypatch.setenv("ENABLE_XRAY", value)
        assert client.post("/api/analyze-xray", data={}).status_code == 403

    @pytest.mark.parametrize("value", ["true", "1", "yes", "on", "TRUE"])
    def test_truthy_values_pass_the_gate(self, client, monkeypatch, value):
        """Past the gate, a request with no image hits the handler's own
        validation: 400 'No image provided', not 403."""
        monkeypatch.setenv("ENABLE_XRAY", value)
        resp = client.post("/api/analyze-xray", data={})
        assert resp.status_code == 400
        assert "image" in (resp.get_json() or {}).get("error", "").lower()


class TestMetadataStripping:

    def test_jpeg_exif_is_removed(self):
        from app import _strip_image_metadata
        from PIL import Image
        stripped = _strip_image_metadata(_jpeg_with_exif(), "jpg")
        exif = Image.open(io.BytesIO(stripped)).getexif()
        assert len(exif) == 0, f"EXIF survived stripping: {dict(exif)}"

    def test_png_text_chunks_are_removed(self):
        from app import _strip_image_metadata
        from PIL import Image
        stripped = _strip_image_metadata(_png_with_text(), "png")
        reopened = Image.open(io.BytesIO(stripped))
        assert "PatientName" not in (getattr(reopened, "text", {}) or {})

    def test_stripped_image_still_decodes(self):
        from app import _strip_image_metadata
        from PIL import Image
        stripped = _strip_image_metadata(_jpeg_with_exif(), "jpg")
        assert Image.open(io.BytesIO(stripped)).size == (12, 12)

    def test_undecodable_upload_is_rejected_not_forwarded(self, client, monkeypatch):
        """Fail closed: if Pillow cannot decode the bytes, the route must
        400 without ever calling the vision provider."""
        import app as app_mod
        monkeypatch.setenv("ENABLE_XRAY", "true")
        called = []
        monkeypatch.setattr(app_mod, "analyze_radiograph",
                            lambda *a, **k: called.append(1) or {})
        resp = client.post("/api/analyze-xray", data={
            "image": (io.BytesIO(b"not an image at all"), "x.jpg"),
        }, content_type="multipart/form-data")
        assert resp.status_code == 400
        assert called == [], "vision provider was called with unstripped bytes"


class TestToothHintSanitizer:

    @pytest.mark.parametrize("raw,expected", [
        ("14", "14"),
        ("#30", "30"),
        ("4.6", "4.6"),
        ("B", "B"),
        ("", ""),
        ("upper left first molar", ""),
        ("Pt John Doe, DOB 1/2/1934, necrotic #30 with sinus tract", ""),
        ("30; also patient is on bisphosphonates", ""),
    ])
    def test_only_bare_tooth_designations_survive(self, raw, expected):
        from app import _sanitize_tooth_hint
        assert _sanitize_tooth_hint(raw) == expected


class TestNoCaseTextReachesProvider:

    def test_vision_call_gets_stripped_bytes_and_no_free_text(self, client, monkeypatch):
        """End to end through the route: EXIF-laden JPEG + narrative tooth
        hint in -> the vision call receives EXIF-free bytes and an empty
        hint."""
        import app as app_mod
        from PIL import Image
        monkeypatch.setenv("ENABLE_XRAY", "true")

        captured = {}

        def fake_analyze(image_bytes, media_type, tooth_hint="", provider="auto"):
            captured["bytes"] = image_bytes
            captured["tooth_hint"] = tooth_hint
            return {"_meta": {"provider": "fake", "fallback_reason": None}}

        monkeypatch.setattr(app_mod, "analyze_radiograph", fake_analyze)
        monkeypatch.setattr(app_mod, "_analysis_to_prefill", lambda raw: {})

        resp = client.post("/api/analyze-xray", data={
            "image": (io.BytesIO(_jpeg_with_exif()), "xray.jpg"),
            "tooth_hint": "necrotic #30, pt Jane Doe, severe pain since Tuesday",
        }, content_type="multipart/form-data")

        assert resp.status_code == 200
        assert captured["tooth_hint"] == ""
        exif = Image.open(io.BytesIO(captured["bytes"])).getexif()
        assert len(exif) == 0, "vision provider received EXIF metadata"
