"""Homebox client — entity parsing + HTTP behavior with urllib fully mocked."""

import io
import json
import urllib.error

import pytest

from labeljetty.integrations import homebox as hb
from labeljetty.integrations.homebox import HomeboxClient, HomeboxEntity, HomeboxError


def make_client():
    return HomeboxClient(base_url="https://box.example.com", api_key="hb_key")


class FakeResp:
    def __init__(self, body: bytes, content_type="application/json"):
        self._body = body
        self.headers = {"Content-Type": content_type}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def patch_urlopen(monkeypatch):
    """Patch urlopen; the test sets ``box['resp']`` or ``box['error']``."""
    box = {}

    def fake_urlopen(req, timeout=None):
        if "error" in box:
            raise box["error"]
        box["last_url"] = req.full_url
        box["last_headers"] = req.headers
        return box["resp"]

    monkeypatch.setattr(hb.urllib.request, "urlopen", fake_urlopen)
    return box


# --------------------------------------------------------------------------- #
#  Entity parsing
# --------------------------------------------------------------------------- #
def test_entity_from_api_item():
    e = HomeboxEntity.from_api(
        {
            "id": "abc",
            "name": "Drill",
            "assetId": "000-123",
            "entityType": {"name": "Tool", "isLocation": False},
            "parent": {"name": "Garage"},
        }
    )
    assert e.id == "abc"
    assert e.name == "Drill"
    assert e.asset_id == "000-123"
    assert e.entity_type == "Tool"
    assert e.parent_name == "Garage"
    assert e.is_location is False
    assert e.label_kind == "item"


def test_entity_from_api_location():
    e = HomeboxEntity.from_api(
        {"id": "1", "name": "Shelf", "entityType": {"isLocation": True}}
    )
    assert e.is_location is True
    assert e.label_kind == "location"


def test_entity_unnamed_fallback():
    assert HomeboxEntity.from_api({"id": "1"}).name == "(unnamed)"


# --------------------------------------------------------------------------- #
#  Construction guard
# --------------------------------------------------------------------------- #
def test_requires_url_and_key():
    with pytest.raises(HomeboxError):
        HomeboxClient(base_url="", api_key="")


# --------------------------------------------------------------------------- #
#  search
# --------------------------------------------------------------------------- #
def test_search_parses_items_envelope(patch_urlopen):
    patch_urlopen["resp"] = FakeResp(
        json.dumps({"items": [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]}).encode()
    )
    results = make_client().search("a")
    assert [e.name for e in results] == ["A", "B"]
    # Sends a bearer header + the query.
    assert "Bearer hb_key" in patch_urlopen["last_headers"].get("Authorization", "")
    assert "q=a" in patch_urlopen["last_url"]


def test_search_tolerates_bare_list(patch_urlopen):
    patch_urlopen["resp"] = FakeResp(json.dumps([{"id": "1", "name": "A"}]).encode())
    assert len(make_client().search("a")) == 1


def test_search_location_flag(patch_urlopen):
    patch_urlopen["resp"] = FakeResp(json.dumps({"items": []}).encode())
    make_client().search("x", is_location=True)
    assert "isLocation=true" in patch_urlopen["last_url"]


# --------------------------------------------------------------------------- #
#  entity_web_url / fetch_label
# --------------------------------------------------------------------------- #
def test_entity_web_url_uses_template():
    url = make_client().entity_web_url("xyz")
    assert url == "https://box.example.com/item/xyz"


def test_fetch_label_returns_bytes_and_type(patch_urlopen):
    patch_urlopen["resp"] = FakeResp(b"\x89PNG...", content_type="image/png")
    data, ctype = make_client().fetch_label("item", "abc")
    assert data.startswith(b"\x89PNG")
    assert ctype == "image/png"
    assert "/labelmaker/item/abc" in patch_urlopen["last_url"]


def test_fetch_label_rejects_unknown_kind():
    with pytest.raises(HomeboxError):
        make_client().fetch_label("spaceship", "1")


# --------------------------------------------------------------------------- #
#  Error handling
# --------------------------------------------------------------------------- #
def test_http_error_becomes_homebox_error(patch_urlopen):
    patch_urlopen["error"] = urllib.error.HTTPError(
        "u", 401, "Unauthorized", {}, io.BytesIO(b"")
    )
    with pytest.raises(HomeboxError):
        make_client().search("a")


def test_connection_error_becomes_homebox_error(patch_urlopen):
    patch_urlopen["error"] = OSError("connection refused")
    with pytest.raises(HomeboxError):
        make_client().search("a")
