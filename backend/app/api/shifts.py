from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import date, datetime
from pydantic import BaseModel

from ..database import get_db
from ..models import Shift, ShiftAssignment, User, Machine, Pallet, Box
from ..schemas import ShiftOut, AssignmentOut, ShiftOpenWithComposition, PackerCheckIn, PackerCheckOut

from sqlalchemy import func

router = APIRouter(prefix="/shifts", tags=["shifts"])


@router.post("/open", response_model=ShiftOut)
def open_shift(payload: ShiftOpenWithComposition, db: Session = Depends(get_db)):
    # Проверяем, что нет активной смены
    active = db.query(Shift).filter(Shift.status == "open").first()
    if active:
        raise HTTPException(400, f"Уже есть активная смена (id={active.shift_id}). Закройте её.")

    # Проверяем оператора
    operator = db.get(User, payload.operator_user_id)
    if not operator:
        raise HTTPException(404, "Оператор не найден")
    if operator.role != "naladchik":
        raise HTTPException(400, "Открыть смену может только наладчик")

    # Создаём смену
    s = Shift(
        date=payload.date,
        shift_number=payload.shift_number,
        status="open",
        opened_at=payload.opened_at,
    )
    db.add(s); db.flush()

    # Добавляем оператора
    db.add(ShiftAssignment(
        shift_id=s.shift_id,
        user_id=operator.user_id,
        role_in_shift="operator",
        from_time=payload.opened_at,
    ))

    # Помощники
    for uid in payload.helper_user_ids:
        u = db.get(User, uid)
        if not u:
            raise HTTPException(404, f"Пользователь {uid} не найден")
        db.add(ShiftAssignment(
            shift_id=s.shift_id, user_id=uid,
            role_in_shift="pomoshchnik", from_time=payload.opened_at,
        ))

    # Стажёры
    for uid in payload.stager_user_ids:
        u = db.get(User, uid)
        if not u:
            raise HTTPException(404, f"Пользователь {uid} не найден")
        db.add(ShiftAssignment(
            shift_id=s.shift_id, user_id=uid,
            role_in_shift="stager", from_time=payload.opened_at,
        ))

    db.commit(); db.refresh(s)
    return s


@router.post("/{shift_id}/close", response_model=ShiftOut)
def close_shift(shift_id: int, db: Session = Depends(get_db)):
    s = db.get(Shift, shift_id)
    if not s:
        raise HTTPException(404, "Смена не найдена")
    if s.status != "open":
        raise HTTPException(400, "Смена уже закрыта")

    now = datetime.utcnow()
    s.status = "closed"
    s.closed_at = now

    # Закрываем все активные назначения
    db.query(ShiftAssignment).filter(
        ShiftAssignment.shift_id == shift_id,
        ShiftAssignment.to_time.is_(None),
    ).update({"to_time": now, "reason": "смена закрыта"})

    # Автозакрытие открытых паллет этой смены
    open_pallets = db.query(Pallet).filter(
        Pallet.shift_id == shift_id,
        Pallet.status == "open",
    ).all()
    for p in open_pallets:
        boxes_cnt = db.query(func.count(Box.box_id)).filter(Box.pallet_id == p.pallet_id).scalar() or 0
        # Пустые паллеты просто удаляем (или оставляем открытыми без закрытия)
        if boxes_cnt == 0:
            db.delete(p)
        else:
            p.status = "closed"
            p.closed_at = now
            p.closed_by_user_id = None
            p.close_reason = "auto_shift_close"

    db.commit(); db.refresh(s)
    return s


@router.get("/current", response_model=ShiftOut | None)
def current_shift(db: Session = Depends(get_db)):
    return db.query(Shift).filter(Shift.status == "open").order_by(Shift.shift_id.desc()).first()


@router.get("/{shift_id}/assignments", response_model=list[AssignmentOut])
def list_assignments(shift_id: int, only_active: bool = False, db: Session = Depends(get_db)):
    q = db.query(ShiftAssignment).filter(ShiftAssignment.shift_id == shift_id)
    if only_active:
        q = q.filter(ShiftAssignment.to_time.is_(None))
    return q.order_by(ShiftAssignment.assignment_id).all()


# ─── Упаковщики ───

@router.post("/packer/checkin", response_model=AssignmentOut)
def packer_checkin(payload: PackerCheckIn, db: Session = Depends(get_db)):
    """Упаковщик приходит на станок и вводит PIN на ТСД. Регистрируется на смене."""
    # Активная смена
    s = db.query(Shift).filter(Shift.status == "open").first()
    if not s:
        raise HTTPException(400, "Нет активной смены")

    # Проверяем PIN
    packer = db.query(User).filter(User.pin == payload.pin, User.active == True).first()
    if not packer:
        raise HTTPException(401, "Неверный PIN")
    if packer.role != "upakovshchik":
        raise HTTPException(400, "Этот пользователь не упаковщик")

    # Проверяем станок
    machine = db.get(Machine, payload.machine_id)
    if not machine or not machine.is_active:
        raise HTTPException(404, "Станок не найден или неактивен")

    # Проверяем, не активен ли уже этот упаковщик где-либо
    existing = db.query(ShiftAssignment).filter(
        ShiftAssignment.shift_id == s.shift_id,
        ShiftAssignment.user_id == packer.user_id,
        ShiftAssignment.role_in_shift == "upakovshchik",
        ShiftAssignment.to_time.is_(None),
    ).first()
    if existing:
        raise HTTPException(400, "Этот упаковщик уже активен на смене")

    a = ShiftAssignment(
        shift_id=s.shift_id,
        user_id=packer.user_id,
        role_in_shift="upakovshchik",
        machine_id=payload.machine_id,
    )
    db.add(a); db.commit(); db.refresh(a)
    return a


@router.post("/packer/checkout", response_model=AssignmentOut)
def packer_checkout(payload: PackerCheckOut, db: Session = Depends(get_db)):
    """Оператор закрывает активное назначение упаковщика с указанием причины."""
    a = db.get(ShiftAssignment, payload.assignment_id)
    if not a:
        raise HTTPException(404, "Назначение не найдено")
    if a.to_time is not None:
        raise HTTPException(400, "Это назначение уже закрыто")
    if a.role_in_shift != "upakovshchik":
        raise HTTPException(400, "Это назначение не упаковщика")

    a.to_time = datetime.utcnow()
    a.reason = payload.reason
    db.commit(); db.refresh(a)
    return a


@router.get("/machine/{machine_id}/packers", response_model=list[AssignmentOut])
def active_packers_on_machine(machine_id: int, db: Session = Depends(get_db)):
    """Активные упаковщики на станке. Первый в списке — основной (идёт в QR)."""
    s = db.query(Shift).filter(Shift.status == "open").first()
    if not s:
        return []
    return db.query(ShiftAssignment).filter(
        ShiftAssignment.shift_id == s.shift_id,
        ShiftAssignment.machine_id == machine_id,
        ShiftAssignment.role_in_shift == "upakovshchik",
        ShiftAssignment.to_time.is_(None),
    ).order_by(ShiftAssignment.from_time).all()