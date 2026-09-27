"""Authentication & authorization — the single ``require_access`` seam.

Every API and UI route depends on :func:`require_access`. The design separates
*authentication* (who are you? → a :class:`Principal`) from *route wiring* so new
auth mechanisms drop in without touching any route signature.

Providers (``Authenticator`` strategies) are peers, tried in order; the first to
return a :class:`Principal` wins:

* :class:`TokenAuthenticator` — ``Authorization: Bearer <token>`` for machines.
* :class:`SessionAuthenticator` — a signed session cookie for humans (set by the
  ``/login`` form).

OIDC is intended as a future third provider: its callback would populate the same
session (``request.session["sub"]``) and either reuse :class:`SessionAuthenticator`
or add a sibling — no route changes, because routes only ever see a ``Principal``.

Failure handling diverges by client: browsers (Accept: text/html) are redirected
to ``/login``; API clients get ``401`` JSON with a ``WWW-Authenticate`` header.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Annotated, Literal, Optional, Protocol

from fastapi import Depends, HTTPException, Request, status

from labeljetty.config import Config, get_config
from labeljetty.core.logging import get_logger
from labeljetty.web.password import verify_password


config = get_config()
log = get_logger()

PrincipalKind = Literal["anonymous", "token", "user", "oidc"]


@dataclass
class Principal:
    """The authenticated identity attached to a request.

    Returning an identity (rather than a bare bool) is what keeps the system
    OIDC-ready: a future OIDC login just yields another ``Principal`` with
    ``kind="oidc"`` and its claims, and every route keeps working unchanged.
    """

    subject: str
    kind: PrincipalKind
    display_name: str
    claims: dict = field(default_factory=dict)

    @classmethod
    def anonymous(cls) -> "Principal":
        return cls(subject="anonymous", kind="anonymous", display_name="Anonymous")

    @property
    def is_authenticated(self) -> bool:
        return self.kind != "anonymous"


class Authenticator(Protocol):
    """A pluggable auth strategy. Returns a Principal if it can identify the
    request, else None (let the next provider try)."""

    async def authenticate(self, request: Request) -> Optional[Principal]: ...


def _bearer_token(request: Request) -> Optional[str]:
    header = request.headers.get("Authorization")
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value.strip()


class TokenAuthenticator:
    """Matches an ``Authorization: Bearer`` token against ``config.AUTH_TOKENS``."""

    def __init__(self, config: Config):
        self._tokens = config.AUTH_TOKENS

    async def authenticate(self, request: Request) -> Optional[Principal]:
        presented = _bearer_token(request)
        if presented is None:
            return None
        for entry in self._tokens:
            # Constant-time compare to avoid leaking token length/content via timing.
            if secrets.compare_digest(presented, entry.token):
                return Principal(
                    subject=f"token:{entry.name}",
                    kind="token",
                    display_name=entry.name,
                )
        return None


class SessionAuthenticator:
    """Resolves the signed session cookie's subject to a configured local user.

    OIDC will reuse this same session mechanism — the callback sets
    ``request.session["sub"]`` and (optionally) the provider distinguishes OIDC
    subjects from local ones.
    """

    def __init__(self, config: Config):
        self._config = config

    async def authenticate(self, request: Request) -> Optional[Principal]:
        # request.session asserts SessionMiddleware is installed; guard via the
        # scope so token-only setups (or misconfiguration) degrade gracefully.
        if "session" not in request.scope:
            return None
        session = request.session
        if not session:
            return None
        subject = session.get("sub")
        if not subject:
            return None
        user = self._config.find_user(subject)
        if user is None:
            return None
        return Principal(subject=user.username, kind="user", display_name=user.username)


def build_authenticators(config: Config) -> list[Authenticator]:
    """Assemble the enabled providers, in priority order."""
    providers: list[Authenticator] = []
    if config.AUTH_TOKENS:
        providers.append(TokenAuthenticator(config))
    if config.AUTH_USERS:
        providers.append(SessionAuthenticator(config))
    return providers


def _wants_html(request: Request) -> bool:
    """True for browser navigations (redirect to login) vs API clients (401)."""
    if request.url.path.startswith("/api"):
        return False
    return "text/html" in request.headers.get("accept", "")


def _reject(request: Request) -> HTTPException:
    if _wants_html(request):
        next_url = request.url.path
        if request.url.query:
            next_url += f"?{request.url.query}"
        # A 303 with a Location header redirects browsers to the login page; the
        # JSON body is ignored by the browser. OIDC's "redirect to IdP" slots in here.
        from urllib.parse import quote

        return HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": f"/login?next={quote(next_url)}"},
        )
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_access(request: Request) -> Principal:
    """Central authorization seam for **every** endpoint (API and web UI).

    Open mode → anonymous Principal (no checks). Protected mode → the first
    provider that recognises the request wins; if none do, browsers are
    redirected to ``/login`` and API clients receive ``401``.
    """
    if not config.auth_enabled():
        principal = Principal.anonymous()
        request.state.principal = principal
        return principal

    for provider in build_authenticators(config):
        principal = await provider.authenticate(request)
        if principal is not None:
            request.state.principal = principal
            return principal

    raise _reject(request)


def current_principal(request: Request) -> Principal:
    """Best-effort principal for templates/UX (set by :func:`require_access`)."""
    return getattr(request.state, "principal", None) or Principal.anonymous()


__all__ = [
    "Principal",
    "Authenticator",
    "TokenAuthenticator",
    "SessionAuthenticator",
    "build_authenticators",
    "require_access",
    "current_principal",
    "verify_password",
]
