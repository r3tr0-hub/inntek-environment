from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import LabelTemplate
from ..schemas import TemplateOut, TemplateDetailOut, TemplateCreate, TemplateUpdate

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[TemplateOut])
def list_templates(active: bool | None = None, db: Session = Depends(get_db)):
    q = db.query(LabelTemplate)
    if active is not None:
        q = q.filter(LabelTemplate.is_active == active)
    return q.order_by(LabelTemplate.code).all()


@router.get("/{template_id}", response_model=TemplateDetailOut)
def get_template(template_id: int, db: Session = Depends(get_db)):
    t = db.get(LabelTemplate, template_id)
    if not t:
        raise HTTPException(404, "Шаблон не найден")
    return t


@router.post("", response_model=TemplateDetailOut)
def create_template(payload: TemplateCreate, db: Session = Depends(get_db)):
    if db.query(LabelTemplate).filter(LabelTemplate.code == payload.code).first():
        raise HTTPException(400, f"Шаблон с кодом {payload.code} уже существует")

    t = LabelTemplate(
        code=payload.code,
        name=payload.name,
        template_content=payload.template_content,
        producer_info=payload.producer_info,
        is_active=True,
    )
    db.add(t); db.commit(); db.refresh(t)
    return t


@router.patch("/{template_id}", response_model=TemplateDetailOut)
def update_template(template_id: int, payload: TemplateUpdate, db: Session = Depends(get_db)):
    t = db.get(LabelTemplate, template_id)
    if not t:
        raise HTTPException(404, "Шаблон не найден")

    for field in ("name", "template_content", "producer_info", "is_active"):
        val = getattr(payload, field)
        if val is not None:
            setattr(t, field, val)

    db.commit(); db.refresh(t)
    return t


@router.delete("/{template_id}", response_model=TemplateDetailOut)
def deactivate_template(template_id: int, db: Session = Depends(get_db)):
    t = db.get(LabelTemplate, template_id)
    if not t:
        raise HTTPException(404, "Шаблон не найден")
    t.is_active = False
    db.commit(); db.refresh(t)
    return t