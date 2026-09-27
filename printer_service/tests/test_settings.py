"""Config-via-UI: the DB overlay, precedence, and the /ui/settings routes.

The overlay (admin edits) overrides env, which overrides defaults. The settings
page is gated behind SETTINGS_UI_ENABLED and renders/saves a generic form built
from the fields flagged with ``_ui(...)`` metadata.
"""

import json

import pytest

from labeljetty.config import (
    build_config,
    get_config,
    reload_config,
    ui_field_meta,
)
from labeljetty.core.db import (
    get_setting_overrides,
    set_setting_overrides,
    clear_setting_overrides,
)


@pytest.fixture
def settings_enabled(monkeypatch):
    """Turn the settings UI on for the singleton, restoring it afterwards.

    Teardown clears any overrides and reloads so the process-wide singleton can't
    leak edited state (e.g. AUTH_MODE=protected) into later test modules."""
    monkeypatch.setenv("SETTINGS_UI_ENABLED", "true")
    reload_config()
    yield
    clear_setting_overrides()
    monkeypatch.delenv("SETTINGS_UI_ENABLED", raising=False)
    reload_config()


# --------------------------------------------------------------------------- #
#  Overlay precedence
# --------------------------------------------------------------------------- #
def test_overlay_overrides_env():
    set_setting_overrides({"DEFAULT_DPI": json.dumps(300)})
    cfg = build_config()
    assert cfg.DEFAULT_DPI == 300  # overlay beats the env default (203)


def test_no_overlay_falls_back_to_env():
    clear_setting_overrides()
    assert build_config().DEFAULT_DPI == 203  # from the test env


def test_locked_key_is_not_taken_from_overlay(monkeypatch):
    monkeypatch.setenv("SETTINGS_LOCKED_KEYS", '["DEFAULT_DPI"]')
    set_setting_overrides({"DEFAULT_DPI": json.dumps(300)})
    assert build_config().DEFAULT_DPI == 203  # pinned to env, overlay ignored


def test_overlay_runs_validators():
    # A complex field is coerced + validated through the model, not stored blindly.
    set_setting_overrides(
        {"LABEL_PROFILES": json.dumps([{"name": "DHL", "width_mm": 100, "height_mm": 50}])}
    )
    cfg = build_config()
    assert [p.name for p in cfg.LABEL_PROFILES] == ["DHL"]


# --------------------------------------------------------------------------- #
#  Field metadata
# --------------------------------------------------------------------------- #
def test_ui_field_meta_includes_operational_excludes_secrets():
    meta = ui_field_meta()
    assert "DEFAULT_DPI" in meta and "LABEL_PROFILES" in meta
    # Secrets / infra are intentionally not editable from the web UI.
    assert "HOMEBOX_API_KEY" not in meta
    assert "SQLITE_PATH" not in meta
    assert "SESSION_SECRET" not in meta


# --------------------------------------------------------------------------- #
#  Routes
# --------------------------------------------------------------------------- #
def test_settings_404_when_disabled(client):
    # Default SETTINGS_UI_ENABLED is false in the test env.
    assert client.get("/ui/settings").status_code == 404


def test_settings_page_renders_when_enabled(client, settings_enabled):
    resp = client.get("/ui/settings")
    assert resp.status_code == 200
    assert "Label defaults" in resp.text
    assert "System info" in resp.text


def test_settings_save_persists_and_reloads(client, settings_enabled):
    resp = client.post("/ui/settings", data={"DEFAULT_DPI": "300", "LOG_LEVEL": "INFO"})
    assert resp.status_code == 200
    assert "Settings saved" in resp.text
    assert get_config().DEFAULT_DPI == 300
    assert "DEFAULT_DPI" in get_setting_overrides()


def test_label_profiles_row_editor_saves(client, settings_enabled):
    resp = client.post(
        "/ui/settings",
        data={"lp_name": "DHL", "lp_width": "100", "lp_height": "50", "lp_dpi": ""},
    )
    assert resp.status_code == 200
    profiles = get_config().LABEL_PROFILES
    assert [(p.name, p.width_mm, p.height_mm, p.dpi) for p in profiles] == [
        ("DHL", 100, 50, None)
    ]


def test_label_profiles_blank_rows_ignored(client, settings_enabled):
    # An empty name row is dropped rather than erroring.
    resp = client.post(
        "/ui/settings",
        data={
            "lp_name": ["A", ""],
            "lp_width": ["57", ""],
            "lp_height": ["32", ""],
            "lp_dpi": ["", ""],
        },
    )
    assert resp.status_code == 200
    assert [p.name for p in get_config().LABEL_PROFILES] == ["A"]


