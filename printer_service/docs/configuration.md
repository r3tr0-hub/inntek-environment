# Configuration

Every setting is read from an environment variable, or from a `.env` file (see
[`sample.env`](../sample.env) for a documented template). Under Docker, set them in the
Compose `environment:` block, pass `-e KEY=value`, or mount a file with `--env-file .env`.

> **First time?** The [Setup guide](setup.md) walks you through the printer, the host, and
> running the service end to end. This page is the settings reference behind it.

- [What you must / should set](#what-you-must--should-set)
- [`PRINTER_USB` selector forms](#printer_usb-selector-forms)
- [Full reference](#full-reference)
- [Settings via the web UI](#settings-via-the-web-ui)
- [Status reading is optional](#status-reading-is-optional)

## What you must / should set

Nothing is strictly required - an unset `PRINTER_USB` auto-detects the printer - but you
should set it (and review auth) for a stable, secure deployment.

| Priority | Variables | Why |
| --- | --- | --- |
| **Should set (recommended)** | `PRINTER_USB` | Left unset, LabelJetty auto-detects a connected TSPL printer; pin it so the right device is always used (and to get a clear error rather than a scan). See [Find your printer](advanced-usage.md#find-your-printer). |
| **Should set (when exposed beyond a trusted LAN)** | `AUTH_MODE=protected` + `AUTH_TOKENS` and/or `AUTH_USERS`, plus a stable `SESSION_SECRET` | The default is **no authentication**. See [Authentication](advanced-usage.md#authentication). |
| **Should set (for your label stock)** | `DEFAULT_LABEL_WIDTH_MM`, `DEFAULT_LABEL_HEIGHT_MM`, `DEFAULT_DPI` | So jobs that don't specify a size match your actual labels. Add `LABEL_PROFILES` for one-click sizes in the UI. |
| **Should set (outside Docker)** | absolute `SQLITE_PATH` and `IMAGE_STORAGE_DIRECTORY` | They resolve relative to the working directory; absolute paths avoid surprises. The Docker image already points both at `/data`. |
| **Optional** | `HOMEBOX_*`, `SERVER_LISTENING_*`, `DELETE_OLD_JOBS_AFTER_DAYS`, `LOG_*` | Sensible defaults; set only if you need them. `HOMEBOX_*` enables the [Homebox module](advanced-usage.md#homebox-integration). |

## `PRINTER_USB` selector forms

`PRINTER_USB` selects which USB device is the printer. **Leave it unset to auto-detect**
a connected TSPL printer (matches known vendors and USB printer-class devices) - LabelJetty
uses it when exactly one is found, and lists candidates if several are. To pin a specific
device, the most robust form is **vendor:product id** (read off `lsusb`, see
[Find your printer](advanced-usage.md#find-your-printer)), because - unlike a bus/address - it
survives replugging:

```sh
PRINTER_USB=vid:2d37:pid:62de
```

| Form | Example | Notes |
| --- | --- | --- |
| Vendor + product id | `vid:2d37:pid:62de` | **Recommended** - stable across replug |
| Vendor id only (first match) | `vid:2d37` | If you only have one matching device |
| Serial number | `serial:ABC123456` | If the printer exposes a serial |
| USB port path | `port:3-1-2` | Stable per physical port |
| Device path | `path:/dev/bus/usb/001/015` | Changes on replug |
| Bus + address | `bus:1:addr:15` | Changes on replug |

> **USB auto-discovery** detects common printers without setting `PRINTER_USB` by hand -
> just leave it unset. Run `labeljetty-testbench list-printers` to see what it finds.

## Full reference

| Variable | Default | Description |
| --- | --- | --- |
| `PRINTER_USB` | *(unset → auto-detect)* | Which USB printer to use; unset auto-detects (see [forms above](#printer_usb-selector-forms)) |
| `SERVER_LISTENING_HOST` | `localhost` | API bind host (use `0.0.0.0` to expose on the LAN) |
| `SERVER_LISTENING_PORT` | `8888` | API port |
| `AUTH_MODE` | `open` | `open` (no auth) or `protected` - see [Authentication](advanced-usage.md#authentication) |
| `AUTH_TOKENS` | `[]` | JSON list of API tokens for machines, e.g. `[{"name":"ci","token":"..."}]` |
| `AUTH_USERS` | `[]` | JSON list of login users, e.g. `[{"username":"tim","password_hash":"pbkdf2_sha256$..."}]` |
| `SESSION_SECRET` | *(ephemeral)* | Secret signing session cookies; set a stable value so logins survive restarts |
| `SESSION_COOKIE_NAME` | `labeljetty_session` | Name of the session cookie |
| `SESSION_MAX_AGE` | `1209600` | Session lifetime in seconds (default 14 days) |
| `SQLITE_PATH` | `./printjobs.sqlite` | Job-queue database (relative to the working directory) |
| `IMAGE_STORAGE_DIRECTORY` | `./../images` | Where uploaded files are stored (relative to cwd) |
| `DELETE_OLD_JOBS_AFTER_DAYS` | `100` | Retention for old jobs and their files |
| `UPDATE_CHECK_ENABLED` | `true` | Show an "update available" banner by checking GitHub for a newer release (one cached outbound call). Set `false` for offline deployments. See [Updating](updating.md). |
| `UPDATE_CHECK_REPO` | `motey/LabelJetty` | GitHub `owner/repo` queried for the latest release (set this on a fork) |
| `DEFAULT_LABEL_WIDTH_MM` | `100` | Default label width when a job doesn't specify one |
| `DEFAULT_LABEL_HEIGHT_MM` | `30` | Default label height |
| `DEFAULT_DPI` | `203` | Default printer resolution |
| `LABEL_PROFILES` | `[]` | Named label sizes for the UI, e.g. `[{"name":"Homebox","width_mm":57,"height_mm":32}]` |
| `HOMEBOX_ENABLED` | `false` | Enable the Homebox module (also needs `HOMEBOX_URL` + `HOMEBOX_API_KEY`) |
| `HOMEBOX_URL` | *(unset)* | Base URL of your Homebox server (v0.26+, entity-merged API) |
| `HOMEBOX_API_KEY` | *(unset)* | Homebox API key (`hb_...`) for entity search and labelmaker |
| `HOMEBOX_API_PREFIX` | `/api/v1` | API path prefix on the Homebox server |
| `HOMEBOX_ENTITY_URL_TEMPLATE` | `/item/{id}` | Web path an entity opens at (for the "open in Homebox" link) |
| `HOMEBOX_LABEL_SERVICE_AUTOPRINT` | `true` | Also enqueue the print when Homebox calls our label-service endpoint |
| `SETTINGS_UI_ENABLED` | `false` | Enable the in-app settings page (`/ui/settings`) to edit the operational settings below at runtime. See [Settings via the web UI](#settings-via-the-web-ui). |
| `SETTINGS_LOCKED_KEYS` | `[]` | JSON list of field names pinned to their env value — shown read-only in the settings page and never taken from the DB, e.g. `["HOMEBOX_URL","LOG_LEVEL"]` |
| `APP_NAME` | `LabelJetty` | Display name shown in the UI and logs |
| `LOG_LEVEL` | `DEBUG` | `CRITICAL`/`ERROR`/`WARNING`/`INFO`/`DEBUG` |
| `LOG_DISABLE_COLORS` | `false` | Disable ANSI colours (useful when logging to a file/journal) |
| `UVICORN_LOG_LEVEL` | *(= `LOG_LEVEL`)* | Web-server log level |

> **Note:** `SQLITE_PATH` and `IMAGE_STORAGE_DIRECTORY` resolve **relative to the current
> working directory**. Run the service from the same directory each time, or set absolute
> paths. The Docker image already sets both to `/data`. A non-standard override,
> `LABELJETTY_DOT_ENV_FILE`, points at a different `.env` path (used by the test harness to
> ignore the real one).

## Settings via the web UI

Setting `SETTINGS_UI_ENABLED=true` exposes a **Settings** page at `/ui/settings` (linked
from the header) that edits the operational settings — label defaults and profiles, the
printer selector, the Homebox connection, job retention, and log level — **without editing
env vars or restarting**. This is what makes the prepared Raspberry Pi image practical: ship
sane env defaults, then adjust from the browser.

- **Precedence:** an edit saved in the UI is stored in the database and **overrides the
  environment variable** for that setting (UI&nbsp;>&nbsp;env/`.env`&nbsp;>&nbsp;default). The
  page form is generated automatically from the settings model, so it stays in sync.
- **What's editable:** an operational allowlist — label defaults/profiles, printer selector,
  Homebox connection, job retention, log level, plus **authentication mode and login users**
  (`AUTH_MODE` / `AUTH_USERS`), so you can secure the interface without editing env/compose.
  Passwords are entered in the form, **hashed server-side**, and only the hash is stored; leave
  a user's password blank to keep it. Raw secrets (`HOMEBOX_API_KEY`, `SESSION_SECRET`,
  `AUTH_TOKENS`) and infrastructure (`SQLITE_PATH`, `SERVER_LISTENING_*`) stay env-only — the
  latter shown read-only under *System info*. A few values (e.g. `LOG_LEVEL`) are marked ↻ and
  only take effect after a restart.

> **Securing the printer from the UI:** add a login user, switch *Authentication mode* to
> `protected`, and Save. The lock-out guard refuses `protected` with no users/tokens, so a bad
> save is rejected rather than locking you out — but make sure your new login works, and set a
> stable `SESSION_SECRET` (env) so sessions survive restarts.
- **Pinning:** list field names in `SETTINGS_LOCKED_KEYS` to force them to their env value —
  they render read-only and ignore any stored override (useful for managed/Pi deployments).
- **Reverting:** *Reset to env/defaults* clears all stored overrides.

> **Security:** the page is **off by default**. Enabling it in `AUTH_MODE=open` means anyone
> who can reach the box can change configuration (the page warns you). Pair it with
> `AUTH_MODE=protected`.

## Status reading is optional

Many cheap TSPL printers (Xprinter / Poskey-class clones, including the reference Vretti
420B) have an effectively **write-only USB interface**: they print fine but never answer
status queries. On such a printer `testbench status` prints *"status: not available"* and
the API's `/printer/status` returns `status_supported: false`. **This does not affect
printing** - the service treats an unreadable status as "ready" and prints anyway. You only
get live status (ready / paper out / head open / ...) on printers that implement it. Use
`testbench probe` to check whether yours does.
