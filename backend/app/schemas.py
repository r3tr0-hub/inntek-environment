from datetime import date, datetime
from pydantic import BaseModel, ConfigDict


# ─── Users ───

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    full_name: str
    employee_code: str
    role: str
    active: bool


class UserCreate(BaseModel):
    full_name: str
    employee_code: str
    role: str
    pin: str | None = None


class UserUpdate(BaseModel):
    full_name: str | None = None
    employee_code: str | None = None
    role: str | None = None
    pin: str | None = None
    active: bool | None = None


# ─── Specifications ───

class SpecOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    spec_id: int
    sku_1c: str
    name_1c: str
    size_label: str
    format: str | None = None
    perforation: str | None = None
    color: str | None = None
    film_sku: str | None = None
    film_name: str | None = None
    thickness_mkm: int | None = None
    weight_brutto_g: int | None = None
    is_active: bool


class SpecCreate(BaseModel):
    sku_1c: str
    name_1c: str
    size_label: str
    format: str | None = None
    perforation: str | None = None
    color: str | None = None
    film_sku: str | None = None
    film_name: str | None = None
    thickness_mkm: int | None = None
    weight_brutto_g: int | None = None


class SpecUpdate(BaseModel):
    name_1c: str | None = None
    size_label: str | None = None
    format: str | None = None
    perforation: str | None = None
    color: str | None = None
    film_sku: str | None = None
    film_name: str | None = None
    thickness_mkm: int | None = None
    weight_brutto_g: int | None = None
    is_active: bool | None = None


# ─── Templates ───

class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    template_id: int
    code: str
    name: str
    is_active: bool


class TemplateDetailOut(TemplateOut):
    template_content: str
    producer_info: str | None = None


class TemplateCreate(BaseModel):
    code: str
    name: str
    template_content: str
    producer_info: str | None = None


class TemplateUpdate(BaseModel):
    name: str | None = None
    template_content: str | None = None
    producer_info: str | None = None
    is_active: bool | None = None


# ─── Label variants ───

class LabelVariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    variant_id: int
    spec_id: int
    template_id: int
    label_name: str
    barcode: str | None = None
    external_sku: str | None = None
    supplier: str | None = None
    spec_sku: str | None = None
    template_code: str | None = None
    is_active: bool


class LabelVariantCreate(BaseModel):
    spec_id: int
    template_id: int
    label_name: str
    barcode: str | None = None
    external_sku: str | None = None
    supplier: str | None = 'ООО «ИННТЕК»'


class LabelVariantUpdate(BaseModel):
    label_name: str | None = None
    barcode: str | None = None
    external_sku: str | None = None
    supplier: str | None = None
    is_active: bool | None = None


# ─── Machines ───

class MachineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    machine_id: int
    code: str
    name: str
    is_active: bool


# ─── Shifts ───

class ShiftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    shift_id: int
    date: date
    shift_number: int
    status: str


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    assignment_id: int
    shift_id: int
    user_id: int
    role_in_shift: str
    machine_id: int | None = None
    from_time: datetime
    to_time: datetime | None = None
    reason: str | None = None


class ShiftOpenWithComposition(BaseModel):
    date: date
    shift_number: int
    operator_user_id: int
    opened_at: datetime
    helper_user_ids: list[int] = []
    stager_user_ids: list[int] = []


class PackerCheckIn(BaseModel):
    pin: str
    machine_id: int


class PackerCheckOut(BaseModel):
    assignment_id: int
    reason: str


# ─── Boxes ───

class BoxCreate(BaseModel):
    spec_id: int
    variant_id: int
    shift_id: int
    machine_id: int
    quantity_total: int
    quantity_packs: int | None = None
    quantity_per_pack: int | None = None
    operator_user_id: int | None = None


class BoxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    box_id: int
    box_uid: int
    box_barcode: str
    qr_content: str
    box_number_in_shift: int | None
    status: str
    machine_id: int | None = None
    printed_at: datetime | None = None
    labeled_at: datetime | None = None
    quarantined_at: datetime | None = None
    quarantine_reason: str | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None
    created_at: datetime

# ─── Box actions ───

class BoxQuarantine(BaseModel):
    reason: str


class BoxCancel(BaseModel):
    reason: str


class BoxScanIn(BaseModel):
    """Сканирование коробки упаковщиком через ТСД.
    ТСД хранит PIN упаковщика и отправляет его в каждом запросе."""
    pin: str
    qr: str  # сырое содержимое QR или box_barcode


class BoxScanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    box_id: int
    box_uid: int
    box_barcode: str
    status: str
    spec_id: int
    variant_id: int
    machine_id: int | None
    box_number_in_shift: int | None
    labeled_at: datetime | None

# ─── Print runs ───

class PrintRunCreate(BaseModel):
    spec_id: int
    variant_id: int
    shift_id: int
    machine_id: int
    quantity: int
    quantity_total: int
    quantity_packs: int | None = None
    quantity_per_pack: int | None = None
    operator_user_id: int


class PrintRunCancel(BaseModel):
    reason: str


class PrintRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    run_id: int
    spec_id: int
    variant_id: int
    shift_id: int
    machine_id: int
    operator_user_id: int | None = None
    packer_user_id: int | None = None
    quantity: int
    batch_number: str | None = None
    status: str
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None
    created_at: datetime


class PrintRunResult(BaseModel):
    run_id: int
    quantity: int
    first_box_uid: int
    last_box_uid: int
    transport: str
    print_status: str
    details: dict

# ─── Отчёт по смене ───

class ReportUserShort(BaseModel):
    user_id: int
    full_name: str
    employee_code: str


class ReportPacker(BaseModel):
    user_id: int
    full_name: str
    employee_code: str
    boxes_labeled: int
    machines: list[str]


class ReportSpec(BaseModel):
    spec_id: int
    sku_1c: str
    name_1c: str
    size_label: str
    boxes_labeled: int
    total_packets: int


class ReportMachine(BaseModel):
    machine_id: int
    code: str
    name: str
    boxes_labeled: int


class ReportTotals(BaseModel):
    boxes_printed: int
    boxes_labeled: int
    boxes_cancelled: int
    boxes_quarantined: int
    total_packets: int


class ShiftReport(BaseModel):
    shift_id: int
    date: date
    shift_number: int
    status: str
    opened_at: datetime
    closed_at: datetime | None = None
    duration_minutes: int
    operator: ReportUserShort | None = None
    helpers: list[ReportUserShort] = []
    stagers: list[ReportUserShort] = []
    packers: list[ReportPacker] = []
    specifications: list[ReportSpec] = []
    machines: list[ReportMachine] = []
    totals: ReportTotals

# ─── Pallets ───

class PalletOpenIn(BaseModel):
    pin: str
    machine_id: int


class PalletCloseIn(BaseModel):
    pin: str


class PalletMoveBoxIn(BaseModel):
    pin: str
    box_id: int
    target_pallet_id: int | None = None
    create_new_pallet: bool = False
    reference_box_id: int | None = None  # паллета определяется по этой коробке
    create_new_machine_id: int | None = None  # для создания новой паллеты нужен machine_id
    remove_from_pallet: bool = False  # если true — просто снять с паллеты


class PalletOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    pallet_id: int
    pallet_number: str
    shift_id: int
    machine_id: int
    created_by_user_id: int
    closed_by_user_id: int | None = None
    close_reason: str | None = None
    status: str
    created_at: datetime
    closed_at: datetime | None = None
    boxes_count: int | None = None


class PalletBoxShort(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    box_id: int
    box_uid: int
    box_barcode: str
    box_number_in_shift: int | None
    spec_id: int
    status: str