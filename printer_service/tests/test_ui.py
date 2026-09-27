"""Web UI (HTMX/Jinja) routes through the TestClient.

Covers the public login flow, the render-preview and enqueue routes, polled
fragments, and the Homebox UI section (HTTP to Homebox is mocked).
"""

import io

import pytest
from PIL import Image

from labeljetty.config import AuthUser, Config
from labeljetty.integrations import homebox as hb
from labeljetty.web import auth as auth_mod
from labeljetty.web import ui as ui_mod
from labeljetty.web.password import hash_password


# --------------------------------------------------------------------------- #
#  Pages (open mode)
# --------------------------------------------------------------------------- #
def test_index_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_login_redirects_when_auth_off(client):
    resp = client.get("/login", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


# --------------------------------------------------------------------------- #
#  Login flow (protected mode with a local user)
# --------------------------------------------------------------------------- #
@pytest.fixture
def protected_with_user(monkeypatch):
    cfg = Config(
        _env_file=None,
        PRINTER_USB="vid:0000:pid:0000",
        AUTH_MODE="protected",
        AUTH_USERS=[AuthUser(username="tim", password_hash=hash_password("pw"))],
    )
    monkeypatch.setattr(ui_mod, "config", cfg)
    monkeypatch.setattr(auth_mod, "config", cfg)
    return cfg


def test_login_form_renders(client, protected_with_user):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "password" in resp.text.lower()


def test_login_rejects_bad_credentials(client, protected_with_user):
    resp = client.post(
        "/login", data={"username": "tim", "password": "wrong"}, follow_redirects=False
    )
    assert resp.status_code == 401


def test_login_success_then_access(client, protected_with_user):
    # A browser navigation (Accept: text/html) is redirected to /login.
    html = {"Accept": "text/html"}
    assert client.get("/", headers=html, follow_redirects=False).status_code == 303
    # Log in → 303 redirect, session cookie set.
    resp = client.post(
        "/login", data={"username": "tim", "password": "pw"}, follow_redirects=False
    )
    assert resp.status_code == 303
    # Now the session cookie grants access.
    assert client.get("/", follow_redirects=False).status_code == 200


def test_logout_clears_session(client, protected_with_user):
    client.post("/login", data={"username": "tim", "password": "pw"})
    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


# --------------------------------------------------------------------------- #
#  Preview (render only)
# --------------------------------------------------------------------------- #
def test_preview_text(client):
    resp = client.post("/ui/preview", data={"job_type": "text", "text": "hi"})
    assert resp.status_code == 200
    assert "data:image/png;base64," in resp.text


def test_preview_png_upload(client):
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, "PNG")
    buf.seek(0)
    resp = client.post(
        "/ui/preview",
        data={"job_type": "png", "image_fit": "fit"},
        files={"file": ("a.png", buf, "image/png")},
    )
    assert resp.status_code == 200
    assert "data:image/png;base64," in resp.text


def test_preview_file_job_without_file_shows_error(client):
    resp = client.post("/ui/preview", data={"job_type": "png"})
    assert resp.status_code == 200
    assert "Choose a file" in resp.text


# --------------------------------------------------------------------------- #
#  Print (enqueue) + fragments
# --------------------------------------------------------------------------- #
def test_ui_print_enqueues_and_triggers_refresh(client, worker_running):
    resp = client.post("/ui/print", data={"job_type": "text", "text": "hi"})
    assert resp.status_code == 200
    assert resp.headers.get("HX-Trigger") == "jobsChanged"


def test_ui_print_file_job_without_file_errors(client, worker_running):
    resp = client.post("/ui/print", data={"job_type": "png"})
    assert resp.status_code == 200
    assert "Choose a file" in resp.text


def test_ui_jobs_fragment(client, worker_running):
    client.post("/ui/print", data={"job_type": "text", "text": "hi"})
    resp = client.get("/ui/jobs")
    assert resp.status_code == 200


def test_ui_status_fragment(client):
    # Printer is unreachable (dummy USB id) but the fragment must still render.
    resp = client.get("/ui/status")
    assert resp.status_code == 200


# --------------------------------------------------------------------------- #
#  Homebox UI section
# --------------------------------------------------------------------------- #
@pytest.fixture
def homebox_enabled(monkeypatch):
    monkeypatch.setattr(ui_mod.config, "HOMEBOX_ENABLED", True)
    monkeypatch.setattr(ui_mod.config, "HOMEBOX_URL", "https://box.example.com")
    monkeypatch.setattr(ui_mod.config, "HOMEBOX_API_KEY", "hb_key")


def test_homebox_section_hidden_when_unconfigured(client):
    resp = client.get("/ui/homebox")
    assert resp.status_code == 200
    assert resp.text.strip() == ""


def test_homebox_section_renders_when_configured(client, homebox_enabled):
    resp = client.get("/ui/homebox")
    assert resp.status_code == 200
    assert resp.text.strip() != ""


def test_homebox_search(client, homebox_enabled, monkeypatch):
    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def search(self, q, is_location=False):
            return [hb.HomeboxEntity(id="1", name="Drill", asset_id="000-1")]

        def entity_web_url(self, eid):
            return f"https://box.example.com/item/{eid}"

    monkeypatch.setattr(hb, "HomeboxClient", FakeClient)
    resp = client.get("/ui/homebox/search", params={"q": "drill"})
    assert resp.status_code == 200
    assert "Drill" in resp.text


def test_homebox_search_empty_query(client, homebox_enabled):
    resp = client.get("/ui/homebox/search", params={"q": "  "})
    assert resp.status_code == 200


def test_homebox_print_fetches_and_enqueues(client, homebox_enabled, worker_running, monkeypatch):
    png = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(png, "PNG")
    monkeypatch.setattr(
        ui_mod, "_homebox_fetch_label", lambda kind, eid: (png.getvalue(), ".png")
    )
    resp = client.post(
        "/ui/homebox/print", data={"kind": "item", "entity_id": "abc"}
    )
    assert resp.status_code == 200
    assert resp.headers.get("HX-Trigger") == "jobsChanged"


def test_homebox_setup_page(client):
    resp = client.get("/ui/homebox/setup", params={"host": "printer.local:8888"})
    assert resp.status_code == 200
    assert "curl" in resp.text
    assert "printer.local:8888" in resp.text
