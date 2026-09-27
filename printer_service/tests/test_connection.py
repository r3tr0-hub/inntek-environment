"""USB connection layer — device lookup + wire encoding, all without real USB.

``usb.core.find`` is patched to return fake devices, so no hardware is touched.
"""

import types

import pytest
import usb.core
import usb.util

from labeljetty.printer import connection
from labeljetty.printer.connection import TSPLPrinterConnectionUSB as Conn


class FakeDev:
    def __init__(self, bus=1, address=4, port_numbers=(3, 1, 2),
                 idVendor=0x2d37, idProduct=0x62de, serial="ABC123"):
        self.bus = bus
        self.address = address
        self.port_numbers = list(port_numbers)
        self.idVendor = idVendor
        self.idProduct = idProduct
        self.iSerialNumber = 3
        self._serial = serial


@pytest.fixture
def fake_usb(monkeypatch):
    """Patch usb.core.find + usb.util.get_string with a single fake device."""
    dev = FakeDev()

    def fake_find(find_all=False, idVendor=None, idProduct=None, backend=None):
        matches = [dev]
        if idVendor is not None:
            matches = [d for d in matches if d.idVendor == idVendor]
        if idProduct is not None:
            matches = [d for d in matches if d.idProduct == idProduct]
        return iter(matches) if find_all else (matches[0] if matches else None)

    monkeypatch.setattr(usb.core, "find", fake_find)
    # Don't spin up a real libusb context in unit tests; the fake find ignores it.
    monkeypatch.setattr(connection, "_fresh_backend", lambda: None)
    monkeypatch.setattr(usb.util, "get_string", lambda d, idx: d._serial)
    return dev


# --------------------------------------------------------------------------- #
#  Wire encoding
# --------------------------------------------------------------------------- #
def test_to_wire_appends_newline_for_normal_commands():
    assert Conn._to_wire("SIZE 50 mm", raw=False) == b"SIZE 50 mm\n"


def test_to_wire_strips_then_terminates():
    assert Conn._to_wire("  CLS\n", raw=False) == b"CLS\n"


def test_to_wire_raw_passes_bytes_untouched():
    # Real-time commands like <ESC>!? must NOT get a trailing newline.
    assert Conn._to_wire(b"\x1b!?", raw=True) == b"\x1b!?"


def test_to_wire_raw_encodes_str():
    assert Conn._to_wire("AB", raw=True) == b"AB"


# --------------------------------------------------------------------------- #
#  Lookups
# --------------------------------------------------------------------------- #
def test_by_vendor_and_product_id(fake_usb):
    c = Conn.by_vendor_and_product_id("2d37", "62de")
    assert c.dev is fake_usb


def test_by_vendor_id_only(fake_usb):
    assert Conn.by_vendor_and_product_id("2d37").dev is fake_usb


def test_by_vendor_no_match_raises(fake_usb):
    with pytest.raises(ValueError):
        Conn.by_vendor_and_product_id("dead", "beef")


def test_by_vendor_requires_an_argument():
    with pytest.raises(ValueError):
        Conn.by_vendor_and_product_id(None, None)


def test_by_bus_and_device_id(fake_usb):
    assert Conn.by_bus_and_device_id(1, 4).dev is fake_usb


def test_by_bus_no_match_raises(fake_usb):
    with pytest.raises(ValueError):
        Conn.by_bus_and_device_id(9, 9)


def test_by_serial(fake_usb):
    assert Conn.by_serial("ABC123").dev is fake_usb


def test_by_serial_empty_raises():
    with pytest.raises(ValueError):
        Conn.by_serial("")


def test_by_port_string(fake_usb):
    assert Conn.by_port("3-1-2").dev is fake_usb


def test_by_device_path_full(fake_usb):
    assert Conn.by_device_path("/dev/bus/usb/001/004").dev is fake_usb


def test_by_device_path_short(fake_usb):
    assert Conn.by_device_path("001/004").dev is fake_usb


def test_by_device_path_bad_format():
    with pytest.raises(ValueError):
        Conn.by_device_path("not-a-path")


def test_by_device_path_non_numeric():
    with pytest.raises(ValueError):
        Conn.by_device_path("aa/bb")


# --------------------------------------------------------------------------- #
#  Auto-discovery
# --------------------------------------------------------------------------- #
class FakeIntf:
    def __init__(self, interface_class):
        self.bInterfaceClass = interface_class


class FakeCfg:
    def __init__(self, interfaces):
        self._interfaces = interfaces

    def __iter__(self):
        return iter(self._interfaces)


class FakeDiscDev:
    """A fake device iterable over configs/interfaces (for printer-class checks)."""

    def __init__(self, idVendor, idProduct, interface_class=0xFF):
        self.idVendor = idVendor
        self.idProduct = idProduct
        self.iManufacturer = 1
        self.iProduct = 2
        self._cfgs = [FakeCfg([FakeIntf(interface_class)])]

    def __iter__(self):
        return iter(self._cfgs)


