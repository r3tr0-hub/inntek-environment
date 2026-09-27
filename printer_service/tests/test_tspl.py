"""TSPLPrinter command layer, driven through a fake connection (no USB).

We assert on the TSPL byte stream the printer *would* send. Real printing is the
only thing not covered here — that lives in the manual ``testbench`` CLI.
"""

import pytest
from PIL import Image

from labeljetty.printer.tspl import TSPLPrinter
from tests.conftest import FakeConnection


def make_printer(status_byte: int = 0) -> tuple[TSPLPrinter, FakeConnection]:
    con = FakeConnection(status_byte=status_byte)
    printer = TSPLPrinter(
        connection=con, label_width_mm=57, label_height_mm=32, dpi=203
    )
    return printer, con


def _joined(con: FakeConnection) -> str:
    """All sent commands as one text blob (bytes decoded latin-1)."""
    parts = []
    for c in con.sent:
        parts.append(c if isinstance(c, str) else c.decode("latin-1"))
    return "".join(parts)


# --------------------------------------------------------------------------- #
#  Basic commands
# --------------------------------------------------------------------------- #
def test_basic_commands():
    printer, con = make_printer()
    printer.cls()
    printer.formfeed()
    printer.print_label(copies=3)
    assert "CLS\n" in con.sent
    assert "FORMFEED\n" in con.sent
    assert "PRINT 3\n" in con.sent


def test_set_size_uses_mm():
    printer, con = make_printer()
    printer._set_size()
    assert "SIZE 57 mm,32 mm\n" in con.sent


# --------------------------------------------------------------------------- #
#  Image pipeline emits SIZE → CLS → BITMAP → PRINT
# --------------------------------------------------------------------------- #
def test_text_print_emits_full_job():
    printer, con = make_printer()
    printer.print_text("Hi", copies=2)
    blob = _joined(con)
    assert "SIZE 57 mm,32 mm" in blob
    assert "CLS" in blob
    assert "BITMAP " in blob
    assert "PRINT 2" in blob


def test_qrcode_print_uses_bitmap_pipeline():
    printer, con = make_printer()
    printer.print_qrcode("https://example.com")
    assert "BITMAP " in _joined(con)


def test_barcode_uses_native_barcode_command():
    printer, con = make_printer()
    printer.print_barcode("12345678", barcode_type="128")
    blob = _joined(con)
    assert 'BARCODE ' in blob
    assert '"128"' in blob
    assert '"12345678"' in blob


def test_barcode_with_text_emits_text_and_barcode():
    printer, con = make_printer()
    printer.print_barcode_with_text("999", text="LABEL")
    blob = _joined(con)
    assert "TEXT " in blob
    assert "BARCODE " in blob


# --------------------------------------------------------------------------- #
#  Status handling
# --------------------------------------------------------------------------- #
def test_get_status_parses_connection_byte():
    printer, _ = make_printer(status_byte=0x04)  # paper empty
    status = printer.get_status()
    assert status.paper_empty
    assert status.error


def test_dry_run_status_is_ready():
    printer = TSPLPrinter(connection=None, dry_run_mode=True)
    assert printer.get_status().ready
    assert printer.is_ready()


def test_is_ready_true_when_status_unavailable(monkeypatch):
    printer, _ = make_printer()
    # A write-only clone never answers → get_status None → assume ready.
    monkeypatch.setattr(printer, "get_status", lambda: None)
    assert printer.is_ready() is True


def test_get_error_message():
    printer, _ = make_printer(status_byte=0x01)  # head open
    assert "head" in printer.get_error_message().lower()
    ready, _ = make_printer(status_byte=0x00)
    assert ready.get_error_message() is None


def test_wait_until_ready_returns_true_when_ready():
    printer, _ = make_printer(status_byte=0x00)
    assert printer.wait_until_ready(timeout=1) is True


