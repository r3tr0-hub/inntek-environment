"""Headless rendering: every job type renders to a label-sized 1-bit PNG.

This is the same engine the web preview and the Homebox push endpoint use, so
it must produce correct output *without* a printer.
"""

import io
from pathlib import Path

import pytest
from PIL import Image

from labeljetty.printer.render import render_label_image, render_label_png_bytes

FIXTURES = Path(__file__).parent / "fixtures"

# Geometry from conftest (57x32mm @ 203dpi). Width is padded to a multiple of 8.
GEOM = dict(width_mm=57, height_mm=32, dpi=203)
EXPECTED_W = 456  # int(57/25.4*203)=455 → padded up to 456
EXPECTED_H = 255  # int(32/25.4*203)=255


def _open(png_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png_bytes))


@pytest.mark.parametrize(
    "job_type,params",
    [
        ("text", {"text": "Hello world"}),
        ("text", {"text": "x", "font_size": 24, "fit": "width"}),
        ("markdown", {"text": "# Title\n\nbody line"}),
        ("barcode", {"data": "12345678", "barcode_type": "128"}),
        ("barcode", {"data": "ABC", "text": "caption"}),
        ("qrcode", {"data": "https://example.com"}),
        ("qrcode", {"data": "https://example.com", "text": "Scan me"}),
    ],
)
def test_renders_label_sized_1bit(job_type, params):
    img = render_label_image(job_type, params, **GEOM)
    assert img.mode == "1"
    assert img.size == (EXPECTED_W, EXPECTED_H)
    assert img.width % 8 == 0


@pytest.mark.parametrize(
    "job_type,params",
    [
        ("text", {"text": "hi"}),
        ("qrcode", {"data": "x"}),
        ("barcode", {"data": "123"}),
    ],
)
def test_png_bytes_are_valid_png(job_type, params):
    data = render_label_png_bytes(job_type, params, **GEOM)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert _open(data).size == (EXPECTED_W, EXPECTED_H)


def test_unsupported_barcode_falls_back_to_code128():
    # An unknown TSPL barcode type must not raise — it falls back to Code 128.
    img = render_label_image("barcode", {"data": "X1", "barcode_type": "NOPE"}, **GEOM)
    assert img.size == (EXPECTED_W, EXPECTED_H)


def test_unknown_job_type_raises():
    with pytest.raises(ValueError):
        render_label_image("hologram", {}, **GEOM)


def test_png_preview_requires_input_file():
    with pytest.raises(ValueError):
        render_label_image("png", {}, **GEOM)


def test_renders_png_from_fixture():
    img = render_label_image(
        "png", {"fit": "fit"}, input_file_path=FIXTURES / "label_test.png", **GEOM
    )
    assert img.size == (EXPECTED_W, EXPECTED_H)


def test_renders_pdf_page(tmp_path):
    # Build a one-page PDF on the fly (PIL can save images as PDF).
    pdf_path = tmp_path / "page.pdf"
    Image.new("RGB", (400, 200), "white").save(pdf_path, "PDF")
    img = render_label_image(
        "pdf", {"page": 0, "fit": "fit"}, input_file_path=pdf_path, **GEOM
    )
    assert img.size == (EXPECTED_W, EXPECTED_H)
