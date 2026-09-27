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
    quantity_total: int
    quantity_packs: int | None = None
    quantity_per_pack: int | None = None
    packer_user_id: int | None = None
    operator_user_id: int | None = None

class BoxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    box_id: int
    box_uid: int
    box_barcode: str
    qr_content: str
    box_number_in_shift: int | None
    status: str
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