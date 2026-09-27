import json
import os
import sqlite3
from typing import TYPE_CHECKING, Any, Dict, List, Self
from pathlib import Path
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings
from typing import Literal, Optional

if TYPE_CHECKING:
    from labeljetty.printer.connection import TSPLPrinterConnectionUSB

# `.env` is looked up relative to the current working directory (the repo root,
# per the README) — the override env var takes precedence. It is intentionally
# not resolved relative to this file, which now lives inside the package.
env_file_path = os.environ.get(
    "LABELJETTY_DOT_ENV_FILE", Path(".env")
)


def _ui(
    group: str,
    *,
    label: Optional[str] = None,
    widget: Optional[str] = None,
    restart: bool = False,
    secret: bool = False,
) -> Dict[str, Any]:
    """Mark a Config field as editable in the web settings UI.

    Attached via ``Field(json_schema_extra=_ui(...))``. The settings page
    introspects ``Config.model_fields`` and renders a form from the fields that
    carry this metadata — adding a new editable setting is just one flag here, no
    UI code. ``widget`` overrides the annotation-inferred input (e.g. ``"json"``
    for list-of-model fields); ``restart`` flags values that only take effect
    after a process restart; ``secret`` masks the value (reserved — no secrets
    are exposed in the UI yet)."""
    return {
        "ui": {
            "editable": True,
            "group": group,
            "label": label,
            "widget": widget,
            "restart": restart,
            "secret": secret,
        }
    }


class LabelProfile(BaseModel):
    """A named label stock (width × height in mm), selectable in the web UI."""

    name: str
    width_mm: int
    height_mm: int
    dpi: Optional[int] = None


class AuthToken(BaseModel):
    """A named API token for machine-to-machine access (sent as a Bearer token)."""

    name: str
    token: str


class AuthUser(BaseModel):
    """A local login user. ``password_hash`` is a ``pbkdf2_sha256$…`` string —
    generate it with the ``labeljetty-hash-password`` CLI (never store plaintext)."""

    username: str
    password_hash: str