# --------------------------------------------------------------------------- #
#  1-bit preparation / bitmap encoding
# --------------------------------------------------------------------------- #
def test_prepare_1bit_pads_width_to_multiple_of_8():
    printer, _ = make_printer()
    img = Image.new("L", (455, 100), 255)
    out = printer._prepare_1bit(img)
    assert out.mode == "1"
    assert out.width % 8 == 0
    assert out.width == 456


def test_bitmap_requires_1bit():
    printer, _ = make_printer()
    with pytest.raises(ValueError):
        printer._bitmap_tspl(Image.new("L", (8, 8), 255))


def test_build_methods_return_label_sized_images():
    printer, _ = make_printer()
    for img in (
        printer.build_text_image("hi"),
        printer.build_qrcode_image("x"),
        printer.build_barcode_image("123"),
    ):
        assert img.size == (printer.width_px, printer.height_px)


def test_fit_image_margin_reserves_white_border():
    """A solid image fitted with a margin leaves a blank border of that width."""
    printer, _ = make_printer()  # 57x32mm @ 203dpi
    black = Image.new("L", (printer.width_px, printer.height_px), 0)

    out = printer._fit_image(black, fit="fill", margin_mm=2.0)
    assert out.size == (printer.width_px, printer.height_px)

    margin_px = round((2.0 / 25.4) * printer.dpi)
    cx, cy = printer.width_px // 2, printer.height_px // 2
    # Corners (within the margin band) stay white; the centre is inked.
    assert out.getpixel((1, 1)) == 255
    assert out.getpixel((margin_px - 1, cy)) == 255
    assert out.getpixel((cx, margin_px - 1)) == 255
    assert out.getpixel((cx, cy)) == 0


def test_fit_image_zero_margin_fills_to_edge():
    printer, _ = make_printer()
    black = Image.new("L", (printer.width_px, printer.height_px), 0)
    out = printer._fit_image(black, fit="fill", margin_mm=0.0)
    assert out.getpixel((0, 0)) == 0
    assert out.getpixel((printer.width_px - 1, printer.height_px - 1)) == 0


# --------------------------------------------------------------------------- #
#  Content rotation (same label format, content turned in 90° steps)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
def test_rotation_keeps_label_size_and_restores_geometry(rotate):
    """Every rotation returns a real-label-sized image and leaves the printer's
    own geometry untouched (the 90/270 transpose is only temporary)."""
    printer, _ = make_printer()  # landscape 57x32mm
    before = (printer.width_px, printer.height_px)
    img = printer.build_text_image("hello world", rotate=rotate)
    assert img.size == (printer.width_px, printer.height_px)
    assert (printer.width_px, printer.height_px) == before


def test_rotation_snaps_unknown_angle_to_no_op():
    printer, _ = make_printer()
    a = printer.build_text_image("x", rotate=0)
    b = printer.build_text_image("x", rotate=45)  # not a 90° step → treated as 0
    assert list(a.getdata()) == list(b.getdata())


def test_rotation_90_changes_the_bitmap():
    """A quarter turn actually rotates the content (not a no-op)."""
    printer, _ = make_printer()
    a = printer.build_text_image("Label", rotate=0)
    b = printer.build_text_image("Label", rotate=90)
    assert list(a.getdata()) != list(b.getdata())


def test_rotation_180_is_a_flip_of_the_unrotated_bitmap():
    printer, _ = make_printer()
    base = printer.build_text_image("Label", rotate=0)
    turned = printer.build_text_image("Label", rotate=180)
    assert turned.size == base.size
    assert list(turned.rotate(180).getdata()) == list(base.getdata())


def test_rotation_90_and_270_auto_fit_differs_from_unrotated():
    """Smart auto-fit: sizing targets the rotated aspect ratio, so a quarter turn
    on a strongly non-square label yields a different fit than no rotation."""
    printer, _ = make_printer()
    black0 = printer.build_text_image("AB", rotate=0).convert("L").histogram()[0]
    black90 = printer.build_text_image("AB", rotate=90).convert("L").histogram()[0]
    assert black0 != black90
