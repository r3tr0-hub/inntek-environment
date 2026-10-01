from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import LabelVariant, Specification, LabelTemplate
from ..schemas import LabelVariantOut, LabelVariantCreate, LabelVariantUpdate
from ..services.label_designer.validators import validate_ean13, ean13_error_message


router = APIRouter(prefix="/variants", tags=["variants"])


def _enrich(variant: LabelVariant, spec: Specification, template: LabelTemplate) -> LabelVariantOut:
    item = LabelVariantOut.model_validate(variant)
    item.spec_sku = spec.sku_1c if spec else None
    item.template_code = template.code if template else None
    return item


@router.get("", response_model=list[LabelVariantOut])
def list_variants(
    spec_id: int | None = None,
    template_code: str | None = None,
    active: bool | None = None,
    db: Session = Depends(get_db),
):
    q = (
        db.query(LabelVariant, Specification, LabelTemplate)
        .join(Specification, LabelVariant.spec_id == Specification.spec_id)
        .join(LabelTemplate, LabelVariant.template_id == LabelTemplate.template_id)
    )
    if spec_id is not None:
        q = q.filter(LabelVariant.spec_id == spec_id)
    if template_code:
        q = q.filter(LabelTemplate.code == template_code)
    if active is not None:
        q = q.filter(LabelVariant.is_active == active)

    return [_enrich(v, s, t) for v, s, t in q.order_by(LabelVariant.variant_id).all()]


@router.get("/{variant_id}", response_model=LabelVariantOut)
def get_variant(variant_id: int, db: Session = Depends(get_db)):
    row = (
        db.query(LabelVariant, Specification, LabelTemplate)
        .join(Specification, LabelVariant.spec_id == Specification.spec_id)
        .join(LabelTemplate, LabelVariant.template_id == LabelTemplate.template_id)
        .filter(LabelVariant.variant_id == variant_id)
        .first()
    )
    if not row:
        raise HTTPException(404, "Вариант не найден")
    v, s, t = row
    return _enrich(v, s, t)


@router.post("", response_model=LabelVariantOut)
def create_variant(payload: LabelVariantCreate, db: Session = Depends(get_db)):
    spec = db.get(Specification, payload.spec_id)
    if not spec:
        raise HTTPException(404, "Спецификация не найдена")
    template = db.get(LabelTemplate, payload.template_id)
    if not template:
        raise HTTPException(404, "Шаблон не найден")

    if db.query(LabelVariant).filter(
        LabelVariant.spec_id == payload.spec_id,
        LabelVariant.template_id == payload.template_id,
    ).first():
        raise HTTPException(400, "Вариант с этой парой (spec, template) уже существует")
    # Если штрихкод задан — проверяем контрольную сумму EAN-13.
    if payload.barcode and not validate_ean13(payload.barcode):
        raise HTTPException(
            400,
            f"Некорректный штрихкод: {ean13_error_message(payload.barcode)}",
        )

    v = LabelVariant(
        spec_id=payload.spec_id,
        template_id=payload.template_id,
        label_name=payload.label_name,
        barcode=payload.barcode,
        external_sku=payload.external_sku,
        supplier=payload.supplier or 'ООО «ИННТЕК»',
        is_active=True,
    )
    db.add(v); db.commit(); db.refresh(v)
    return _enrich(v, spec, template)


@router.patch("/{variant_id}", response_model=LabelVariantOut)
def update_variant(variant_id: int, payload: LabelVariantUpdate, db: Session = Depends(get_db)):
    v = db.get(LabelVariant, variant_id)
    if not v:
        raise HTTPException(404, "Вариант не найден")

    # Отдельно проверяем новый barcode перед записью.
    if payload.barcode is not None and not validate_ean13(payload.barcode):
        raise HTTPException(
            400,
            f"Некорректный штрихкод: {ean13_error_message(payload.barcode)}",
        )

    for field in ("label_name", "barcode", "external_sku", "supplier", "is_active"):
        val = getattr(payload, field)
        if val is not None:
            setattr(v, field, val)

    db.commit(); db.refresh(v)
    spec = db.get(Specification, v.spec_id)
    template = db.get(LabelTemplate, v.template_id)
    return _enrich(v, spec, template)


@router.delete("/{variant_id}", response_model=LabelVariantOut)
def deactivate_variant(variant_id: int, db: Session = Depends(get_db)):
    v = db.get(LabelVariant, variant_id)
    if not v:
        raise HTTPException(404, "Вариант не найден")
    v.is_active = False
    db.commit(); db.refresh(v)
    spec = db.get(Specification, v.spec_id)
    template = db.get(LabelTemplate, v.template_id)
    return _enrich(v, spec, template)