from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Specification
from ..schemas import SpecOut

router = APIRouter(prefix="/specifications", tags=["specifications"])

@router.get("", response_model=list[SpecOut])
def list_specs(db: Session = Depends(get_db)):
    return db.query(Specification).filter(Specification.is_active == True).order_by(Specification.sku_1c).all()