"""Persistence layer: PrintJob status machine, paths, and status (de)serialization."""

import uuid
from datetime import datetime

from labeljetty.core import db
from labeljetty.core.db import PrintJob, get_session
from labeljetty.printer.tspl import TSPLPrinterStatusMessage


# --------------------------------------------------------------------------- #
#  get_status() state machine
# --------------------------------------------------------------------------- #
def test_status_queued():
    assert PrintJob(job_type="text").get_status() == "queued"


def test_status_processing():
    job = PrintJob(job_type="text", started_at=datetime.now())
    assert job.get_status() == "processing"


def test_status_done():
    job = PrintJob(
        job_type="text", started_at=datetime.now(), finished_at=datetime.now()
    )
    assert job.get_status() == "done"


def test_status_failed():
    job = PrintJob(
        job_type="text",
        started_at=datetime.now(),
        finished_at=datetime.now(),
        error="boom",
    )
    assert job.get_status() == "failed"


# --------------------------------------------------------------------------- #
#  Input file path
# --------------------------------------------------------------------------- #
def test_input_file_path_none_when_no_file():
    assert PrintJob(job_type="text").get_input_file_path() is None


def test_input_file_path_under_storage_dir():
    job = PrintJob(job_type="png", input_file_name="abc.png")
    path = job.get_input_file_path()
    assert path is not None
    assert path.name == "abc.png"


# --------------------------------------------------------------------------- #
#  Round-trip through SQLite (incl. status serialization + JSON params)
# --------------------------------------------------------------------------- #
def test_roundtrip_persists_params_and_status():
    status = TSPLPrinterStatusMessage.from_raw_response(0x04)
    job = PrintJob(
        job_type="qrcode",
        params={"data": "x", "ecc_level": "M"},
        printer_status_on_finished=status,
    )
    with get_session() as session:
        session.add(job)
        session.commit()
        job_id = job.id

    with get_session() as session:
        loaded = session.get(PrintJob, job_id)
        assert loaded.params == {"data": "x", "ecc_level": "M"}
        # NOTE: SQLAlchemy loads bypass pydantic validators, so the status comes
        # back as the stored dict (not a re-hydrated model). What matters is that
        # the content survives the JSON round-trip intact.
        stored = loaded.printer_status_on_finished
        as_dict = stored.model_dump() if hasattr(stored, "model_dump") else stored
        assert as_dict["paper_empty"] is True
        assert as_dict["raw_status_byte"] == 4


def test_get_session_rolls_back_on_error():
    try:
        with get_session() as session:
            session.add(PrintJob(job_type="text"))
            raise RuntimeError("force rollback")
    except RuntimeError:
        pass
    with get_session() as session:
        from sqlmodel import select

        assert session.exec(select(PrintJob)).all() == []
