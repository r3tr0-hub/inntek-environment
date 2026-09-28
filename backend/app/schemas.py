from datetime import date, datetime
from pydantic import BaseModel, ConfigDict

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    full_name: str
    role: str
    active: bool

class SpecOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    spec_id: int
    sku_1c: str
    name_1c: str
    size_label: str
    color: str | None = None
    film_sku: str | None = None
    film_name: str | None = None
    thickness_mkm: int | None = None

class ShiftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    shift_id: int
    date: date
    shift_number: int
    status: str

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
    created_at: datetime

class LabelVariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    variant_id: int
    spec_id: int
    template_id: int
    label_name: str
    barcode: str | None = None
    external_sku: str | None = None
    supplier: str | None = None
    # Расшифровка для удобства
    spec_sku: str | None = None
    template_code: str | None = None

class MachineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    machine_id: int
    code: str
    name: str
    is_active: bool

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