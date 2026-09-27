from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import LabelVariant, Specification, LabelTemplate
from ..schemas import LabelVariantOut

router = APIRouter(prefix="/variants", tags=["variants"])


@router.get("", response_model=list[LabelVariantOut])
def list_variants(
    spec_id: int | None = None,
    template_code: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Список вариантов этикеток.
    Фильтры (опционально):
      - spec_id — только для конкретной спецификации
      - template_code — 'VBK' | 'MP' | 'CDEK'
    """
    q = (
        db.query(LabelVariant, Specification, LabelTemplate)
        .join(Specification, LabelVariant.spec_id == Specification.spec_id)
        .join(LabelTemplate, LabelVariant.template_id == LabelTemplate.template_id)
        .filter(LabelVariant.is_active == True)
    )
    if spec_id is not None:
        q = q.filter(LabelVariant.spec_id == spec_id)
    if template_code:
        q = q.filter(LabelTemplate.code == template_code)

    result = []
    for variant, spec, template in q.order_by(LabelVariant.variant_id).all():
        item = LabelVariantOut.model_validate(variant)
        item.spec_sku = spec.sku_1c
        item.template_code = template.code
        result.append(item)
    return result