class Config(BaseSettings):
    APP_NAME: str = "LabelJetty"
    LOG_LEVEL: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = Field(
        default="DEBUG",
        json_schema_extra=_ui("System", label="Log level", restart=True),
    )
    LOG_DISABLE_COLORS: bool = False
    UVICORN_LOG_LEVEL: Optional[str] = Field(
        default=None,
        description="The log level of the uvicorn server. If not defined it will be the same as LOG_LEVEL.",
    )
    SERVER_LISTENING_PORT: int = Field(default=8888)
    SERVER_LISTENING_HOST: str = Field(
        default="localhost",
        examples=["0.0.0.0", "localhost", "127.0.0.1", "176.16.8.123"],
    )
    SQLITE_PATH: str = Field(default="./printjobs.sqlite")
    IMAGE_STORAGE_DIRECTORY: str = Field(
        default="./images", description="Storage for posted images to print"
    )
    # --- Authentication ----------------------------------------------------- #
    # AUTH_MODE selects the policy. "open" (default) = no auth at all — intended
    # for a trusted LAN appliance. See the fat warning in the README before
    # exposing the service beyond a trusted network. "protected" = every route
    # requires a valid credential from ANY configured provider (tokens and/or
    # local users; OIDC is planned as a drop-in third provider).
    AUTH_MODE: Literal["open", "protected"] = Field(
        default="open",
        json_schema_extra=_ui("Authentication", label="Authentication mode"),
    )
    # API tokens for machine-to-machine access, as a JSON list, e.g.
    #   AUTH_TOKENS='[{"name":"ci","token":"s3cr3t"}]'
    # Sent by clients as `Authorization: Bearer <token>`.
    AUTH_TOKENS: List[AuthToken] = Field(default_factory=list)
    # Local login users (humans, via the /login form → session cookie), e.g.
    #   AUTH_USERS='[{"username":"tim","password_hash":"pbkdf2_sha256$..."}]'
    # Generate password_hash with: labeljetty-hash-password
    AUTH_USERS: List[AuthUser] = Field(
        default_factory=list,
        json_schema_extra=_ui("Authentication", label="Login users", widget="auth_users"),
    )
    # Secret used to sign session cookies. Leave unset for an ephemeral random
    # secret (logins won't survive a restart) — set a stable value in production.
    SESSION_SECRET: Optional[str] = Field(default=None)
    SESSION_COOKIE_NAME: str = Field(default="labeljetty_session")
    SESSION_MAX_AGE: int = Field(default=1_209_600, description="Session lifetime in seconds (default 14 days).")
    # --- OIDC (reserved — planned drop-in provider, not yet implemented) ----- #
    # AUTH_OIDC_ISSUER / AUTH_OIDC_CLIENT_ID / AUTH_OIDC_CLIENT_SECRET will be
    # added when OIDC lands. The auth framework already returns a Principal and
    # resolves providers from the session, so OIDC slots in without route changes.
    DELETE_OLD_JOBS_AFTER_DAYS: int = Field(
        default=100,
        description="Old job entries in the database will be removed with associated files.",
        json_schema_extra=_ui("Maintenance", label="Delete old jobs after (days)"),
    )
    # --- Update check (optional, outbound) ---------------------------------- #
    # Compares the running version against the latest GitHub release and shows an
    # "update available" banner in the web UI. Updating itself is still manual
    # (docker compose pull && up -d — see docs/updating.md); this only notifies.
    UPDATE_CHECK_ENABLED: bool = Field(
        default=True,
        description=(
            "Check GitHub for a newer release and show an 'update available' banner "
            "in the web UI. One outbound HTTPS call to the public GitHub API, cached "
            "for hours. Turn off for offline/air-gapped deployments."
        ),
        json_schema_extra=_ui("Maintenance", label="Check for updates"),
    )
    UPDATE_CHECK_REPO: str = Field(
        default="motey/LabelJetty",
        description="GitHub 'owner/repo' queried for the latest release (set this on a fork).",
        json_schema_extra=_ui("Maintenance", label="Update check repo (owner/repo)"),
    )
    # Default label geometry — used when a print job does not specify its own.
    DEFAULT_LABEL_WIDTH_MM: int = Field(
        default=100, json_schema_extra=_ui("Label defaults", label="Default width (mm)")
    )
    DEFAULT_LABEL_HEIGHT_MM: int = Field(
        default=30, json_schema_extra=_ui("Label defaults", label="Default height (mm)")
    )
    DEFAULT_DPI: int = Field(
        default=203, json_schema_extra=_ui("Label defaults", label="Default DPI")
    )
    # Named label profiles selectable in the web UI, as a JSON list, e.g.
    #   LABEL_PROFILES='[{"name":"Homebox","width_mm":57,"height_mm":32}]'
    # The server default geometry is always offered as a "Default" profile too.
    LABEL_PROFILES: List[LabelProfile] = Field(
        default_factory=list,
        json_schema_extra=_ui(
            "Label defaults", label="Label profiles", widget="label_profiles"
        ),
    )

    # --- Settings UI (the admin config page itself) ------------------------- #
    # The page is OFF by default: in AUTH_MODE=open anyone reaching the box could
    # otherwise rewrite config. Enable deliberately, ideally alongside protected
    # auth. Edits are stored in the DB and OVERRIDE env vars (DB > env > default).
    SETTINGS_UI_ENABLED: bool = Field(default=False)
    # Field names pinned to their env/default value: shown read-only in the UI and
    # never taken from the DB overlay. For managed deployments (e.g. the Pi image)
    # that want to forbid override of specific keys, e.g.
    #   SETTINGS_LOCKED_KEYS='["HOMEBOX_URL","LOG_LEVEL"]'
    SETTINGS_LOCKED_KEYS: List[str] = Field(default_factory=list)

    # --- Homebox integration (optional module) ------------------------------ #
    # The module's UI section + endpoints appear only when HOMEBOX_URL and
    # HOMEBOX_API_KEY are both set (and HOMEBOX_ENABLED is true).
    HOMEBOX_ENABLED: bool = Field(
        default=True, json_schema_extra=_ui("Homebox", label="Enable Homebox module")
    )
    HOMEBOX_URL: Optional[str] = Field(
        default=None,
        description="Base URL of the Homebox server, e.g. https://box.example.com",
        json_schema_extra=_ui("Homebox", label="Homebox URL"),
    )
    # API key stays env-only for now — secrets are not exposed in the settings UI.
    HOMEBOX_API_KEY: Optional[str] = Field(
        default=None, description="Homebox API key (prefixed 'hb_…')."
    )
    HOMEBOX_API_PREFIX: str = Field(
        default="/api/v1",
        description="API path prefix on the Homebox server (entities live at <prefix>/entities).",
        json_schema_extra=_ui("Homebox", label="API path prefix"),
    )
    HOMEBOX_ENTITY_URL_TEMPLATE: str = Field(
        default="/item/{id}",
        description="Web path (appended to HOMEBOX_URL) an entity opens at; '{id}' is substituted. Used for the QR link.",
        json_schema_extra=_ui("Homebox", label="Entity URL template"),
    )
    HOMEBOX_LABEL_MARGIN_MM: float = Field(
        default=0.0,
        ge=0.0,
        json_schema_extra=_ui("Homebox", label="Safety border (mm)"),
        description=(
            "Blank safety border reserved on all sides when printing a Homebox "
            "label. Homebox renders its own label edge-to-edge (sized by the "
            "server-side HBOX_LABEL_MAKER_* settings, which we cannot override per "
            "request), so we inset its image to keep content off the label edge. "
            "Defaults to 0 (print exactly what Homebox returns); raise it if your "
            "Homebox label content sits too close to the edge."
        ),
    )
    HOMEBOX_LABEL_SERVICE_AUTOPRINT: bool = Field(
        default=True,
        json_schema_extra=_ui("Homebox", label="Auto-print on label-service fetch"),
        description=(
            "For the push 'external label service' endpoint: also enqueue the print "
            "as a side effect of Homebox requesting the label image. Disable if your "
            "Homebox build calls the label-service URL for previews too (would cause "
            "spurious prints) — then use the print-command script (path C) instead."
        ),
    )

    def homebox_configured(self) -> bool:
        """True when the Homebox module should be active."""
        return bool(self.HOMEBOX_ENABLED and self.HOMEBOX_URL and self.HOMEBOX_API_KEY)

    def auth_enabled(self) -> bool:
        """True when routes require authentication (``AUTH_MODE == "protected"``)."""
        return self.AUTH_MODE == "protected"

    def find_user(self, username: str) -> Optional[AuthUser]:
        """Return the configured user with this username, or None."""
        for user in self.AUTH_USERS:
            if user.username == username:
                return user
        return None

    @model_validator(mode="after")
    def validate_auth_config(self) -> Self:
        """Guard against a lock-everyone-out / no-op auth configuration."""
        if self.AUTH_MODE == "protected" and not self.AUTH_TOKENS and not self.AUTH_USERS:
            raise ValueError(
                "AUTH_MODE=protected but neither AUTH_TOKENS nor AUTH_USERS is "
                "configured — this would lock out every request. Configure at "
                "least one token or user, or set AUTH_MODE=open."
            )
        return self

    def get_label_profiles(self) -> List[LabelProfile]:
        """Configured profiles, preceded by the server-default geometry."""
        default = LabelProfile(
            name="Default",
            width_mm=self.DEFAULT_LABEL_WIDTH_MM,
            height_mm=self.DEFAULT_LABEL_HEIGHT_MM,
            dpi=self.DEFAULT_DPI,
        )
        return [default, *self.LABEL_PROFILES]
    # USB Printer - leave UNSET to auto-detect a connected TSPL printer, or pin a
    # specific device with ONE of the selector forms below.
    PRINTER_USB: Optional[str] = Field(
        default=None,
        json_schema_extra=_ui("Printer", label="USB printer", widget="printer_select"),
        description=(
            "USB printer identifier. Leave unset to auto-detect a connected TSPL "
            "printer (matches known vendors and USB printer-class devices). "
            "To pin a device, use one of:\n"
            "  - Serial number:     'serial:ABC123456'\n"
            "  - Device path:       'path:/dev/bus/usb/001/004' or 'path:001/004'\n"
            "  - USB port:          'port:3-1-2'\n"
            "  - Vendor+Product ID: 'vid:1234:pid:5678' or 'vid:1234' (first match)\n"
            "  - Bus+Address:       'bus:1:addr:4'"
        ),
        examples=[
            "serial:ABC123456",
            "path:/dev/bus/usb/001/004",
            "port:3-1-2",
            "vid:1234:pid:5678",
            "bus:1:addr:4",
        ],
    )

    def get_printer_connection(self) -> "TSPLPrinterConnectionUSB":
        """Returns a printer connection using the configured identifier, or
        auto-detects a connected TSPL printer when ``PRINTER_USB`` is unset."""
        from labeljetty.printer.connection import TSPLPrinterConnectionUSB

        usb_id = self.PRINTER_USB

        if not usb_id:
            return TSPLPrinterConnectionUSB.autodetect()

        if usb_id.startswith("serial:"):
            serial = usb_id.split(":", 1)[1]
            return TSPLPrinterConnectionUSB.by_serial(serial)

        elif usb_id.startswith("path:"):
            path = usb_id.split(":", 1)[1]
            return TSPLPrinterConnectionUSB.by_device_path(path)

        elif usb_id.startswith("port:"):
            port = usb_id.split(":", 1)[1]
            return TSPLPrinterConnectionUSB.by_port(port)

        elif usb_id.startswith("bus:"):
            # Format: bus:1:addr:4
            parts = usb_id.split(":")
            if len(parts) != 4 or parts[2] != "addr":
                raise ValueError(
                    f"Invalid bus format: {usb_id}. Expected 'bus:1:addr:4'"
                )
            bus = int(parts[1])
            addr = int(parts[3])
            return TSPLPrinterConnectionUSB.by_bus_and_device_id(bus, addr)

        elif usb_id.startswith("vid:"):
            # Format: vid:1234:pid:5678 or vid:1234
            parts = usb_id.split(":")
            vendor = parts[1]
            product = parts[3] if len(parts) >= 4 and parts[2] == "pid" else None
            return TSPLPrinterConnectionUSB.by_vendor_and_product_id(vendor, product)

        else:
            raise ValueError(
                f"Invalid PRINTER_USB format: {usb_id}\n"
                "Must start with: serial:, path:, port:, bus:, or vid:"
            )

    ###### CONFIG END ######
    # "class Config:" is a pydantic-settings pre-defined config class to control the behaviour of our settings model
    # you could call it a "meta config" class
    # if you dont know what this is you can ignore it.
    # https://docs.pydantic.dev/latest/api/base_model/#pydantic.main.BaseModel.model_config

    class Config:
        env_nested_delimiter = "__"
        env_file = env_file_path
        env_file_encoding = "utf-8"
        extra = "ignore"


