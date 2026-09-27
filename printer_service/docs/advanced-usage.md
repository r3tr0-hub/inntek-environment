# Advanced usage

Everything beyond the [Setup guide](setup.md): setting up by hand, running without Docker,
authentication, the REST API, text auto-fit, and Homebox integration. Every setting is in
**[Configuration](configuration.md)**.

- [Manual Docker setup](#manual-docker-setup)
- [Running without Docker](#running-without-docker)
- [Authentication](#authentication)
- [The web UI](#the-web-ui)
- [The REST API](#the-rest-api)
- [Text rendering & auto-fit](#text-rendering--auto-fit)
- [Homebox integration](#homebox-integration)
- [Docker tags & architectures](#docker-tags--architectures)

## Manual Docker setup

The [one-line installer](../README.md#-install) does all of this for you - installs Docker,
detects the printer and writes the USB udev rule, drops a `docker-compose.yml`, and brings the
stack up - and is the recommended path. Do it by hand when you're **not on a Debian-based
host**, want to understand each piece, or are wiring LabelJetty into existing infrastructure.
(To run without Docker at all, see [Running without Docker](#running-without-docker).)

### Prepare the host

LabelJetty ships as a Docker image, so the only requirement is **Docker** with Compose
(`docker compose version` to check; [install docs](https://docs.docker.com/engine/install/)).
The image bundles everything else it needs (libusb, the DejaVu font).

### Find your printer

> **You can skip pinning a device.** Left unset, `PRINTER_USB` auto-detects a connected TSPL
> printer (it matches known vendors and generic USB printer-class devices): if exactly one is
> found it just works; if several are found it stops and lists them so you can pick one. You
> still need the **vendor:product id** for the udev rule below, so note it down either way.

Plug the printer in and list USB devices:

```sh
lsusb
```

Find your label printer, e.g.:

```
Bus 001 Device 015: ID 2d37:62de Zhuhai Poskey Technology Co.,Ltd 420B
```

The **vendor:product id** here is `2d37:62de`. To **pin** this exact device (instead of relying
on auto-detect - recommended if you have more than one USB printer), set
`PRINTER_USB=vid:2d37:pid:62de` below. This `vid:pid` form is the most robust selector because
it survives replugging; other forms are listed in
[Configuration](configuration.md#printer_usb-selector-forms).

To see exactly what auto-detect finds (as ready-to-paste selectors), run
`labeljetty-testbench list-printers`.

### Grant USB access

By default a normal user (and the container) cannot open the USB device, which fails with:

```
usb.core.USBError: [Errno 13] Access denied (insufficient permissions)
```

Fix it with a udev rule that gives the `plugdev` group access (most desktop users are already
in `plugdev` - check with `groups`). Replace the ids with **your** printer's:

```sh
sudo tee /etc/udev/rules.d/99-tspl-printer.rules >/dev/null <<'EOF'
# TSPL label printer - allow plugdev group to access it over raw USB
SUBSYSTEM=="usb", ATTRS{idVendor}=="2d37", ATTRS{idProduct}=="62de", MODE="0660", GROUP="plugdev"
EOF

# Reload rules and re-trigger (or just unplug/replug the printer)
sudo udevadm control --reload-rules
sudo udevadm trigger
```

If you are not in `plugdev`, add yourself and log out/in:

```sh
sudo usermod -aG plugdev "$USER"
```

This rule lives on the **host** and governs the device for Docker too: passing the USB bus into
the container only forwards the device, the host still controls its permissions.

> Just want a one-off local test without the rule? Run the command with `sudo` (e.g.
> `sudo uv run labeljetty-testbench status`). The udev rule is the proper, persistent solution
> for an always-on box.

### Run with Docker Compose

A ready-made [`docker-compose.yml`](../docker-compose.yml) is in the repo. The minimal form:

```yaml
services:
  labeljetty:
    image: motey/labeljetty:latest
    restart: unless-stopped
    ports:
      - "8888:8888"
    device_cgroup_rules:
      - "c 189:* rmw"                  # allow all USB device nodes (survives replug)
    environment:
      PRINTER_USB: vid:2d37:pid:62de   # from "Find your printer"; omit to auto-detect
    volumes:
      - ./data:/data                   # persists the job DB + stored images
      - /dev/bus/usb:/dev/bus/usb      # the printer's USB bus (live, so replugs appear)
```

> **Why a bind mount and not `devices:`?** A `devices: /dev/bus/usb:/dev/bus/usb` mapping binds the
> device node that exists at `up` time. Unplug and replug the printer and the kernel gives it a new
> node (e.g. `001/015` → `001/016`); the container is still pointed at the old, dead one and stops
> seeing the printer until you recreate it. Bind-mounting `/dev/bus/usb` plus the `c 189:* rmw`
> cgroup rule (which permits the whole USB device major) lets the new node appear live instead.

```sh
docker compose up -d
```

Then open **http://localhost:8888/** and [verify](setup.md#3-verify) with the alignment pattern.
Match your label stock by also setting `DEFAULT_LABEL_WIDTH_MM` / `DEFAULT_LABEL_HEIGHT_MM` /
`DEFAULT_DPI`; every other setting is optional and documented in
[Configuration](configuration.md).

## Running without Docker

`labeljetty` ships as a PyPI package and as a source checkout. Both give you the same three
console commands:

| Command | What it does |
| --- | --- |
| `labeljetty` | Runs the service - REST API + web UI + background print worker. |
| `labeljetty-testbench` | CLI for driving the printer library directly (see [Developing](developing.md#real-world-print-tests-with-the-testbench)). |
| `labeljetty-hash-password` | Generates a password hash for a login user. |

### Requirements

- **Python 3.11+**
- [`uv`](https://docs.astral.sh/uv/) for dependency / virtualenv management (recommended)
- **libusb** (usually already present on Linux; `pyusb` talks to it)
- **DejaVu Sans** font for text/markdown rendering (present on most Linux desktops; on a bare
  server: `sudo apt-get install -y fonts-dejavu-core`)
- A USB **TSPL** label printer

### From PyPI

```sh
pip install labeljetty
# or, with uv:
uv tool install labeljetty
```

You still need a `.env` (or env vars) and a printer set up - see
[Configuration](configuration.md). Then run `labeljetty`.

### From source

The project uses `uv`. From the repository root:

```sh
# Install uv if you don't have it
curl -fsSL https://astral.sh/uv/install.sh | sh

# Create the virtualenv and install all dependencies (editable)
uv sync
```

`uv run ...` automatically uses the project's virtualenv - you never activate it manually:

```sh
uv run labeljetty
```

The service starts the REST API, the web UI, and the background print worker on
`http://localhost:8888/` by default.

> **Working directory matters.** `SQLITE_PATH` and `IMAGE_STORAGE_DIRECTORY` are resolved
> **relative to the current working directory**. Run from the repository root each time, or set
> absolute paths in `.env`.

## Authentication

> ### ⚠️ The default is NO authentication
>
> With `AUTH_MODE=open` (the default) **every endpoint and the whole web UI are public** -
> anyone who can reach the host can print, browse the queue, and read printer status. That's
> intentional for a single printer on a **trusted home LAN**, but **do not expose open mode**
> to the internet or an untrusted network. Set `AUTH_MODE=protected` (below) or put the
> service behind your own reverse-proxy auth / VPN first.

There are two modes, selected by `AUTH_MODE`:

- **`open`** (default) - no authentication. LAN-only convenience.
- **`protected`** - every API and UI route requires a valid credential. Multiple credential
  **providers** can be active at once; any one of them satisfies a request:
  - **API tokens** (`AUTH_TOKENS`) - for machines/scripts. Sent as `Authorization: Bearer <token>`.
  - **Local users** (`AUTH_USERS`) - for humans. They log in at `/login`; a signed session
    cookie keeps them authenticated. (Browsers hitting a protected route while logged out are
    redirected to `/login`; API clients receive `401`.)

> The auth layer is built around a pluggable provider model and a `Principal` identity, so
> **OIDC / SSO is planned as a drop-in third provider** without changing any routes.

### Protected setup

> **From the browser (no env editing).** If you enable the [settings page](configuration.md#settings-via-the-web-ui)
> (`SETTINGS_UI_ENABLED=true`), you can add login users and switch *Authentication mode* to
> `protected` directly under **Settings → Authentication** — passwords are hashed for you, so the
> `labeljetty-hash-password` step below isn't needed. API tokens and `SESSION_SECRET` still come
> from the environment. The rest of this section is the equivalent env-var setup.

Generate a password hash for a login user (never store plaintext):

```sh
docker compose exec labeljetty labeljetty-hash-password
# → pbkdf2_sha256$600000$...$...
```

<details>
<summary>Not using Compose? - docker / uv / python</summary>

```sh
# docker
docker exec labeljetty labeljetty-hash-password

# uv (from a source checkout)
uv run labeljetty-hash-password

# python (venv with `pip install labeljetty`)
python -m labeljetty.web.password
```

</details>

Then put the hash, tokens and a stable session secret in your config (these are env vars -
set them in the Compose `environment:` block, or a `.env` file outside Docker):

```sh
AUTH_MODE=protected
AUTH_TOKENS=[{"name":"ci","token":"choose-a-long-random-secret"}]
AUTH_USERS=[{"username":"tim","password_hash":"pbkdf2_sha256$600000$...$..."}]
SESSION_SECRET=another-long-random-string   # so logins survive restarts
```

If `AUTH_MODE=protected` but neither tokens nor users are configured, startup fails fast
(otherwise you'd lock yourself out). If `SESSION_SECRET` is unset, an ephemeral one is used and
logins reset on restart (a warning is logged).

## The web UI

Open `http://<host>:<port>/` for the mobile-first UI. It covers everything the API does, plus:

- **Label profiles** - named sizes from `LABEL_PROFILES`, so you pick "Homebox" instead of
  retyping 57×32 mm.
- **Live preview** - render the label bitmap and see it before you print, saving wasted stock.
- **Live status** - the job queue and the printer/worker status poll and update in place.
- **Settings page** (optional, `SETTINGS_UI_ENABLED=true`) - edit the operational settings at
  runtime without touching env/compose: label defaults and profiles (a row editor, no JSON), a
  USB printer picker, the Homebox connection, retention, log level, and login users / auth mode.
  See [Settings via the web UI](configuration.md#settings-via-the-web-ui).

## The REST API

> **Interactive API docs.** The running service serves live, auto-generated API docs - the
> quickest way to explore and try every endpoint:
> | URL | What it is |
> | --- | --- |
> | [`/docs`](http://localhost:8888/docs) | **Swagger UI** - browse and run requests in the browser |
> | [`/redoc`](http://localhost:8888/redoc) | ReDoc - a clean, readable reference view |
> | [`/openapi.json`](http://localhost:8888/openapi.json) | the raw OpenAPI schema (for codegen / Postman / etc.) |
>
> (In `protected` mode these are behind auth, like every other route.)

All routes are under the `/api` prefix. In `protected` mode, send an API token as
`-H "Authorization: Bearer <token>"` (see [Authentication](#authentication)).

| Method & path | Body | Purpose |
| --- | --- | --- |
| `POST /api/print/png` | multipart `file=@label.png` | Enqueue a PNG print |
| `POST /api/print/pdf` | multipart `file=@doc.pdf`, `page` | Enqueue a PDF print (page or `all`) |
| `POST /api/print/text` | JSON `{"text": "..."}` (optional `font_size`, `fit`; auto-fits if omitted) | Enqueue plain text |
| `POST /api/print/markdown` | JSON `{"text": "# Hi\n* a"}` | Enqueue basic markdown |
| `POST /api/print/barcode` | JSON `{"data": "123", "barcode_type": "128", "text": "..."}` | Enqueue a barcode |
| `POST /api/print/qrcode` | JSON `{"data": "https://...", "ecc_level": "M", "text": "..."}` | Enqueue a QR code |
| `GET  /api/jobs` | `?limit=100` | List recent jobs + their status |
| `GET  /api/jobs/{job_id}` | - | Status of a single job |
| `GET  /api/worker/status` | - | Background worker health |
| `GET  /api/printer/status` | - | `{reachable, status_supported, status}`; `503` only if the device can't be opened |
| `GET  /api/printer/info` | - | USB facts about the selected printer (`selector`, `vendor_id`/`product_id`, `serial`, `port_path`, `autodetected`, …); `503` if no printer resolves |
| `GET  /api/version` | - | The running service version |

All print endpoints also accept optional `label_width_mm`, `label_height_mm`, `dpi` and `copies`
to override the defaults per job. `/print/png` and `/print/pdf` additionally take `fit` - how the
image scales to the label: `fit` (contain, default), `fill` (cover/crop), `stretch` (exact size)
or `original` (keep the image's own size). Text and markdown use their own `fit` (`fill`/`width`);
see [Text rendering & auto-fit](#text-rendering--auto-fit).

Example:

```sh
BASE=http://127.0.0.1:8888/api

curl -s -X POST $BASE/print/text -H 'content-type: application/json' \
  -d '{"text":"hello label","copies":2}'
curl -s -X POST $BASE/print/png -F file=@tests/fixtures/label_test.png
curl -s "$BASE/jobs?limit=10"
curl -s $BASE/printer/status     # {reachable, status_supported, status}
```

## Text rendering & auto-fit

Plain-text and markdown labels **auto-scale to your label** by default - you don't have to guess
a font size for each stock. Markdown keeps headings proportionally larger (`#` = 2×, `##` = 1.5×
the body). Two things control sizing:

- **Fixed size** - pass an explicit font size (`--font-size` on the test bench, `font_size` in
  the `/print/text` body) to disable auto-fit and use that exact size.
- **Fit mode** (`fit`, default `fill`) - how auto-fit chooses the size:

  | `fit` | Behaviour |
  | --- | --- |
  | `fill` | Grow the text to fill the label (width **and** height), wrapping lines as needed. Maximises size; short text may wrap to use the vertical space (e.g. `Box 12` → two big lines). |
  | `width` | Size the text to the label **width**, keeping your line breaks (no extra wrapping); height may be left blank (e.g. `Box 12` stays one line). Falls back to `fill` if a line is too long to fit unwrapped. |

Examples:

```sh
# default (fill) - fills the whole label
docker compose exec labeljetty labeljetty-testbench text "Box 12"

# width - keep it on one line, sized to the label width
docker compose exec labeljetty labeljetty-testbench text "Box 12" --fit width

# fixed size, no auto-fit
docker compose exec labeljetty labeljetty-testbench text "Box 12" --font-size 40
```

<details>
<summary>Not using Compose? - docker / uv / python</summary>

```sh
# docker (swap `docker compose exec labeljetty` for `docker exec labeljetty`)
docker exec labeljetty labeljetty-testbench text "Box 12"
docker exec labeljetty labeljetty-testbench text "Box 12" --fit width
docker exec labeljetty labeljetty-testbench text "Box 12" --font-size 40

# uv (from a source checkout)
uv run labeljetty-testbench text "Box 12"
uv run labeljetty-testbench text "Box 12" --fit width
uv run labeljetty-testbench text "Box 12" --font-size 40

# python (venv with `pip install labeljetty`)
python -m labeljetty.testbench text "Box 12"
python -m labeljetty.testbench text "Box 12" --fit width
python -m labeljetty.testbench text "Box 12" --font-size 40
```

</details>

The same label via the REST API (works the same with or without Docker, it's an HTTP call):

```sh
curl -s -X POST $BASE/print/text -H 'content-type: application/json' \
  -d '{"text":"Box 12", "fit":"width"}'
```

## Homebox integration

[Homebox](https://github.com/sysadminsmedia/homebox) integration is a **self-contained, optional
module**. The printer service works fully on its own; set `HOMEBOX_URL` + `HOMEBOX_API_KEY` and a
**Homebox** section appears in the web UI. With nothing configured, there is no trace of Homebox
in the app.

> Targets **Homebox v0.26.0+**, where items and locations were merged into a single **entity**
> model (`/v1/entities`). The API key is a static `hb_...` key sent as a bearer token; the Homebox
> admin must have set `HBOX_AUTH_API_KEY_PEPPER` (≥32 chars) for keys to work.

There are three ways to connect the two systems:

### A. Pull - the in-app module

The UI's Homebox section lets you **search items and locations**, pick one, preview, and print.
The label printed is **Homebox's own label**, fetched from its labelmaker API
(`/v1/labelmaker/{item,location,asset}/{id}`) and printed by us - so there's a single source of
label rendering (Homebox's, controlled by its `HBOX_LABEL_MAKER_*` sizing) rather than a second
renderer to maintain. Just set `HOMEBOX_URL` + `HOMEBOX_API_KEY`.

### B. Push - external label service

Homebox can delegate label *rendering* to an HTTP service via
`HBOX_LABEL_MAKER_LABEL_SERVICE_URL`. We expose exactly such an endpoint (`/api/homebox/label`):
it renders the label with **our** engine (tuned to your stock) and **enqueues the print as a side
effect**, then returns the image to Homebox. One mechanism renders *and* prints, with no script
on the Homebox host - point `HBOX_LABEL_MAKER_LABEL_SERVICE_URL` at our endpoint.

### C. Print command - fallback

Homebox's per-entity print action renders a `label.png` server-side and runs a configured command
(`HBOX_LABEL_MAKER_PRINT_COMMAND`) with a `{{.FileName}}` placeholder. The setup wizard at
`/ui/homebox/setup` generates a ready-to-paste script that `curl`s the file to `/api/print/png`,
plus the `HBOX_LABEL_MAKER_*` env-var hints (sized in pixels) to match your label stock. Prefer
this when you want Homebox's *native* label layout and "print means print" semantics with our
service as a non-critical dependency.

## Docker tags & architectures

The image is published to Docker Hub as
[`motey/labeljetty`](https://hub.docker.com/r/motey/labeljetty).

### Image tags

| Tag | When it's pushed |
| --- | --- |
| `latest` | Every normal GitHub Release |
| `beta` | Every GitHub **pre-release** |
| `X.Y.Z` | Every release (the exact version) |
| `dev` | Every push to `main` (x86-only, bleeding edge) |

Pin `X.Y.Z` in production; use `beta` to try pre-releases. `dev` rebuilds on every commit to
`main` and is **`linux/amd64` only** (no Raspberry Pi) - for testing the latest code, not for
production.

### Supported architectures

The image is a multi-arch manifest, so `docker pull` picks the right one automatically:

| Architecture | Covers |
| --- | --- |
| `linux/amd64` | x86-64 PCs and servers |
| `linux/arm64` | Raspberry Pi **3 / 4 / 5 running a 64-bit OS** (Raspberry Pi OS 64-bit, Ubuntu) |

> **32-bit Raspberry Pi OS, Pi Zero / Zero 2 W, Pi 1 / 2** run on `arm/v7` (or `arm/v6`), which
> is **not** built - `docker pull` there fails with "no matching manifest". The simplest fix is
> to run a **64-bit Raspberry Pi OS** (the default download today) so the `arm64` image applies.
> If you genuinely need a 32-bit image, please **[open an issue](../../issues)** - we'll consider
> adding `linux/arm/v7` if there's interest.

Building the image locally (for hands-on testing) and the full release process are covered in
**[Build & release](BUILD.md)**.
