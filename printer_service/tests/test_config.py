"""Config: validation guards, helpers, and PRINTER_USB → connection dispatch."""

import pytest

from labeljetty.config import Config, AuthToken, AuthUser, LabelProfile
from labeljetty.printer import connection as conn_mod


def make_config(**overrides) -> Config:
    base = dict(PRINTER_USB="vid:0000:pid:0000", _env_file=None)
    base.update(overrides)
    return Config(**base)


# --------------------------------------------------------------------------- #
#  Validation
# --------------------------------------------------------------------------- #
def test_printer_usb_unset_routes_to_autodetect(monkeypatch):
    # PRINTER_USB is now optional: unset means "auto-detect a connected printer".
    monkeypatch.delenv("PRINTER_USB", raising=False)
    cfg = Config(_env_file=None)
    assert cfg.PRINTER_USB is None
    monkeypatch.setattr(
        conn_mod.TSPLPrinterConnectionUSB,
        "autodetect",
        classmethod(lambda cls: "autodetected"),
    )
    assert cfg.get_printer_connection() == "autodetected"


def test_protected_requires_a_provider():
    with pytest.raises(Exception):
        make_config(AUTH_MODE="protected")


def test_protected_ok_with_token():
    cfg = make_config(AUTH_MODE="protected", AUTH_TOKENS=[AuthToken(name="ci", token="t")])
    assert cfg.auth_enabled()


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def test_homebox_configured_requires_url_key_and_enabled():
    # HOMEBOX_ENABLED is passed explicitly because the test env defaults it off.
    assert not make_config(HOMEBOX_ENABLED=True).homebox_configured()
    assert not make_config(
        HOMEBOX_ENABLED=True, HOMEBOX_URL="https://x"
    ).homebox_configured()
    assert make_config(
        HOMEBOX_ENABLED=True, HOMEBOX_URL="https://x", HOMEBOX_API_KEY="hb_y"
    ).homebox_configured()
    assert not make_config(
        HOMEBOX_ENABLED=False, HOMEBOX_URL="https://x", HOMEBOX_API_KEY="hb_y"
    ).homebox_configured()


def test_find_user():
    cfg = make_config(AUTH_USERS=[AuthUser(username="tim", password_hash="h")])
    assert cfg.find_user("tim").username == "tim"
    assert cfg.find_user("ghost") is None


def test_label_profiles_prepends_default():
    cfg = make_config(
        DEFAULT_LABEL_WIDTH_MM=57,
        DEFAULT_LABEL_HEIGHT_MM=32,
        LABEL_PROFILES=[LabelProfile(name="DHL", width_mm=100, height_mm=50)],
    )
    profiles = cfg.get_label_profiles()
    assert profiles[0].name == "Default"
    assert profiles[0].width_mm == 57
    assert [p.name for p in profiles] == ["Default", "DHL"]


# --------------------------------------------------------------------------- #
#  PRINTER_USB → connection dispatch
# --------------------------------------------------------------------------- #
@pytest.fixture
def record_lookups(monkeypatch):
    """Replace every TSPLPrinterConnectionUSB.by_* with a recorder."""
    calls = {}

    def recorder(name):
        def _fn(*args, **kwargs):
            calls["name"] = name
            calls["args"] = args
            calls["kwargs"] = kwargs
            return f"conn:{name}"
        return classmethod(lambda cls, *a, **k: _fn(*a, **k))

    for name in (
        "by_serial",
        "by_device_path",
        "by_port",
        "by_bus_and_device_id",
        "by_vendor_and_product_id",
    ):
        monkeypatch.setattr(conn_mod.TSPLPrinterConnectionUSB, name, recorder(name))
    return calls


@pytest.mark.parametrize(
    "usb_id,expected_name,expected_args",
    [
        ("serial:ABC123", "by_serial", ("ABC123",)),
        ("path:001/004", "by_device_path", ("001/004",)),
        ("port:3-1-2", "by_port", ("3-1-2",)),
        ("bus:1:addr:4", "by_bus_and_device_id", (1, 4)),
        ("vid:1234:pid:5678", "by_vendor_and_product_id", ("1234", "5678")),
        ("vid:1234", "by_vendor_and_product_id", ("1234", None)),
    ],
)
def test_get_printer_connection_dispatch(
    record_lookups, usb_id, expected_name, expected_args
):
    cfg = make_config(PRINTER_USB=usb_id)
    result = cfg.get_printer_connection()
    assert result == f"conn:{expected_name}"
    assert record_lookups["name"] == expected_name
    assert record_lookups["args"] == expected_args


def test_get_printer_connection_bad_format():
    with pytest.raises(ValueError):
        make_config(PRINTER_USB="garbage").get_printer_connection()


def test_get_printer_connection_bad_bus_format():
    with pytest.raises(ValueError):
        make_config(PRINTER_USB="bus:1:wrong:4").get_printer_connection()
