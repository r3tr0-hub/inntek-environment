"""Shared test fixtures and — crucially — import-time isolation.

Several ``labeljetty`` modules do real work *at import time*:

* every web/service module instantiates ``config = Config()`` (which reads
  ``.env`` from the current working directory), and
* :mod:`labeljetty.core.db` creates a global SQLAlchemy ``engine`` from
  ``config.SQLITE_PATH`` the moment it is imported.

The repo's real ``.env`` points at a real printer and carries live Homebox
credentials. So before *anything* from the package is imported, we redirect the
config at a throwaway temp directory and a nonexistent ``.env``. This block runs
at conftest import — which pytest loads before collecting any test module — so
the global engine and every module-level ``Config()`` pick up the test values.

Nothing here talks to USB or the network: rendering runs headless
(``dry_run_mode``), and the printer/Homebox seams are faked per-test.
"""

import os
import shutil
import tempfile

# --------------------------------------------------------------------------- #
#  Import-time isolation — MUST run before importing labeljetty.*
# --------------------------------------------------------------------------- #
_TMP_ROOT = tempfile.mkdtemp(prefix="labeljetty-tests-")

os.environ.update(
    {
        # Ignore the repo's real .env entirely (point at a path that doesn't exist).
        "LABELJETTY_DOT_ENV_FILE": os.path.join(_TMP_ROOT, "nonexistent.env"),
        # Required field — a dummy USB id that never matches real hardware.
        "PRINTER_USB": "vid:0000:pid:0000",
        # Throwaway sqlite DB + image storage so we never touch ./printjobs.sqlite.
        "SQLITE_PATH": os.path.join(_TMP_ROOT, "test_jobs.sqlite"),
        "IMAGE_STORAGE_DIRECTORY": os.path.join(_TMP_ROOT, "images"),
        # Deterministic label geometry for rendering assertions.
        "DEFAULT_LABEL_WIDTH_MM": "57",
        "DEFAULT_LABEL_HEIGHT_MM": "32",
        "DEFAULT_DPI": "203",
        # Stable session secret so login/session tests are reproducible.
        "SESSION_SECRET": "test-secret-not-for-production",
        # Homebox off by default; tests that need it opt in via fixtures.
        "HOMEBOX_ENABLED": "false",
        "AUTH_MODE": "open",
    }
)
# Clear any inherited Homebox creds so homebox_configured() is False by default.
os.environ.pop("HOMEBOX_URL", None)
os.environ.pop("HOMEBOX_API_KEY", None)

import os as _os  # noqa: E402  (after env setup, intentionally)

import pytest  # noqa: E402

# Safe to import now: the config reads the test environment set above.
from labeljetty.core import db  # noqa: E402
from labeljetty.core.db import PrintJob, WorkerStatus  # noqa: E402
from labeljetty.printer.tspl import TSPLPrinterStatusMessage  # noqa: E402


def pytest_sessionfinish(session, exitstatus):
    """Remove the throwaway temp tree after the run."""
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)


# --------------------------------------------------------------------------- #
#  Database isolation — fresh tables per test
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def fresh_db():
    """Drop & recreate all tables before each test for a clean slate."""
    from sqlmodel import SQLModel

    SQLModel.metadata.drop_all(db.engine)
    SQLModel.metadata.create_all(db.engine)
    yield
    SQLModel.metadata.drop_all(db.engine)


@pytest.fixture
def image_dir(tmp_path, monkeypatch):
    """Point IMAGE_STORAGE_DIRECTORY at a per-test temp dir on every module's config."""
    target = tmp_path / "images"
    target.mkdir()
    for mod in ("labeljetty.web.api", "labeljetty.web.ui", "labeljetty.core.db",
                "labeljetty.service.worker"):
        import importlib
        m = importlib.import_module(mod)
        if hasattr(m, "config"):
            monkeypatch.setattr(m.config, "IMAGE_STORAGE_DIRECTORY", str(target))
    return target


