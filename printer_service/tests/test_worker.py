"""Print service worker: job dispatch, queue ordering, status, cleanup.

The print *path* is exercised against a fake connection — no subprocess is
spawned and no USB device is touched.
"""

import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import psutil
import pytest

from labeljetty.core import db
from labeljetty.core.db import PrintJob, WorkerStatus, get_session
from labeljetty.service import worker as worker_mod
from labeljetty.service.worker import PrintService, PrintServiceManager


# --------------------------------------------------------------------------- #
#  _dispatch routing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "job,method",
    [
        (PrintJob(job_type="text", params={"text": "hi"}), "print_text"),
        (PrintJob(job_type="markdown", params={"text": "# hi"}), "print_markdown"),
        (PrintJob(job_type="qrcode", params={"data": "x"}), "print_qrcode"),
        (
            PrintJob(job_type="qrcode", params={"data": "x", "text": "cap"}),
            "print_qrcode_with_text",
        ),
        (PrintJob(job_type="barcode", params={"data": "1"}), "print_barcode"),
        (
            PrintJob(job_type="barcode", params={"data": "1", "text": "c"}),
            "print_barcode_with_text",
        ),
        (PrintJob(job_type="png", input_file_name="a.png"), "print_png"),
        (PrintJob(job_type="pdf", input_file_name="a.pdf"), "print_pdf"),
    ],
)
def test_dispatch_routes_to_correct_method(job, method):
    printer = MagicMock()
    PrintService._dispatch(printer, job)
    getattr(printer, method).assert_called_once()


def test_dispatch_unknown_type_raises():
    with pytest.raises(ValueError):
        PrintService._dispatch(MagicMock(), PrintJob(job_type="bogus"))


# --------------------------------------------------------------------------- #
#  Queue ordering
# --------------------------------------------------------------------------- #
def test_get_next_returns_oldest_unstarted():
    older = PrintJob(job_type="text", created_at=datetime(2020, 1, 1))
    newer = PrintJob(job_type="text", created_at=datetime(2024, 1, 1))
    with get_session() as s:
        s.add(older)
        s.add(newer)
        s.commit()
        older_id = older.id

    nxt = PrintService().get_next_print_job()
    assert nxt.id == older_id


def test_get_next_skips_started_jobs():
    with get_session() as s:
        s.add(PrintJob(job_type="text", started_at=datetime.now()))
        s.commit()
    assert PrintService().get_next_print_job() is None


# --------------------------------------------------------------------------- #
#  Worker status
# --------------------------------------------------------------------------- #
def test_status_not_started():
    assert PrintServiceManager.get_worker_status().status == "not_started"


def test_status_running_for_live_pid():
    with get_session() as s:
        s.merge(WorkerStatus(id=1, process_id=os.getpid(), worker_error=None))
    assert PrintServiceManager.get_worker_status().status == "running"


def test_status_error_when_worker_error_set():
    with get_session() as s:
        s.merge(WorkerStatus(id=1, process_id=os.getpid(), worker_error="crashed"))
    assert PrintServiceManager.get_worker_status().status == "error"


def test_status_dead_when_process_gone(monkeypatch):
    with get_session() as s:
        s.merge(WorkerStatus(id=1, process_id=4242424, worker_error=None))

    def boom(_pid):
        raise psutil.NoSuchProcess(_pid)

    monkeypatch.setattr(worker_mod.psutil, "Process", boom)
    assert PrintServiceManager.get_worker_status().status == "dead"


# --------------------------------------------------------------------------- #
#  Cleanup of obsolete jobs
# --------------------------------------------------------------------------- #
def test_clean_obsolete_jobs_removes_old_rows_and_files(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_mod.config, "DELETE_OLD_JOBS_AFTER_DAYS", 10)
    monkeypatch.setattr(worker_mod.config, "IMAGE_STORAGE_DIRECTORY", str(tmp_path))
    # PrintJob.get_input_file_path() resolves files via the db module's config.
    monkeypatch.setattr(db.config, "IMAGE_STORAGE_DIRECTORY", str(tmp_path))
    old_file = tmp_path / "old.png"
    old_file.write_bytes(b"x")

    with get_session() as s:
        s.add(
            PrintJob(
                job_type="png",
                input_file_name="old.png",
                created_at=datetime.now() - timedelta(days=100),
            )
        )
        s.add(PrintJob(job_type="text", created_at=datetime.now()))
        s.commit()

    PrintService().clean_obsolete_print_jobs()

    from sqlmodel import select

    with get_session() as s:
        remaining = s.exec(select(PrintJob)).all()
    assert len(remaining) == 1
    assert remaining[0].job_type == "text"
    assert not old_file.exists()


# --------------------------------------------------------------------------- #
#  Full print path against the fake connection
# --------------------------------------------------------------------------- #
def test_print_job_marks_done(patch_printer_connection):
    job = PrintJob(job_type="text", params={"text": "hi"})
    with get_session() as s:
        s.add(job)
        s.commit()
        s.refresh(job)
        s.expunge(job)

    PrintService().print_job(job)

    with get_session() as s:
        loaded = s.get(PrintJob, job.id)
    assert loaded.started_at is not None
    assert loaded.finished_at is not None
    assert loaded.error is None
    # The fake connection received a real TSPL job.
    assert any("BITMAP" in str(c) for c in patch_printer_connection.sent)