def _patch_find(monkeypatch, devices):
    """Make usb.core.find return ``devices`` (and stub string reads)."""

    def fake_find(find_all=False, idVendor=None, idProduct=None, backend=None):
        matches = list(devices)
        if idVendor is not None:
            matches = [d for d in matches if d.idVendor == idVendor]
        if idProduct is not None:
            matches = [d for d in matches if d.idProduct == idProduct]
        return iter(matches) if find_all else (matches[0] if matches else None)

    monkeypatch.setattr(usb.core, "find", fake_find)
    # Don't spin up a real libusb context in unit tests; the fake find ignores it.
    monkeypatch.setattr(connection, "_fresh_backend", lambda: None)
    monkeypatch.setattr(usb.util, "get_string", lambda d, idx: "FakeMfg")


def test_selector_for_formats_vid_pid():
    assert Conn.selector_for(FakeDiscDev(0x2d37, 0x62de)) == "vid:2d37:pid:62de"


def test_discover_matches_known_vendor(monkeypatch):
    # 0x2d37 is in the allowlist; interface class is irrelevant here.
    dev = FakeDiscDev(0x2d37, 0x62de, interface_class=0xFF)
    _patch_find(monkeypatch, [dev])
    assert Conn.discover() == [dev]


def test_discover_matches_printer_class(monkeypatch):
    # Unknown vendor, but advertises the USB printer class (7).
    dev = FakeDiscDev(0x1234, 0x5678, interface_class=7)
    _patch_find(monkeypatch, [dev])
    assert Conn.discover() == [dev]


def test_discover_ignores_non_printer(monkeypatch):
    # Unknown vendor and a non-printer interface class -> not a candidate.
    dev = FakeDiscDev(0x1234, 0x5678, interface_class=0x08)  # mass storage
    _patch_find(monkeypatch, [dev])
    assert Conn.discover() == []


def test_discover_filters_mixed_bus(monkeypatch):
    printer = FakeDiscDev(0x2d37, 0x62de)
    other = FakeDiscDev(0x1234, 0x5678, interface_class=0x03)  # HID
    _patch_find(monkeypatch, [other, printer])
    assert Conn.discover() == [printer]


def test_autodetect_single(monkeypatch):
    dev = FakeDiscDev(0x2d37, 0x62de)
    _patch_find(monkeypatch, [dev])
    assert Conn.autodetect().dev is dev


def test_autodetect_none_raises(monkeypatch):
    _patch_find(monkeypatch, [])
    with pytest.raises(ValueError, match="No TSPL printer auto-detected"):
        Conn.autodetect()


def test_info_reports_usb_facts(monkeypatch):
    dev = FakeDiscDev(0x2d37, 0x62de)
    _patch_find(monkeypatch, [dev])
    # bus/address/port_numbers come from the richer fake used by the lookup tests.
    dev.bus = 1
    dev.address = 4
    dev.port_numbers = [3, 1, 2]
    dev.iSerialNumber = 3
    info = Conn(dev).info()
    assert info["selector"] == "vid:2d37:pid:62de"
    assert info["vendor_id"] == "2d37"
    assert info["product_id"] == "62de"
    assert info["port_path"] == "3-1-2"
    assert info["device_path"] == "/dev/bus/usb/001/004"
    assert info["serial"] == "FakeMfg"  # stubbed get_string
    assert info["known_vendor"] == "Poskey / Vretti-class (e.g. 420B)"


def test_info_never_raises_on_bad_descriptors(monkeypatch):
    dev = FakeDiscDev(0x1234, 0x5678, interface_class=7)
    # get_string blows up; port_numbers missing → info degrades to None, no raise.
    monkeypatch.setattr(usb.util, "get_string", lambda d, idx: (_ for _ in ()).throw(ValueError()))
    info = Conn(dev).info()
    assert info["serial"] is None
    assert info["manufacturer"] is None
    assert info["selector"] == "vid:1234:pid:5678"
    assert info["known_vendor"] is None


def test_autodetect_multiple_raises_with_selectors(monkeypatch):
    devs = [FakeDiscDev(0x2d37, 0x62de), FakeDiscDev(0x1234, 0x5678, interface_class=7)]
    _patch_find(monkeypatch, devs)
    with pytest.raises(ValueError, match="Multiple TSPL printers") as exc:
        Conn.autodetect()
    # Each candidate is offered as a copy-paste PRINTER_USB selector.
    assert "PRINTER_USB=vid:2d37:pid:62de" in str(exc.value)
    assert "PRINTER_USB=vid:1234:pid:5678" in str(exc.value)
