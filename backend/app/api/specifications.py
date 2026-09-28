from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Specification
from ..schemas import SpecOut, SpecCreate, SpecUpdate

router = APIRouter(prefix="/specifications", tags=["specifications"])


@router.get("", response_model=list[SpecOut])
def list_specs(active: bool | None = None, db: Session = Depends(get_db)):
    q = db.query(Specification)
    if active is not None:
        q = q.filter(Specification.is_active == active)
    return q.order_by(Specification.sku_1c).all()


@router.get("/{spec_id}", response_model=SpecOut)
def get_spec(spec_id: int, db: Session = Depends(get_db)):
    s = db.get(Specification, spec_id)
    if not s:
        raise HTTPException(404, "Спецификация не найдена")
    return s


@router.post("", response_model=SpecOut)
def create_spec(payload: SpecCreate, db: Session = Depends(get_db)):
    if db.query(Specification).filter(Specification.sku_1c == payload.sku_1c).first():
        raise HTTPException(400, f"SKU {payload.sku_1c} уже существует")

    s = Specification(
        sku_1c=payload.sku_1c,
        name_1c=payload.name_1c,
        size_label=payload.size_label,
        format=payload.format,
        perforation=payload.perforation,
        color=payload.color,
        film_sku=payload.film_sku,
        film_name=payload.film_name,
        thickness_mkm=payload.thickness_mkm,
        weight_brutto_g=payload.weight_brutto_g,
        is_active=True,
    )
    db.add(s); db.commit(); db.refresh(s)
    return s


@router.patch("/{spec_id}", response_model=SpecOut)
def update_spec(spec_id: int, payload: SpecUpdate, db: Session = Depends(get_db)):
    s = db.get(Specification, spec_id)
    if not s:
        raise HTTPException(404, "Спецификация не найдена")

    for field in ("name_1c", "size_label", "format", "perforation", "color",
                  "film_sku", "film_name", "thickness_mkm", "weight_brutto_g", "is_active"):
        val = getattr(payload, field)
        if val is not None:
            setattr(s, field, val)

    db.commit(); db.refresh(s)
    return s


@router.delete("/{spec_id}", response_model=SpecOut)
def deactivate_spec(spec_id: int, db: Session = Depends(get_db)):
    s = db.get(Specification, spec_id)
    if not s:
        raise HTTPException(404, "Спецификация не найдена")
    s.is_active = False
    db.commit(); db.refresh(s)
    return s