def test_label_profiles_missing_dimension_rejected(client, settings_enabled):
    resp = client.post(
        "/ui/settings",
        data={"lp_name": "x", "lp_width": "", "lp_height": "32", "lp_dpi": ""},
    )
    assert resp.status_code == 400
    assert "width and height are required" in resp.text


def test_label_profiles_non_numeric_rejected(client, settings_enabled):
    # Non-numeric width is caught by the model validator.
    resp = client.post(
        "/ui/settings",
        data={"lp_name": "x", "lp_width": "abc", "lp_height": "32", "lp_dpi": ""},
    )
    assert resp.status_code == 400


def test_printer_select_picks_candidate(client, settings_enabled):
    resp = client.post(
        "/ui/settings", data={"PRINTER_USB_choice": "vid:1234:pid:5678"}
    )
    assert resp.status_code == 200
    assert get_config().PRINTER_USB == "vid:1234:pid:5678"


def test_printer_select_custom_selector(client, settings_enabled):
    resp = client.post(
        "/ui/settings",
        data={"PRINTER_USB_choice": "__custom__", "PRINTER_USB_custom": "serial:ABC123"},
    )
    assert resp.status_code == 200
    assert get_config().PRINTER_USB == "serial:ABC123"


def test_printer_select_auto_detect_clears(client, settings_enabled):
    # Empty choice => auto-detect (PRINTER_USB unset/None).
    resp = client.post("/ui/settings", data={"PRINTER_USB_choice": ""})
    assert resp.status_code == 200
    assert get_config().PRINTER_USB is None


def test_settings_reset_clears_overrides(client, settings_enabled):
    set_setting_overrides({"DEFAULT_DPI": json.dumps(300)})
    reload_config()
    assert get_config().DEFAULT_DPI == 300
    resp = client.post("/ui/settings/reset")
    assert resp.status_code == 200
    assert get_setting_overrides() == {}
    assert get_config().DEFAULT_DPI == 203


# --------------------------------------------------------------------------- #
#  Login users via the settings UI
# --------------------------------------------------------------------------- #
def test_add_login_user_and_protect(client, settings_enabled):
    from labeljetty.web.password import verify_password

    resp = client.post(
        "/ui/settings",
        data={"AUTH_MODE": "protected", "au_username": "tim", "au_password": "s3cret"},
    )
    assert resp.status_code == 200
    cfg = get_config()
    assert cfg.auth_enabled()
    user = cfg.find_user("tim")
    assert user is not None
    assert user.password_hash.startswith("pbkdf2_sha256$")  # never plaintext
    assert verify_password("s3cret", user.password_hash)


def test_new_user_without_password_rejected(client, settings_enabled):
    resp = client.post("/ui/settings", data={"au_username": "bob", "au_password": ""})
    assert resp.status_code == 400
    assert "set a password" in resp.text


def test_blank_password_keeps_existing_hash(client, settings_enabled):
    client.post("/ui/settings", data={"au_username": "tim", "au_password": "pw1"})
    h1 = get_config().find_user("tim").password_hash
    client.post("/ui/settings", data={"au_username": "tim", "au_password": ""})
    assert get_config().find_user("tim").password_hash == h1


def test_protected_without_user_rejected(client, settings_enabled):
    # Lock-out guard: protected with no users and no tokens is refused.
    resp = client.post("/ui/settings", data={"AUTH_MODE": "protected"})
    assert resp.status_code == 400
    assert get_config().auth_enabled() is False


def test_remove_user(client, settings_enabled):
    client.post("/ui/settings", data={"au_username": "tim", "au_password": "pw"})
    assert get_config().find_user("tim") is not None
    # Omitting the row removes the user.
    client.post("/ui/settings", data={"DEFAULT_DPI": "203"})
    assert get_config().find_user("tim") is None


def test_password_hash_never_rendered(client, settings_enabled):
    client.post("/ui/settings", data={"au_username": "tim", "au_password": "pw"})
    html = client.get("/ui/settings").text
    assert "tim" in html  # username shown
    assert "pbkdf2_sha256$" not in html  # hash never sent to the browser


def test_checkbox_unchecked_saves_false(client, settings_enabled):
    # HOMEBOX_ENABLED is a checkbox; omitting it from the form means "off".
    resp = client.post("/ui/settings", data={"DEFAULT_DPI": "203"})
    assert resp.status_code == 200
    assert get_config().HOMEBOX_ENABLED is False
