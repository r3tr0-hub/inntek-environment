from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import date
from pydantic import BaseModel
from ..database import get_db
from ..models import Shift
from ..schemas import ShiftOut

router = APIRouter(prefix="/shifts", tags=["shifts"])

class ShiftOpenIn(BaseModel):
    date: date
    shift_number: int

@router.post("/open", response_model=ShiftOut)
def open_shift(payload: ShiftOpenIn, db: Session = Depends(get_db)):
    existing = db.query(Shift).filter(
        Shift.date == payload.date, Shift.shift_number == payload.shift_number
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Смена уже открыта")
    s = Shift(date=payload.date, shift_number=payload.shift_number, status="open")
    db.add(s); db.commit(); db.refresh(s)
    return s

@router.get("/current", response_model=ShiftOut | None)
def current_shift(db: Session = Depends(get_db)):
    return db.query(Shift).filter(Shift.status == "open").order_by(Shift.shift_id.desc()).first()