# --------------------------------------------------------------------------- #
#  Worker / printer seams (no hardware, no subprocess)
# --------------------------------------------------------------------------- #
@pytest.fixture
def worker_running():
    """Insert a WorkerStatus row pointing at THIS (alive) process.

    ``get_worker_status`` checks the pid with psutil; the test process is alive
    and not a zombie, so the worker reports "running" — letting enqueue
    endpoints proceed without spawning the real print subprocess.
    """
    with db.get_session() as session:
        session.merge(WorkerStatus(id=1, process_id=_os.getpid(), worker_error=None))
    yield


class FakeConnection:
    """Stand-in for :class:`TSPLPrinterConnectionUSB` — records writes, never USB.

    ``query`` returns a configurable status byte so the real ``TSPLPrinter``
    status path can be exercised end-to-end without hardware.
    """

    def __init__(self, status_byte: int = 0):
        self.status_byte = status_byte
        self.sent: list = []
        self.connected = False

    # lifecycle
    def connect(self, max_retries: int = 5) -> bool:
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.connected = False

    # io
    def send(self, data, raw: bool = False) -> None:
        self.sent.append(data)

    def send_many(self, data, raw: bool = False) -> None:
        self.sent.extend(data)

    def query(self, cmd, timeout: int = 1000, max_length: int = 1024, raw: bool = False):
        return bytes([self.status_byte])

    # discovery / info
    def info(self) -> dict:
        return {
            "vendor_id": "2d37",
            "product_id": "62de",
            "selector": "vid:2d37:pid:62de",
            "bus": 1,
            "address": 4,
            "port_path": "3-1-2",
            "device_path": "/dev/bus/usb/001/004",
            "serial": "ABC123",
            "manufacturer": "Poskey",
            "product": "420B",
            "description": "Poskey 420B — Poskey / Vretti-class (e.g. 420B)",
            "known_vendor": "Poskey / Vretti-class (e.g. 420B)",
        }


@pytest.fixture
def fake_connection():
    """A ready, healthy fake printer connection (status byte 0x00 = ready)."""
    return FakeConnection(status_byte=0)


@pytest.fixture
def patch_printer_connection(monkeypatch, fake_connection):
    """Make every module's ``config.get_printer_connection`` return the fake.

    Lets the printer/status endpoints run their real code path against a fake
    USB device that reports "ready".

    ``get_printer_connection`` is a *method* (not a settings field), so we patch
    it on the ``Config`` class — pydantic forbids setting it per-instance, and
    every module's ``config`` shares the class anyway.
    """
    from labeljetty.config import Config

    monkeypatch.setattr(Config, "get_printer_connection", lambda self: fake_connection)
    return fake_connection


# --------------------------------------------------------------------------- #
#  FastAPI app + client
# --------------------------------------------------------------------------- #
@pytest.fixture
def app():
    """A fresh FastAPI app (no worker subprocess — that callback is only wired
    in ``labeljetty.app.run``, which tests never call)."""
    from labeljetty.web.app import FastApiAppContainer

    return FastApiAppContainer().app


@pytest.fixture
def client(app):
    """Starlette/httpx TestClient with lifespan run (startup/shutdown)."""
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
#  Small helpers reused across tests
# --------------------------------------------------------------------------- #
@pytest.fixture
def make_job():
    """Factory inserting a PrintJob row and returning it (detached)."""
    def _make(**overrides) -> PrintJob:
        base = dict(job_type="text", params={"text": "hi"}, copies=1)
        base.update(overrides)
        job = PrintJob(**base)
        with db.get_session() as session:
            session.add(job)
            session.commit()
            session.refresh(job)
        return job

    return _make


@pytest.fixture
def status_message():
    """Factory: TSPLPrinterStatusMessage from a raw status byte."""
    return TSPLPrinterStatusMessage.from_raw_response
