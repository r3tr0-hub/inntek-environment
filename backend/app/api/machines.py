from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_db
from ..models import Machine
from ..schemas import MachineOut

router = APIRouter(prefix="/machines", tags=["machines"])


class MachineCreate(BaseModel):
    code: str
    name: str


class MachineUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None


@router.get("", response_model=list[MachineOut])
def list_machines(db: Session = Depends(get_db)):
    return db.query(Machine).order_by(Machine.code).all()


@router.post("", response_model=MachineOut)
def create_machine(payload: MachineCreate, db: Session = Depends(get_db)):
    existing = db.query(Machine).filter(Machine.code == payload.code).first()
    if existing:
        raise HTTPException(400, f"Станок с кодом {payload.code} уже существует")
    m = Machine(code=payload.code, name=payload.name)
    db.add(m); db.commit(); db.refresh(m)
    return m


@router.patch("/{machine_id}", response_model=MachineOut)
def update_machine(machine_id: int, payload: MachineUpdate, db: Session = Depends(get_db)):
    m = db.get(Machine, machine_id)
    if not m:
        raise HTTPException(404, "Станок не найден")
    if payload.name is not None:
        m.name = payload.name
    if payload.is_active is not None:
        m.is_active = payload.is_active
    db.commit(); db.refresh(m)
    return m