from operator import is_
from typing import Optional, Dict, Literal
from sqlmodel import select
import time
import multiprocessing
import os
import signal
from datetime import datetime, timedelta
import psutil
from sqlalchemy.sql.operators import is_
from pydantic import BaseModel

from labeljetty.core.db import get_session, PrintJob, WorkerStatus, init_db
from labeljetty.printer import TSPLPrinter, TSPLPrinterConnectionUSB
from labeljetty.core.logging import get_logger

from labeljetty.config import get_config, reload_config

config = get_config()
log = get_logger()


# Response Models
class ProcessInfo(BaseModel):
    pid: int
    status: str
    cpu_percent: float
    memory_mb: float
    create_time: str


class WorkerStatusResponse(BaseModel):
    status: Literal["not_started", "running", "dead", "error"]
    process_id: Optional[int] = None
    worker_error: Optional[str] = None
    process_alive: bool
    process_info: Optional[ProcessInfo] = None


class PrintServiceManager:
    def __init__(self):
        init_db()
        self.process = None
        self.shutdown_event = multiprocessing.Event()
        self._stopped = False

    def start(self):
        """Start print service in background process (non-blocking)"""
        if self.process and self.process.is_alive():
            log.warning("Print service already running")
            return

        self.process = multiprocessing.Process(
            target=self._run_service_with_watchdog, args=(self.shutdown_event,)
        )
        # Daemonic: the interpreter terminates this child on a normal parent exit,
        # so the worker can never be left orphaned even if our explicit shutdown
        # path is skipped (e.g. KeyboardInterrupt escaping uvicorn.serve()).
        self.process.daemon = True
        self.process.start()
        log.info(f"Print service started with PID {self.process.pid}")

    def shutdown(self, timeout: float = 10.0):
        """Reliably shut down the service. Idempotent — safe to call more than once
        (it is invoked from both the FastAPI lifespan and the entrypoint's finally)."""
        if self._stopped:
            return
        self._stopped = True
        log.info("Shutting down print service...")
        self.shutdown_event.set()

        if self.process:
            self.process.join(timeout=timeout)
            if self.process.is_alive():
                log.warning("Process didn't stop gracefully, terminating...")
                self.process.terminate()
                self.process.join(timeout=5)
                if self.process.is_alive():
                    log.error("Process didn't terminate, killing...")
                    self.process.kill()
                    self.process.join()

        log.info("Print service stopped")

    @classmethod
    def get_worker_status(cls) -> WorkerStatusResponse:
        """
        Query worker status and verify process health (call this from REST API)
        """
        with get_session() as session:
            status = session.get(WorkerStatus, 1)

            if not status:
                return WorkerStatusResponse(
                    status="not_started",
                    process_id=None,
                    worker_error=None,
                    process_alive=False,
                    process_info=None,
                )

            process_alive = False
            process_info = None

            if status.process_id:
                try:
                    process = psutil.Process(status.process_id)
                    process_alive = (
                        process.is_running()
                        and process.status() != psutil.STATUS_ZOMBIE
                    )

                    if process_alive:
                        process_info = ProcessInfo(
                            pid=process.pid,
                            status=process.status(),
                            cpu_percent=process.cpu_percent(interval=0.1),
                            memory_mb=process.memory_info().rss / 1024 / 1024,
                            create_time=datetime.fromtimestamp(
                                process.create_time()
                            ).isoformat(),
                        )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    process_alive = False

            # Determine overall status
            if status.worker_error:
                overall_status = "error"
            elif not process_alive:
                overall_status = "dead"
            else:
                overall_status = "running"

            return WorkerStatusResponse(
                status=overall_status,
                process_id=status.process_id,
                worker_error=status.worker_error,
                process_alive=process_alive,
                process_info=process_info,
            )

    @staticmethod
    def _run_service_with_watchdog(shutdown_event: multiprocessing.Event):
        """Watchdog that restarts service on failure (max 3 times)"""
        # A terminal Ctrl+C delivers SIGINT to the whole process group, this child
        # included. Ignore it here so the worker is never interrupted mid-print and
        # its lifecycle is driven solely by the parent (shutdown_event / terminate).
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        max_retries = 3
        retry_count = 0

        # Initialize worker status
        with get_session() as session:
            status = WorkerStatus(id=1, process_id=os.getpid(), worker_error=None)
            session.merge(status)

        while not shutdown_event.is_set() and retry_count < max_retries:
            try:
                service = PrintService()
                service.run(shutdown_event)
                break
            except Exception as e:
                retry_count += 1
                error_msg = (
                    f"Service crashed (attempt {retry_count}/{max_retries}): {e}"
                )
                log.error(error_msg)

                with get_session() as session:
                    status = session.get(WorkerStatus, 1)
                    if status:
                        status.worker_error = error_msg
                        session.add(status)

                if retry_count < max_retries:
                    time.sleep(5)

        if retry_count >= max_retries:
            with get_session() as session:
                status = session.get(WorkerStatus, 1)
                if status:
                    status.worker_error = (
                        f"Service failed after {max_retries} retries. Giving up."
                    )
                    session.add(status)
            log.error("Print service gave up after max retries")


