"""TSPLPrinterStatusMessage: bit-flag decoding of the real-time status byte."""

import pytest

from labeljetty.printer.tspl import TSPLPrinterStatusMessage as Msg


def test_ready_byte():
    m = Msg.from_raw_response(0x00)
    assert m.ready
    assert not m.error
    assert m.raw_status_byte == 0


@pytest.mark.parametrize(
    "byte,attr",
    [
        (0x01, "head_opened"),
        (0x02, "paper_jam"),
        (0x04, "paper_empty"),
        (0x08, "ribbon_empty"),
        (0x10, "paused"),
        (0x20, "printing"),
        (0x80, "other_error"),
    ],
)
def test_individual_flags(byte, attr):
    m = Msg.from_raw_response(byte)
    assert getattr(m, attr) is True
    assert not m.ready  # any non-zero byte is not "ready"


def test_combined_flags():
    # 0x05 = out of paper (0x04) + head opened (0x01)
    m = Msg.from_raw_response(0x05)
    assert m.head_opened and m.paper_empty
    assert m.error


def test_paused_is_not_an_error():
    # Pause / printing are states, not faults.
    assert not Msg.from_raw_response(0x10).error
    assert not Msg.from_raw_response(0x20).error


def test_accepts_bytes_input():
    m = Msg.from_raw_response(b"\x04")
    assert m.paper_empty
    assert m.raw_status_byte == 4
