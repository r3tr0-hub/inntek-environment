# Design

How **LabelJetty** is put together, what the moving parts are, and why it's built this way.

- [Goals](#goals)
- [Architecture](#architecture)
- [The layers](#the-layers)
- [The job model](#the-job-model)
- [Rendering](#rendering)
- [Authentication](#authentication)
- [Homebox integration](#homebox-integration)
- [Design principles & trade-offs](#design-principles--trade-offs)
- [Non-goals](#non-goals)

## Goals

There are two intertwined goals:

1. **Primary - Homebox label printing.** Make it trivial to print labels (QR code + item
   name / asset ID) for items in a self-hosted
   [Homebox](https://github.com/sysadminsmedia/homebox) inventory. This is the concrete itch why i build this.
2. **Side quest - a generic USB TSPL printer interface.** The Homebox use case sits on top of a
   general-purpose library + service that can drive *any* TSPL printer over USB and print PDFs,
   images, text, barcodes and QR codes. Useful on its own, independent of Homebox.

The development/reference hardware is a **Vretti 420B** (a Poskey-class USB TSPL printer,
~203 dpi, USB id `2d37:62de`).

## Architecture

Four layers, each depending only on the one below it, with the lowest dependency footprint
possible - we talk to the printer **directly over USB** rather than relying on CUPS or a vendor
driver.

```
┌────────────────────────────────────────────────────┐
│  Web UI (mobile + desktop)        REST API (tokens)  │  ← interface layer
├────────────────────────────────────────────────────┤
│  Print service: job queue (sqlite) + worker process  │  ← service layer
├────────────────────────────────────────────────────┤
│  TSPLPrinter library (render → TSPL commands)         │  ← library layer
├────────────────────────────────────────────────────┤
│  TSPLPrinterConnectionUSB (pyusb send/receive)        │  ← connection layer
└────────────────────────────────────────────────────┘
                         │ USB
                   ┌───────────┐
                   │  Printer  │
                   └───────────┘
```

This maps onto the package layout under [`src/labeljetty/`](../src/labeljetty):

| Subpackage | Layer | Responsibility |
| --- | --- | --- |
| [`printer/`](../src/labeljetty/printer) | connection + library | USB I/O, rendering, TSPL command generation. Zero internal deps - extractable as a standalone library. |
| [`core/`](../src/labeljetty/core) | persistence | SQLModel job/worker models, the SQLite engine, logging, custom SQL types. |
| [`service/`](../src/labeljetty/service) | service | the background worker that owns the printer and processes jobs. |
| [`integrations/`](../src/labeljetty/integrations) | integration | the Homebox client. |
| [`web/`](../src/labeljetty/web) | interface | FastAPI app, REST API, web UI (Jinja2 + HTMX), auth. |
| [`config.py`](../src/labeljetty/config.py) | - | one `Config` (pydantic-settings) read from `.env` / env vars, with an optional DB overlay edited via the [settings UI](configuration.md#settings-via-the-web-ui) layered on top (DB > env > default); sits at the package root on purpose - the first thing people look for. |

## The layers

### Connection layer - `printer/connection.py`

Raw USB endpoint I/O via `pyusb`/libusb: device discovery (the `PRINTER_USB` selector strategies
- `vid:pid`, `serial`, `port`, `path`, `bus:addr`), lazy connect + endpoint setup, and fast-fail
on `EACCES` with a hint pointing at the udev rule. No web or server concerns.

### Library layer - `printer/`

The only thing that knows TSPL. It converts PDFs / PNGs / text / markdown / barcodes / QR codes
into TSPL command streams and (where the printer supports it) parses status. Usable as a
standalone Python library: `from labeljetty.printer import TSPLPrinter`. A `dry_run` mode prints
the generated TSPL to stdout instead of sending it to the device, for development without
hardware.

`JobType` lives here too, so the printer package has **zero internal dependencies** and could be
lifted out into its own library.

### Service layer - `service/worker.py` + `core/db.py`

A persistent **job queue** (SQLite) decouples requests from the physical print and survives
restarts. A **single background worker** (multiprocessing + a watchdog with retry/backoff) owns
the printer and processes jobs one at a time, so concurrent web/API requests never collide on the
one physical device. The worker persists each job's lifecycle: queued → started → finished, plus
final printer status and any error. Old jobs and their files are cleaned up after
`DELETE_OLD_JOBS_AFTER_DAYS`.

### Interface layer - `web/`

A FastAPI app exposing the [REST API](advanced-usage.md#the-rest-api) (for machines) and a
mobile-first [web UI](advanced-usage.md#the-web-ui) (for humans) built with Jinja2 templates +
HTMX - no front-end build step, served directly by FastAPI from `templates/` and `static/`. Both
the UI and API enqueue jobs through the same service layer, so they're always at feature parity.

## The job model

`PrintJob` ([`core/db.py`](../src/labeljetty/core/db.py)) is deliberately generic so one model
and one worker dispatch loop cover every payload type:

- `job_type` - one of `png` / `pdf` / `text` / `markdown` / `barcode` / `qrcode`.
- `params` - a JSON dict (stored via a custom `SqlJsonText` type) carrying the per-type
  parameters (e.g. the text and fit mode, the barcode type, the QR ECC level).
- optional `input_file_name` - for the file-based types (PNG/PDF).
- per-job `label_width_mm` / `label_height_mm` / `dpi` / `copies` - overriding the
  `DEFAULT_LABEL_*` config when set.

Sessions use `expire_on_commit=False` and the worker persists detached jobs via `session.merge`,
so a job object stays usable across the request/worker boundary.

## Rendering

Everything ends up as a 1-bit bitmap printed through a shared `_render_and_print_image` path:
dither → pad width to a multiple of 8 → emit `SIZE` / `CLS` / `BITMAP` / `PRINT`.

- **PDF** is rendered with [`pypdfium2`](https://github.com/pypdfium2-team/pypdfium2) - no system
  dependencies.
- **QR codes** are rendered to a bitmap with [`segno`](https://github.com/heuer/segno), scaled to
  fill the label and centered (optionally with an auto-sized caption) - also zero system deps.
- **Barcodes** use `python-barcode` (Code128, EAN, UPC, Code39, ...).
- **Text & markdown** auto-fit to the label by default (see
  [auto-fit](advanced-usage.md#text-rendering--auto-fit)); markdown keeps `#`/`##` headings
  proportionally larger.

Picking pure-wheel libraries for PDF and QR keeps the "minimal dependency" promise - the whole
thing installs and runs on a Raspberry Pi without dragging in a system print stack.

## Authentication

Auth is off by default (`AUTH_MODE=open`) for trusted-LAN convenience and on-demand
(`protected`). The design is a **pluggable provider model** behind a single seam,
`web/auth.py::require_access`, which returns a `Principal` (subject / kind / display name /
claims) rather than a bare boolean. Two providers ship today and can be active at once:

- `TokenAuthenticator` - multi-token `AUTH_TOKENS`, `Authorization: Bearer`, constant-time
  comparison.
- `SessionAuthenticator` - multi-user `AUTH_USERS`, a `/login` form, and a signed cookie via
  Starlette's `SessionMiddleware`. Passwords are stdlib pbkdf2_sha256
  ([`web/password.py`](../src/labeljetty/web/password.py) + the `labeljetty-hash-password` CLI).

Returning a `Principal` and centralising the check makes the layer **OIDC-ready**: OIDC slots in
as a third provider reusing the same session, with no route changes. Browsers (Accept:
text/html) get a `303 → /login`; API clients get `401`. The lock-out guard (`protected` with no
providers is rejected) runs as a model validator, so it protects edits from the
[settings UI](configuration.md#settings-via-the-web-ui) — where login users and `AUTH_MODE` can be
managed — exactly as it does at startup. `require_access` rebuilds the providers from the live
config per request, so such changes take effect without a restart.

See [Advanced usage → Authentication](advanced-usage.md#authentication) for configuration.

## Homebox integration

A **self-contained, optional module**, config-gated on `HOMEBOX_URL` + `HOMEBOX_API_KEY`. With
nothing set, there is no trace of Homebox in the app - this keeps the generic-printer side-quest
cleanly separable from the primary goal.

It targets **Homebox v0.26.0+**, where items and locations merged into a single **entity** model
(`/v1/entities`; the old `/v1/items*` and `/v1/locations*` are gone). Three connection paths
(pull / push / print-command) are documented in
[Advanced usage → Homebox integration](advanced-usage.md#homebox-integration). The key design
decision: the in-app *pull* path prints **Homebox's own label** (fetched from its labelmaker API),
so there is one source of label rendering controlled by Homebox's `HBOX_LABEL_MAKER_*` sizing,
rather than a second renderer to keep in sync.

## Design principles & trade-offs

- **No CUPS, no vendor driver.** A single thermal printer doesn't need a spooler, PPDs, and a
  print queue. Talking TSPL directly over USB is simpler to reason about and behaves identically
  on every host.
- **Lowest dependency cost possible.** Pure-wheel libraries everywhere (`pypdfium2`, `segno`,
  `pillow`, `python-barcode`); the only system libs are libusb and a TrueType font. Runs happily
  on a Pi.
- **Generic core, optional integrations.** The printer service knows nothing about Homebox;
  Homebox is a module that appears only when configured.
- **One worker, one printer.** A single physical device is serialised behind a queue + worker, so
  the concurrency story is trivial and correct. (Multi-printer is a possible future, not a current
  target.)
- **Status degrades gracefully.** Many cheap clones are write-only for status; the code treats an
  unreadable status as "ready" and never blocks printing on it.
- **Extractable printer library.** `printer/` has zero internal dependencies by design, so it can
  become a standalone package if that's ever useful.

## Non-goals

- Replacing CUPS or being a full print spooler.
- Supporting non-TSPL printer languages (ZPL/EPL) - could be a future abstraction, not a current
  target.
- Cloud / multi-tenant hosting; this is a single-LAN, single-printer appliance.

Stretch ideas that might relax some of these (raw port-9100 socket, a label template library,
multi-printer) are tracked in the [Roadmap](roadmap.md#possible--under-consideration).
