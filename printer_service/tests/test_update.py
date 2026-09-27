"""Update-available check: version comparison, caching, and the endpoints.

Never touches the network — ``labeljetty.update._fetch`` (the only GitHub caller)
is monkeypatched, and the version-compare helpers are pure.
"""

import pytest

from labeljetty import update as upd
from labeljetty.update import UpdateInfo, _is_newer


@pytest.fixture(autouse=True)
def _clear_update_cache():
    """Each test starts with an empty update cache."""
    upd._reset_cache()
    yield
    upd._reset_cache()


# --------------------------------------------------------------------------- #
#  Version comparison
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "latest,current,expected",
    [
        ("0.4.0", "0.3.1", True),
        ("v0.4.0", "0.3.1", True),          # leading 'v' tolerated
        ("0.3.2", "0.3.1", True),
        ("1.0.0", "0.9.9", True),
        ("0.3.1", "0.3.1", False),          # same release
        ("0.3.0", "0.3.1", False),          # older upstream
        ("0.4", "0.3.1", True),             # short tag still compares
        ("0.4.0", "0.3.1.dev4+g123", False),  # dev build never nags
        ("0.4.0", "0.0.0+unknown", False),    # source-tree fallback never nags
    ],
)
def test_is_newer(latest, current, expected):
    assert _is_newer(latest, current) is expected


# --------------------------------------------------------------------------- #
#  check_for_update: caching + the disable flag
# --------------------------------------------------------------------------- #
def _patch(monkeypatch, *, version="0.3.1", enabled=True, fetch=None, calls=None):
    # get_version + get_config are imported lazily inside check_for_update, so
    # patch them at their source modules.
    import labeljetty.version as ver
    monkeypatch.setattr(ver, "get_version", lambda: version)

    from labeljetty.config import get_config
    conf = get_config()
    monkeypatch.setattr(conf, "UPDATE_CHECK_ENABLED", enabled)
    monkeypatch.setattr(conf, "UPDATE_CHECK_REPO", "motey/LabelJetty")

    def default_fetch(repo, current):
        if calls is not None:
            calls.append(repo)
        return UpdateInfo(current, "0.4.0", True, "https://x/releases/0.4.0", checked=True)

    monkeypatch.setattr(upd, "_fetch", fetch or default_fetch)


def test_check_for_update_flags_newer(monkeypatch):
    _patch(monkeypatch, version="0.3.1")
    info = upd.check_for_update()
    assert info.update_available is True
    assert info.latest == "0.4.0"
    assert info.checked is True


def test_check_for_update_disabled(monkeypatch):
    calls = []
    _patch(monkeypatch, enabled=False, calls=calls)
    info = upd.check_for_update()
    assert info.update_available is False
    assert info.checked is False
    assert calls == []  # disabled → no outbound call at all


def test_check_for_update_caches(monkeypatch):
    calls = []
    _patch(monkeypatch, calls=calls)
    upd.check_for_update()
    upd.check_for_update()
    assert calls == ["motey/LabelJetty"]  # second call served from cache


def test_check_for_update_force_bypasses_cache(monkeypatch):
    calls = []
    _patch(monkeypatch, calls=calls)
    upd.check_for_update()
    upd.check_for_update(force=True)
    assert len(calls) == 2


# --------------------------------------------------------------------------- #
#  API + UI surfaces
# --------------------------------------------------------------------------- #
def test_api_update_endpoint(client, monkeypatch):
    _patch(monkeypatch, version="0.3.1")
    resp = client.get("/api/update")
    assert resp.status_code == 200
    body = resp.json()
    assert body["update_available"] is True
    assert body["latest"] == "0.4.0"
    assert body["current"] == "0.3.1"


def test_ui_update_banner_shown_when_available(client, monkeypatch):
    _patch(monkeypatch, version="0.3.1")
    resp = client.get("/ui/update")
    assert resp.status_code == 200
    assert "Update available" in resp.text
    assert "0.4.0" in resp.text


def test_ui_update_banner_empty_when_current(monkeypatch):
    # Up to date → the fragment renders nothing.
    def fetch(repo, current):
        return UpdateInfo(current, "0.3.1", False, None, checked=True)

    _patch(monkeypatch, version="0.3.1", fetch=fetch)
    from labeljetty.web.app import FastApiAppContainer
    from fastapi.testclient import TestClient

    with TestClient(FastApiAppContainer().app) as c:
        resp = c.get("/ui/update")
    assert resp.status_code == 200
    assert resp.text.strip() == ""
