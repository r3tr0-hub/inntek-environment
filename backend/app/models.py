from datetime import date, datetime
from sqlalchemy import (
    String, Integer, BigInteger, Boolean, Date, DateTime, Numeric,
    ForeignKey, Sequence, CheckConstraint, func, JSON, Text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

box_uid_seq = Sequence("box_uid_seq", start=1)

class User(Base):
    __tablename__ = "users"
    user_id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(150))
    employee_code: Mapped[str] = mapped_column(String(10), unique=True)
    role: Mapped[str] = mapped_column(String(20))
    pin: Mapped[str | None] = mapped_column(String(6), nullable=True, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint(
            "role IN ('naladchik','pomoshchnik','stager','upakovshchik','kladovshchik','shift_lead','admin')",
            name="ck_user_role",
        ),
    )

class Shift(Base):
    __tablename__ = "shifts"
    shift_id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date)
    shift_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="open")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (CheckConstraint("shift_number BETWEEN 1 AND 4", name="ck_shift_number"),)

class Specification(Base):
    __tablename__ = "specifications"
    spec_id: Mapped[int] = mapped_column(primary_key=True)
    sku_1c: Mapped[str] = mapped_column(String(20), unique=True)
    name_1c: Mapped[str] = mapped_column(String(200))
    size_label: Mapped[str] = mapped_column(String(50))
    format: Mapped[str | None] = mapped_column(String(10), nullable=True)
    perforation: Mapped[str | None] = mapped_column(String(10), nullable=True)
    color: Mapped[str | None] = mapped_column(String(30), nullable=True)
    film_sku: Mapped[str | None] = mapped_column(String(20), nullable=True)
    film_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    thickness_mkm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_brutto_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class LabelTemplate(Base):
    __tablename__ = "label_templates"
    template_id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    template_content: Mapped[str] = mapped_column(Text)
    producer_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class LabelVariant(Base):
    __tablename__ = "label_variants"
    variant_id: Mapped[int] = mapped_column(primary_key=True)
    spec_id: Mapped[int] = mapped_column(ForeignKey("specifications.spec_id"))
    template_id: Mapped[int] = mapped_column(ForeignKey("label_templates.template_id"))
    label_name: Mapped[str] = mapped_column(String(200))
    barcode: Mapped[str | None] = mapped_column(String(13), nullable=True)
    external_sku: Mapped[str | None] = mapped_column(String(50), nullable=True)
    supplier: Mapped[str | None] = mapped_column(String(100), default='ООО «ИННТЕК»')
    extra_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class Box(Base):
    __tablename__ = "boxes"
    box_id: Mapped[int] = mapped_column(primary_key=True)
    box_uid: Mapped[int] = mapped_column(BigInteger, box_uid_seq, unique=True)
    box_barcode: Mapped[str] = mapped_column(String(50), unique=True)
    qr_content: Mapped[str] = mapped_column(Text)
    spec_id: Mapped[int] = mapped_column(ForeignKey("specifications.spec_id"))
    variant_id: Mapped[int] = mapped_column(ForeignKey("label_variants.variant_id"))
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.shift_id"))
    machine_id: Mapped[int | None] = mapped_column(ForeignKey("machines.machine_id"), nullable=True)
    print_run_id: Mapped[int | None] = mapped_column(ForeignKey("print_runs.run_id"), nullable=True)
    box_number_in_shift: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity_total: Mapped[int] = mapped_column(Integer)
    quantity_packs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity_per_pack: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_brutto_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    batch_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    packer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"), nullable=True)
    operator_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"), nullable=True)
    packer_fio: Mapped[str | None] = mapped_column(String(150), nullable=True)
    operator_fio: Mapped[str | None] = mapped_column(String(150), nullable=True)

    printed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    labeled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    labeled_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"), nullable=True)

    quarantined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quarantined_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"), nullable=True)
    quarantine_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('created','printed','labeled','quarantined','cancelled','on_pallet','shipped')",
            name="ck_box_status",
        ),
    )

class PrintJob(Base):
    __tablename__ = "print_jobs"
    job_id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("label_templates.template_id"), nullable=True)
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("label_variants.variant_id"), nullable=True)
    box_id: Mapped[int | None] = mapped_column(ForeignKey("boxes.box_id"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"), nullable=True)
    printer_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Machine(Base):
    __tablename__ = "machines"
    machine_id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ShiftAssignment(Base):
    __tablename__ = "shift_assignments"
    assignment_id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.shift_id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"))
    role_in_shift: Mapped[str] = mapped_column(String(20))
    machine_id: Mapped[int | None] = mapped_column(ForeignKey("machines.machine_id"), nullable=True)
    from_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    to_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint(
            "role_in_shift IN ('operator','pomoshchnik','stager','upakovshchik')",
            name="ck_assignment_role",
        ),
    )

class PrintRun(Base):
    __tablename__ = "print_runs"
    run_id: Mapped[int] = mapped_column(primary_key=True)
    spec_id: Mapped[int] = mapped_column(ForeignKey("specifications.spec_id"))
    variant_id: Mapped[int] = mapped_column(ForeignKey("label_variants.variant_id"))
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.shift_id"))
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.machine_id"))
    operator_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"), nullable=True)
    packer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer)
    batch_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','done','cancelled')",
            name="ck_print_run_status",
        ),
    )