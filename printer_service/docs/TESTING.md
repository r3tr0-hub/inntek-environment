# Testing

This project ships an **automated test harness** that covers every layer of the
service - the TSPL command builder, headless rendering, the persistence layer,
the print-service worker, the Homebox client, and every REST API + web-UI
endpoint.

> **The one thing we never automate is real printing.** Driving physical
> hardware lives in the manual [`testbench`](#manual-hardware-testing) CLI.
> Everything else runs with no printer, no USB, and no network.

## TL;DR

```bash
# One-time: install the project + test tooling into the venv
uv sync --group dev

# Run the whole suite
uv run python -m pytest

# With coverage
uv run python -m pytest --cov=labeljetty --cov-report=term-missing
```

## Setup

The test dependencies (`pytest`, `pytest-cov`, `httpx`) live in the `dev`
[dependency group](https://docs.astral.sh/uv/concepts/projects/dependencies/#dependency-groups)
in `pyproject.toml`. Install them with:

```bash
uv sync --group dev
```

Rendering text and markdown labels needs the **DejaVu Sans** TrueType font
(`/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`, the library's
`DEFAULT_FONT_PATH`). It's present on most Linux desktops; on a bare server or
CI runner install it with:

```bash
sudo apt-get install -y fonts-dejavu-core      # Debian / Ubuntu
```

No `.env`, database, USB device, or Homebox server is required - see
[Isolation](#how-isolation-works).

## Running the tests

```bash
# Everything
uv run python -m pytest

# A single file / test
uv run python -m pytest tests/test_api.py
uv run python -m pytest tests/test_api.py::test_print_text_enqueues

# Keyword / quiet / last-failed-first
uv run python -m pytest -k homebox
uv run python -m pytest -q
uv run python -m pytest --lf

# Coverage (term + missing lines)
uv run python -m pytest --cov=labeljetty --cov-report=term-missing
```

Default options (in `[tool.pytest.ini_options]`): `-ra` (summarise non-passing
tests), `--strict-markers` (a typo'd marker is an error), and `-m "not
hardware"` (skip the manual hardware tests, see below).

## How isolation works

Several modules do real work **at import time** - every web/service module does
`config = Config()` (which reads `.env` from the working directory), and
`labeljetty.core.db` builds its global SQLAlchemy engine from
`config.SQLITE_PATH` the moment it is imported. The repo's real `.env` points at
a live printer and carries real Homebox credentials, so a naive test run would
read production config and scribble in `./printjobs.sqlite`.

`tests/conftest.py` prevents all of that. **Before any `labeljetty` import**, at
conftest module load (which pytest runs before collecting any test), it sets
environment variables that redirect the config at a throwaway temp directory:

| Env var | Test value | Why |
|---|---|---|
| `LABELJETTY_DOT_ENV_FILE` | a nonexistent path | ignore the real `.env` |
| `PRINTER_USB` | `vid:0000:pid:0000` | required field; never matches real hardware |
| `SQLITE_PATH` | temp file | never touch `./printjobs.sqlite` |
| `IMAGE_STORAGE_DIRECTORY` | temp dir | uploads land in a sandbox |
| `DEFAULT_LABEL_*` / `DEFAULT_DPI` | 57×32mm @ 203dpi | deterministic render assertions |
| `SESSION_SECRET` | fixed string | reproducible login/session tests |
| `HOMEBOX_*` / `AUTH_MODE` | disabled / `open` | features opt-in per test |

Nothing in the suite opens a USB device or makes a network call:

- **Rendering** runs through the library's `dry_run_mode` / connection-less path.
- **The printer** is replaced by `FakeConnection` (a fixture), which records the
  TSPL bytes it would send and returns a configurable status byte - so the real
  `TSPLPrinter` status/print code path is exercised without hardware.
- **USB discovery** (`usb.core.find`) is monkeypatched with fake devices.
- **Homebox HTTP** (`urllib`) is monkeypatched; the UI tests swap in a fake
  `HomeboxClient`.
- **The print worker subprocess is never spawned** - the app is built directly
  (the worker start callback is only wired in `labeljetty.app.run`, which tests
  don't call). Endpoints that require a "running" worker use the
  `worker_running` fixture, which writes a `WorkerStatus` row pointing at the
  (alive) test process.

The temp tree is removed in `pytest_sessionfinish`.

## Shared fixtures (`tests/conftest.py`)

| Fixture | What it gives you |
|---|---|
| `fresh_db` *(autouse)* | drops + recreates all tables before each test |
| `app` / `client` | a fresh FastAPI app and a `TestClient` (lifespan run) |
| `worker_running` | marks the worker "running" so enqueue endpoints proceed |
| `fake_connection` | a healthy `FakeConnection` (status byte `0x00`) |
| `patch_printer_connection` | makes `config.get_printer_connection()` return the fake |
| `make_job` | factory to insert a `PrintJob` row |
| `status_message` | factory for `TSPLPrinterStatusMessage` from a raw byte |
| `image_dir` | per-test temp image-storage dir |

`FakeConnection` is importable from `tests.conftest` for direct unit tests of
the TSPL layer.

## What's covered

| File | Layer under test |
|---|---|
| `test_config.py` | config validation, helpers, `PRINTER_USB` → connection dispatch |
| `test_status_message.py` | TSPL status-byte bit-flag decoding |
| `test_render.py` | headless rendering of every job type → label-sized 1-bit PNG |
| `test_tspl.py` | TSPL command stream (via `FakeConnection`), status, 1-bit prep |
| `test_connection.py` | USB device lookup + wire encoding (mocked `usb.core`) |
| `test_db.py` | `PrintJob` status machine, paths, JSON/status round-trip |
| `test_worker.py` | job dispatch, queue ordering, worker status, cleanup, print path |
| `test_homebox.py` | Homebox entity parsing + HTTP behavior (mocked `urllib`) |
| `test_api.py` | every REST endpoint, incl. auth enforcement & 503/404 paths |
| `test_ui.py` | web-UI routes: login flow, preview, enqueue, fragments, Homebox |
| `test_auth.py` | the `require_access` auth seam, providers, password hashing |

Deliberately **not** covered (cannot run without hardware or a subprocess, and
would only test the OS/libusb): the real USB read/write in `connection.py`, the
multiprocessing watchdog in `worker.py`, the uvicorn boot in `app.py`, and the
manual `testbench.py`.

## Manual hardware testing

Real printing is **never** part of the automated suite. To exercise a physical
printer use the testbench CLI, documented in
[Developing → Real-world print tests](developing.md#real-world-print-tests-with-the-testbench)
(dry-run, the test pattern, per-type renderers, status/probe).

If you add automated tests that *do* require a real printer, mark them
`@pytest.mark.hardware`. They are deselected by default (`-m "not hardware"`)
and must be run explicitly:

```bash
uv run python -m pytest -m hardware
```

## Continuous integration

`.github/workflows/tests.yml` runs the suite on every push and pull request,
against Python 3.11 and 3.12:

1. installs the DejaVu fonts (needed by the text renderer),
2. installs `uv` and the matching Python,
3. `uv sync --group dev`,
4. `uv run python -m pytest --cov=labeljetty --cov-report=term-missing`.

Because the harness is fully self-isolating, CI needs **no secrets, services,
or `.env`** - and the `hardware` marker keeps real-printer tests out of CI
automatically.

## Writing new tests

- Put new tests in `tests/`, named `test_*.py`. They inherit the isolation
  above automatically.
- For endpoint tests, use the `client` fixture; add `worker_running` if the
  route enqueues a job.
- To test printer behavior, use `FakeConnection` (or `patch_printer_connection`
  for endpoints) - **never** reach for a real device.
- Need a tweaked config? Build one with `Config(_env_file=None, PRINTER_USB=...,
  ...)` and `monkeypatch.setattr` it onto the module that reads it (e.g.
  `labeljetty.web.auth.config`). Note that `Config` is a pydantic model:
  settings *fields* can be `monkeypatch.setattr`'d on an instance, but *methods*
  (like `get_printer_connection`) must be patched on the `Config` class.
- Anything that would print, hit USB, or call Homebox over the network must be
  faked.
