"""Update-available check: compare the running version against the latest
GitHub release and cache the answer.

Why this exists: a Docker deployment can't update itself in place — the user
still runs ``docker compose pull && docker compose up -d`` (see
``docs/updating.md``). What we *can* do safely is tell them an update is out, so
the web UI shows a banner and ``/api/update`` exposes the same facts to scripts.

It is outbound-only: a single GET to the public GitHub releases API, gated by
``UPDATE_CHECK_ENABLED`` so offline/air-gapped deployments can turn it off. The
result is cached process-wide so page loads don't hit GitHub on every request.
``releases/latest`` excludes drafts and pre-releases, so beta tags never nag.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import dataclass
from typing import Optional

from labeljetty.core.logging import get_logger

log = get_logger()

# A successful answer is trusted this long before we ask GitHub again. Releases
# are infrequent; a few hours keeps the UI snappy without polling.
_CACHE_TTL_SECONDS = 6 * 3600
# A failed lookup (offline, rate-limited, DNS) is cached briefly so a broken
# network doesn't stall every page load with a fresh timeout.
_ERROR_TTL_SECONDS = 15 * 60
_HTTP_TIMEOUT_SECONDS = 4

_GITHUB_LATEST_RELEASE = "https://api.github.com/repos/{repo}/releases/latest"

# A clean release version is digits-and-dots, optionally a leading "v". Anything
# else (a setuptools_scm dev/local build like "0.3.1.dev4+g1234" or the
# source-tree fallback "0.0.0+unknown") is NOT a clean release — we never flag an
# update against it, since comparing would just nag a developer's checkout.
_RELEASE_RE = re.compile(r"v?(\d+(?:\.\d+)*)")
_CLEAN_RELEASE_RE = re.compile(r"v?\d+(?:\.\d+)*$")


@dataclass
class UpdateInfo:
    current: str
    latest: Optional[str]
    update_available: bool
    release_url: Optional[str]
    # False when the check is disabled or could not reach GitHub — lets callers
    # tell "no update" apart from "we don't know".
    checked: bool


# (expires_at_monotonic, info) — None until the first lookup.
_cache: Optional[tuple[float, UpdateInfo]] = None


def _release_tuple(text: str) -> Optional[tuple[int, ...]]:
    """Leading numeric release as a tuple: 'v0.3.1' -> (0, 3, 1), or None."""
    m = _RELEASE_RE.match((text or "").strip())
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def _is_clean_release(text: str) -> bool:
    return bool(_CLEAN_RELEASE_RE.fullmatch((text or "").strip()))


def _is_newer(latest: str, current: str) -> bool:
    """True when ``latest`` is a strictly newer release than ``current``. Only a
    clean release ``current`` can be 'behind' — dev/local builds never nag."""
    if not _is_clean_release(current):
        return False
    lt, ct = _release_tuple(latest), _release_tuple(current)
    return bool(lt and ct and lt > ct)


def _fetch(repo: str, current: str) -> UpdateInfo:
    url = _GITHUB_LATEST_RELEASE.format(repo=repo)
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "LabelJetty-update-check",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:
            data = json.load(resp)
    except Exception as e:  # offline, rate-limited, no releases yet, bad repo…
        log.debug(f"Update check failed for {repo!r}: {e}")
        return UpdateInfo(current, None, False, None, checked=False)

    tag = (data.get("tag_name") or "").strip()
    return UpdateInfo(
        current=current,
        latest=tag or None,
        update_available=bool(tag and _is_newer(tag, current)),
        release_url=data.get("html_url"),
        checked=True,
    )


def check_for_update(*, force: bool = False) -> UpdateInfo:
    """Return cached update info, refreshing from GitHub when the cache expires.

    Honours ``UPDATE_CHECK_ENABLED`` (returns ``checked=False`` when off). The
    GitHub call is blocking, so call this from a sync (threadpool) route, not an
    async one. ``force`` bypasses the cache (used by tests)."""
    from labeljetty.config import get_config
    from labeljetty.version import get_version

    cfg = get_config()
    current = get_version()

    if not cfg.UPDATE_CHECK_ENABLED:
        return UpdateInfo(current, None, False, None, checked=False)

    global _cache
    now = time.monotonic()
    if not force and _cache is not None:
        expires, info = _cache
        # A config change (current version, repo) shouldn't be masked by a stale
        # cache entry; the version is fixed per process, but the repo can change.
        if now < expires and info.current == current:
            return info

    info = _fetch(cfg.UPDATE_CHECK_REPO, current)
    ttl = _CACHE_TTL_SECONDS if info.checked else _ERROR_TTL_SECONDS
    _cache = (now + ttl, info)
    return info


def _reset_cache() -> None:
    """Drop the cached result (tests / after a config change)."""
    global _cache
    _cache = None
