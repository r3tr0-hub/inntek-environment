"""Tests for the auth seam: password hashing, providers, and require_access."""

import asyncio

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from labeljetty.config import Config, AuthToken, AuthUser
from labeljetty.web import auth
from labeljetty.web.password import hash_password, verify_password


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def make_config(**overrides) -> Config:
    """A Config with PRINTER_USB satisfied, plus overrides — no .env dependence."""
    base = dict(PRINTER_USB="vid:0000:pid:0000", _env_file=None)
    base.update(overrides)
    return Config(**base)


def make_request(path="/", headers=None, session=None, query="") -> Request:
    raw_headers = [
        (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": raw_headers,
        "state": {},
    }
    if session is not None:
        scope["session"] = session
    return Request(scope)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --------------------------------------------------------------------------- #
#  Password hashing
# --------------------------------------------------------------------------- #
def test_password_roundtrip():
    h = hash_password("hunter2")
    assert h.startswith("pbkdf2_sha256$")
    assert verify_password("hunter2", h)
    assert not verify_password("hunter3", h)


def test_password_unique_salt():
    assert hash_password("x") != hash_password("x")


def test_verify_rejects_malformed():
    assert not verify_password("x", "not-a-valid-hash")
    assert not verify_password("x", "")


# --------------------------------------------------------------------------- #
#  Token provider
# --------------------------------------------------------------------------- #
def test_token_authenticator_accepts_valid():
    cfg = make_config(AUTH_TOKENS=[AuthToken(name="ci", token="s3cr3t")])
    a = auth.TokenAuthenticator(cfg)
    req = make_request(headers={"Authorization": "Bearer s3cr3t"})
    principal = run(a.authenticate(req))
    assert principal is not None
    assert principal.kind == "token"
    assert principal.display_name == "ci"


@pytest.mark.parametrize(
    "header",
    [None, "Bearer wrong", "Basic s3cr3t", "s3cr3t", "Bearer "],
)
def test_token_authenticator_rejects(header):
    cfg = make_config(AUTH_TOKENS=[AuthToken(name="ci", token="s3cr3t")])
    a = auth.TokenAuthenticator(cfg)
    headers = {"Authorization": header} if header is not None else {}
    assert run(a.authenticate(make_request(headers=headers))) is None


# --------------------------------------------------------------------------- #
#  Session provider
# --------------------------------------------------------------------------- #
def test_session_authenticator_resolves_user():
    cfg = make_config(
        AUTH_USERS=[AuthUser(username="tim", password_hash=hash_password("pw"))]
    )
    a = auth.SessionAuthenticator(cfg)
    principal = run(a.authenticate(make_request(session={"sub": "tim"})))
    assert principal is not None
    assert principal.kind == "user"
    assert principal.display_name == "tim"


def test_session_authenticator_unknown_user():
    cfg = make_config(
        AUTH_USERS=[AuthUser(username="tim", password_hash=hash_password("pw"))]
    )
    a = auth.SessionAuthenticator(cfg)
    assert run(a.authenticate(make_request(session={"sub": "ghost"}))) is None
    assert run(a.authenticate(make_request(session={}))) is None
    assert run(a.authenticate(make_request())) is None  # no SessionMiddleware


# --------------------------------------------------------------------------- #
#  require_access seam
# --------------------------------------------------------------------------- #
def test_open_mode_allows_anonymous(monkeypatch):
    monkeypatch.setattr(auth, "config", make_config(AUTH_MODE="open"))
    principal = run(auth.require_access(make_request()))
    assert principal.kind == "anonymous"
    assert not principal.is_authenticated


def test_protected_token_path(monkeypatch):
    monkeypatch.setattr(
        auth,
        "config",
        make_config(AUTH_MODE="protected", AUTH_TOKENS=[AuthToken(name="ci", token="t0p")]),
    )
    req = make_request(path="/api/jobs", headers={"Authorization": "Bearer t0p"})
    principal = run(auth.require_access(req))
    assert principal.kind == "token"
    # require_access stashes the principal for templates/UX.
    assert req.state.principal is principal


def test_protected_api_missing_creds_401(monkeypatch):
    monkeypatch.setattr(
        auth,
        "config",
        make_config(AUTH_MODE="protected", AUTH_TOKENS=[AuthToken(name="ci", token="t0p")]),
    )
    with pytest.raises(HTTPException) as exc:
        run(auth.require_access(make_request(path="/api/jobs")))
    assert exc.value.status_code == 401
    assert exc.value.headers.get("WWW-Authenticate") == "Bearer"


def test_protected_browser_redirects_to_login(monkeypatch):
    monkeypatch.setattr(
        auth,
        "config",
        make_config(AUTH_MODE="protected", AUTH_USERS=[AuthUser(username="tim", password_hash=hash_password("pw"))]),
    )
    req = make_request(path="/", headers={"Accept": "text/html"})
    with pytest.raises(HTTPException) as exc:
        run(auth.require_access(req))
    assert exc.value.status_code == 303
    assert exc.value.headers["Location"].startswith("/login?next=")


# --------------------------------------------------------------------------- #
#  Config validation
# --------------------------------------------------------------------------- #
def test_protected_without_providers_raises():
    with pytest.raises(Exception):
        make_config(AUTH_MODE="protected")