# --------------------------------------------------------------------------- #
#  Settings overlay + process-wide singleton
#
#  Precedence: DB overlay (admin, via the settings UI) > env / .env > default.
#  ``Config()`` alone reads only env/defaults (keeping tests isolated); the app
#  must go through ``get_config()`` / ``build_config()`` to apply the overlay.
# --------------------------------------------------------------------------- #

# Table name SQLModel derives from the ``SettingOverride`` model in core.db. We
# read it here with stdlib sqlite3 (read-only) to avoid importing the DB layer
# (which imports this module) — no circular import, and no DB file is created.
_OVERLAY_TABLE = "settingoverride"

_config_singleton: Optional["Config"] = None


def _load_db_overlay(sqlite_path: str) -> Dict[str, Any]:
    """Return ``{field_name: python_value}`` from the settings-override table, or
    ``{}`` if the DB/table doesn't exist yet. Read-only — never creates the file."""
    if not os.path.exists(sqlite_path):
        return {}
    try:
        con = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
        try:
            rows = con.execute(
                f"SELECT key, json_value FROM {_OVERLAY_TABLE}"
            ).fetchall()
        finally:
            con.close()
    except sqlite3.OperationalError:
        # File exists but the table hasn't been created yet (first run).
        return {}
    return {key: json.loads(value) for key, value in rows}


