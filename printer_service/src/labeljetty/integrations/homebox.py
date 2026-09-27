"""Homebox integration client (optional, config-gated module).

A thin client over the Homebox **v0.26+** entity API (`/v1/entities`), where
items and locations were merged into a single *entity* model. Used by the web
UI's Homebox section to search items/locations and print a label (QR + name /
asset id) rendered to our label stock.

The module is only active when ``Config.homebox_configured()`` is true
(HOMEBOX_URL + HOMEBOX_API_KEY set). It uses the stdlib ``urllib`` so it adds no
dependency; calls are synchronous and meant to be invoked from threadpool
(``def``) routes.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from labeljetty.config import Config, get_config

config = get_config()


class HomeboxEntity(BaseModel):
    """The subset of a Homebox entity summary the UI + label fetch need."""

    id: str
    name: str
    asset_id: Optional[str] = None
    entity_type: Optional[str] = None
    parent_name: Optional[str] = None
    is_location: bool = False

    @staticmethod
    def _name_of(value: Any) -> Optional[str]:
        """Extract a name from a Homebox sub-object (or accept a bare string)."""
        if isinstance(value, dict):
            return value.get("name") or None
        if isinstance(value, str):
            return value or None
        return None

    @classmethod
    def from_api(cls, raw: Dict[str, Any]) -> "HomeboxEntity":
        # In Homebox v0.26 both `parent` and `entityType` are nested objects.
        etype = raw.get("entityType")
        is_loc = bool(etype.get("isLocation")) if isinstance(etype, dict) else False
        return cls(
            id=str(raw.get("id", "")),
            name=raw.get("name") or "(unnamed)",
            asset_id=raw.get("assetId") or None,
            entity_type=cls._name_of(etype),
            parent_name=cls._name_of(raw.get("parent")),
            is_location=is_loc,
        )

    @property
    def label_kind(self) -> str:
        """The labelmaker endpoint kind for this entity ('item' or 'location')."""
        return "location" if self.is_location else "item"


class HomeboxError(RuntimeError):
    """Raised when the Homebox API cannot be reached or returns an error."""


class HomeboxClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        api_prefix: Optional[str] = None,
        timeout: float = 10.0,
    ):
        self.base_url = (base_url or config.HOMEBOX_URL or "").rstrip("/")
        self.api_key = api_key or config.HOMEBOX_API_KEY or ""
        self.api_prefix = (api_prefix or config.HOMEBOX_API_PREFIX).rstrip("/")
        self.timeout = timeout
        if not self.base_url or not self.api_key:
            raise HomeboxError("Homebox is not configured (URL/API key missing).")

    def _request(self, path: str, params: Dict[str, Any]) -> tuple[bytes, str]:
        """GET ``<prefix><path>?<params>`` → (body bytes, content-type)."""
        query = urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None}
        )
        url = f"{self.base_url}{self.api_prefix}{path}"
        if query:
            url = f"{url}?{query}"
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {self.api_key}"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
            raise HomeboxError(f"Homebox returned HTTP {e.code}: {e.reason}") from e
        except Exception as e:
            raise HomeboxError(f"Could not reach Homebox: {e}") from e

    def _get(self, path: str, params: Dict[str, Any]) -> Any:
        body, _ = self._request(path, params)
        return json.loads(body.decode("utf-8"))

    def search(
        self, query: str, is_location: bool = False, page_size: int = 20
    ) -> List[HomeboxEntity]:
        """Search entities (items by default, or locations when ``is_location``)."""
        data = self._get(
            "/entities",
            {
                "q": query or "",
                "isLocation": "true" if is_location else None,
                "pageSize": page_size,
            },
        )
        # Paginated shape: {"items": [...]} — be tolerant of a bare list too.
        rows = data.get("items", data) if isinstance(data, dict) else data
        return [HomeboxEntity.from_api(r) for r in (rows or [])]

    def entity_web_url(self, entity_id: str) -> str:
        """Build the Homebox web URL an entity opens at (for an 'open in Homebox' link)."""
        path = config.HOMEBOX_ENTITY_URL_TEMPLATE.format(id=entity_id)
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def fetch_label(self, kind: str, entity_id: str) -> tuple[bytes, str]:
        """Fetch Homebox's **own** rendered label image for an entity.

        Calls ``/labelmaker/{kind}/{id}`` (kind = item / location / asset) and
        returns ``(image_bytes, content_type)``. We deliberately do NOT pass
        ``print=true`` — that would make Homebox run *its* print command; here we
        only want the image so we can print it ourselves.
        """
        if kind not in ("item", "location", "asset"):
            raise HomeboxError(f"Unknown label kind: {kind}")
        return self._request(f"/labelmaker/{kind}/{entity_id}", {})
