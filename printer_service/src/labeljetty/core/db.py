from typing import Optional, Literal, Dict, Generator, Any
from datetime import datetime
from sqlmodel import SQLModel, Field, Column, Session, create_engine, select
from pydantic import NaiveDatetime
from sqlalchemy import String
from contextlib import contextmanager
from labeljetty.core.sqltypes import SqlJsonText
from labeljetty.config import Config, get_config
import uuid
from pathlib import Path
from pydantic import field_serializer, field_validator
from labeljetty.printer import JobType, TSPLPrinterStatusMessage

config = get_config()
# Database URL - configure as needed
DATABASE_URL = f"sqlite:///{config.SQLITE_PATH}"

# Create engine
engine = create_engine(DATABASE_URL, echo=False)


class PrintJob(SQLModel, table=True):
    id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4, primary_key=True)

    job_type: JobType = Field(
        sa_column=Column(String), description="Which renderer the worker should use"
    )
    # Type-specific parameters (text content, barcode_type, ecc_level, font_size, ...)
    params: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(SqlJsonText),
    )
    # Stored upload for file-based jobs (png/pdf); None for parameter-only jobs.
    input_file_name: Optional[str] = None

    # Per-job label geometry override; None → fall back to config defaults.
    label_width_mm: Optional[int] = None
    label_height_mm: Optional[int] = None
    dpi: Optional[int] = None
    copies: int = 1

    error: Optional[str] = None
    printer_status_on_finished: Optional[TSPLPrinterStatusMessage] = Field(
        default=None,
        sa_column=Column(SqlJsonText),
    )
    created_at: NaiveDatetime = Field(default_factory=datetime.now)
    started_at: Optional[NaiveDatetime] = None
    finished_at: Optional[NaiveDatetime] = None

    def get_status(self) -> Literal["queued", "processing", "done", "failed"]:
        if self.started_at is None:
            return "queued"
        elif self.finished_at is None:
            return "processing"
        elif self.error is not None:
            return "failed"
        else:
            return "done"

    def get_input_file_path(self) -> Optional[Path]:
        if self.input_file_name is None:
            return None
        return Path(f"{config.IMAGE_STORAGE_DIRECTORY}/{self.input_file_name}")

    @field_serializer("printer_status_on_finished")
    def serialize_printer_status(
        self, value: Optional[TSPLPrinterStatusMessage | Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Convert TSPLPrinterStatusMessage to dict for storage/response.

        Pydantic v2.13 вызывает этот метод и при сериализации ORM-инстансов,
        где поле уже загружено из SQLite как dict — поэтому проверяем тип
        и не полагаемся на ``.model_dump()`` безусловно.
        """
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        if hasattr(value, "model_dump"):
            return value.model_dump()
        return value  # на всякий случай — что-то иное

    @field_validator("printer_status_on_finished", mode="before")
    @classmethod
    def validate_printer_status(cls, value: Dict[str, Any] | None):
        """Convert dict to TSPLPrinterStatusMessage when loading from database"""
        if value is None or isinstance(value, TSPLPrinterStatusMessage):
            return value
        if isinstance(value, dict):
            return TSPLPrinterStatusMessage(**value)
        return value


class SettingOverride(SQLModel, table=True):
    """One admin-edited config override (key → JSON value), applied on top of env.

    Written by the settings UI and read back by ``config.build_config()`` (which
    uses stdlib sqlite3 to avoid importing this module). The table name SQLModel
    derives — ``settingoverride`` — is referenced there as ``_OVERLAY_TABLE``."""

    key: str = Field(primary_key=True, description="Config field name, e.g. DEFAULT_DPI")
    json_value: str = Field(description="json.dumps() of the override value")
    updated_at: NaiveDatetime = Field(default_factory=datetime.now)


class WorkerStatus(SQLModel, table=True):
    id: Optional[int] = Field(
        default=1, primary_key=True, description="dummy pk field. Will always be one"
    )
    worker_error: Optional[str] = Field(
        default=None, description="If set the worker is dead"
    )
    process_id: Optional[int] = Field(default=None)


# Database initialization
def init_db():
    """Initialize database tables"""
    SQLModel.metadata.create_all(engine)


# Session management
@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager for database sessions.

    ``expire_on_commit=False`` keeps attributes populated after commit so jobs can
    be safely returned/serialized once the session has closed (FastAPI responses,
    the worker handing a fetched job to the printer).
    """
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db_url() -> str:
    """Get database URL"""
    return DATABASE_URL


# --------------------------------------------------------------------------- #
#  Settings overrides (admin config edited via the web UI)
# --------------------------------------------------------------------------- #
def get_setting_overrides() -> Dict[str, str]:
    """All stored overrides as ``{key: json_value}`` (raw JSON strings)."""
    with get_session() as session:
        rows = session.exec(select(SettingOverride)).all()
        return {row.key: row.json_value for row in rows}


def set_setting_overrides(values: Dict[str, str]) -> None:
    """Replace the override set with ``values`` (``{key: json_value}``). Keys not
    present are deleted, so this mirrors exactly what the settings form submitted."""
    with get_session() as session:
        existing = {row.key: row for row in session.exec(select(SettingOverride)).all()}
        for key, json_value in values.items():
            row = existing.pop(key, None)
            if row is None:
                session.add(SettingOverride(key=key, json_value=json_value))
            else:
                row.json_value = json_value
                row.updated_at = datetime.now()
                session.add(row)
        for stale in existing.values():  # keys no longer submitted → clear override
            session.delete(stale)


def clear_setting_overrides() -> None:
    """Remove every override (revert to env/defaults)."""
    with get_session() as session:
        for row in session.exec(select(SettingOverride)).all():
            session.delete(row)