def build_config() -> "Config":
    """Construct a Config from env/.env, then apply the DB overlay on top.

    Overlay values are passed as constructor kwargs, which outrank env in
    pydantic-settings, and are run through the model's validators — so a bad
    overlay (e.g. an auth lock-out) is rejected exactly like a bad env. Keys in
    ``SETTINGS_LOCKED_KEYS`` are ignored so they stay pinned to env/default."""
    base = Config()
    overrides = _load_db_overlay(base.SQLITE_PATH)
    if not overrides:
        return base
    locked = set(base.SETTINGS_LOCKED_KEYS)
    overrides = {
        k: v for k, v in overrides.items() if k in Config.model_fields and k not in locked
    }
    if not overrides:
        return base
    try:
        return Config(**overrides)
    except Exception as exc:
        # A hand-corrupted overlay must not brick the app on every get_config().
        # The validated settings-UI write path can't produce this; fall back to
        # env/defaults and carry on. (The UI re-validates, so it surfaces there.)
        import logging

        logging.getLogger("labeljetty.config").error(
            "Ignoring invalid settings overlay (%s): %s", sorted(overrides), exc
        )
        return base


def ui_field_meta() -> Dict[str, Dict[str, Any]]:
    """``{field_name: ui-metadata}`` for every field flagged editable via ``_ui``.
    Drives the settings page so it stays in sync with the model automatically."""
    out: Dict[str, Dict[str, Any]] = {}
    for name, field in Config.model_fields.items():
        extra = field.json_schema_extra
        ui = extra.get("ui") if isinstance(extra, dict) else None
        if ui and ui.get("editable"):
            out[name] = ui
    return out


def get_config() -> "Config":
    """Return the process-wide Config singleton (built on first use)."""
    global _config_singleton
    if _config_singleton is None:
        _config_singleton = build_config()
    return _config_singleton


def reload_config() -> "Config":
    """Rebuild config from sources and update the singleton *in place* so every
    module that captured ``get_config()`` sees the new values without re-import.

    Note: the print worker runs in a separate process and reloads on its own."""
    fresh = build_config()
    cfg = get_config()
    for name in Config.model_fields:
        setattr(cfg, name, getattr(fresh, name))
    return cfg