class PrintService:
    def run(self, shutdown_event: multiprocessing.Event):
        """Main service loop"""
        log.info("Print service started")
        while not shutdown_event.is_set():
            try:
                log.debug("Check for next print job")
                job = self.get_next_print_job()
                if job:
                    self.print_job(job)
                else:
                    time.sleep(1)
            except Exception as e:
                log.error(f"Error in print loop: {e}")
                time.sleep(5)

    def get_next_print_job(self) -> Optional[PrintJob]:
        """Get oldest queued job (returned detached but with all attributes loaded)."""
        with get_session() as session:
            stmt = (
                select(PrintJob)
                .where(is_(PrintJob.started_at, None))
                .order_by(PrintJob.created_at)
            )
            job = session.exec(stmt).first()
            if job is not None:
                # Detach before the context manager commits (which would expire the
                # instance and break attribute access after the session closes).
                session.expunge(job)
            return job

    def print_job(self, job: PrintJob):
        """Execute a print job by dispatching on its type."""
        con = None
        try:
            job.started_at = datetime.now()
            self.save_print_job(job)

            # This worker is a separate process, so settings changed via the web
            # UI don't reach it through reload_config() there. Refresh from the DB
            # overlay per job (jobs are human-paced — the extra read is negligible)
            # so the printer selector and geometry defaults stay current.
            reload_config()

            con = config.get_printer_connection()
            con.connect()
            printer = TSPLPrinter(
                connection=con,
                label_width_mm=job.label_width_mm or config.DEFAULT_LABEL_WIDTH_MM,
                label_height_mm=job.label_height_mm or config.DEFAULT_LABEL_HEIGHT_MM,
                dpi=job.dpi or config.DEFAULT_DPI,
            )

            printer.wait_until_ready(timeout=60)
            self._dispatch(printer, job)
            printer.wait_until_ready(10)

            job.printer_status_on_finished = printer.get_status()
            job.error = printer.get_error_message()

        except Exception as e:
            log.error(f"Print job failed: {e}")
            job.error = str(e)
        finally:
            # Release the USB device so status probes / the next job can claim it.
            if con is not None:
                con.disconnect()
            job.finished_at = datetime.now()
            self.save_print_job(job)

    @staticmethod
    def _dispatch(printer: TSPLPrinter, job: PrintJob):
        """Route a job to the matching TSPLPrinter renderer."""
        params: dict = job.params or {}
        copies: int = job.copies or 1
        job_type = job.job_type

        rotate = params.get("rotate", 0)

        if job_type == "png":
            printer.print_png(
                job.get_input_file_path(),
                fit=params.get("fit", "fit"),
                margin_mm=params.get("margin_mm", 0.0),
                rotate=rotate,
                copies=copies,
            )
        elif job_type == "pdf":
            printer.print_pdf(
                job.get_input_file_path(),
                page=params.get("page", 0),
                fit=params.get("fit", "fit"),
                margin_mm=params.get("margin_mm", 0.0),
                rotate=rotate,
                copies=copies,
            )
        elif job_type == "text":
            printer.print_text(
                params["text"],
                font_size=params.get("font_size"),
                fit=params.get("fit", "fill"),
                rotate=rotate,
                copies=copies,
            )
        elif job_type == "markdown":
            printer.print_markdown(
                params["text"], fit=params.get("fit", "fill"), rotate=rotate
            )
        elif job_type == "barcode":
            if params.get("text"):
                printer.print_barcode_with_text(
                    params["data"],
                    text=params["text"],
                    barcode_type=params.get("barcode_type", "128"),
                    copies=copies,
                )
            else:
                printer.print_barcode(
                    params["data"],
                    barcode_type=params.get("barcode_type", "128"),
                    copies=copies,
                )
        elif job_type == "qrcode":
            if params.get("text"):
                printer.print_qrcode_with_text(
                    params["data"],
                    text=params["text"],
                    ecc_level=params.get("ecc_level", "M"),
                    copies=copies,
                )
            else:
                printer.print_qrcode(
                    params["data"],
                    ecc_level=params.get("ecc_level", "M"),
                    copies=copies,
                )
        elif job_type == "raw":
            printer.print_raw_tspl(
                params["tspl"],
                copies=copies,
            )
        else:
            raise ValueError(f"Unknown job_type: {job_type}")

    def save_print_job(self, job: PrintJob):
        """Persist job to database (merge, since the job is detached)."""
        with get_session() as session:
            session.merge(job)

    def clean_obsolete_print_jobs(self):
        with get_session() as session:
            cutoff_time = datetime.now() - timedelta(
                days=config.DELETE_OLD_JOBS_AFTER_DAYS
            )
            jobs_to_delete_query = select(PrintJob).where(
                PrintJob.created_at < cutoff_time
            )
            jobs_to_delete_result = session.exec(jobs_to_delete_query)
            jobs_to_delete = jobs_to_delete_result.all()
            for job in jobs_to_delete:
                # if file exists delete it
                log.info(
                    f"Delete obsolete job because of age as configured in `DELETE_OLD_JOBS_AFTER_DAYS`. Job details: {job}"
                )
                job_file = job.get_input_file_path()
                if job_file is not None and os.path.exists(job_file):
                    os.remove(job_file)
                session.delete(job)
            session.commit()
