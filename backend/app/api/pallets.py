from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..models import Pallet, Box, User, Machine, Shift
from ..schemas import (
    PalletOpenIn, PalletCloseIn, PalletMoveBoxIn,
    PalletOut, PalletBoxShort,
)

router = APIRouter(prefix="/pallets", tags=["pallets"])

ALLOWED_OPEN_ROLES = ("upakovshchik", "naladchik", "kladovshchik")
ALLOWED_MOVE_ROLES = ("naladchik", "kladovshchik", "admin")


def _find_user_by_pin(pin: str, db: Session) -> User:
    u = db.query(User).filter(User.pin == pin, User.active == True).first()
    if not u:
        raise HTTPException(401, "Неверный PIN")
    return u


def _get_open_shift(db: Session) -> Shift:
    s = db.query(Shift).filter(Shift.status == "open").first()
    if not s:
        raise HTTPException(400, "Нет активной смены")
    return s


def _generate_pallet_number(db: Session) -> str:
    today = datetime.utcnow().strftime("%Y%m%d")
    prefix = f"PALLET-{today}-"
    last = (
        db.query(Pallet.pallet_number)
        .filter(Pallet.pallet_number.like(f"{prefix}%"))
        .order_by(Pallet.pallet_number.desc())
        .first()
    )
    next_num = 1
    if last:
        try:
            next_num = int(last[0].split("-")[-1]) + 1
        except (ValueError, IndexError):
            next_num = 1
    return f"{prefix}{next_num:03d}"


# ─── Открытие паллеты ───

@router.post("/open", response_model=PalletOut)
def open_pallet(payload: PalletOpenIn, db: Session = Depends(get_db)):
    user = _find_user_by_pin(payload.pin, db)
    if user.role not in ALLOWED_OPEN_ROLES:
        raise HTTPException(403, f"Открыть паллету может: {', '.join(ALLOWED_OPEN_ROLES)}")

    shift = _get_open_shift(db)

    machine = db.get(Machine, payload.machine_id)
    if not machine or not machine.is_active:
        raise HTTPException(404, "Станок не найден или неактивен")

    # Проверка: нет ли уже открытой паллеты на этом станке
    existing = db.query(Pallet).filter(
        Pallet.shift_id == shift.shift_id,
        Pallet.machine_id == payload.machine_id,
        Pallet.status == "open",
    ).first()
    if existing:
        raise HTTPException(
            400,
            f"На станке {machine.code} уже открыта паллета {existing.pallet_number}. Закройте её.",
        )

    p = Pallet(
        pallet_number=_generate_pallet_number(db),
        shift_id=shift.shift_id,
        machine_id=payload.machine_id,
        created_by_user_id=user.user_id,
        status="open",
    )
    db.add(p); db.commit(); db.refresh(p)
    return _to_out(p, db)


# ─── Закрытие паллеты ───

@router.post("/{pallet_id}/close", response_model=PalletOut)
def close_pallet(pallet_id: int, payload: PalletCloseIn, db: Session = Depends(get_db)):
    user = _find_user_by_pin(payload.pin, db)
    p = db.get(Pallet, pallet_id)
    if not p:
        raise HTTPException(404, "Паллета не найдена")
    if p.status != "open":
        raise HTTPException(400, "Паллета уже закрыта")

    # Нельзя закрыть пустую
    boxes_count = db.query(func.count(Box.box_id)).filter(Box.pallet_id == pallet_id).scalar() or 0
    if boxes_count == 0:
        raise HTTPException(400, "Нельзя закрыть пустую паллету — в ней нет коробок")

    p.status = "closed"
    p.closed_at = datetime.utcnow()
    p.closed_by_user_id = user.user_id
    p.close_reason = "manual"
    db.commit(); db.refresh(p)
    return _to_out(p, db)


# ─── Список и карточка ───

def _to_out(p: Pallet, db: Session) -> PalletOut:
    cnt = db.query(func.count(Box.box_id)).filter(Box.pallet_id == p.pallet_id).scalar() or 0
    out = PalletOut.model_validate(p)
    out.boxes_count = cnt
    return out


@router.get("", response_model=list[PalletOut])
def list_pallets(
    shift_id: int | None = None,
    machine_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(Pallet)
    if shift_id is not None:
        q = q.filter(Pallet.shift_id == shift_id)
    if machine_id is not None:
        q = q.filter(Pallet.machine_id == machine_id)
    if status:
        q = q.filter(Pallet.status == status)
    rows = q.order_by(Pallet.pallet_id.desc()).limit(300).all()
    return [_to_out(p, db) for p in rows]


@router.get("/{pallet_id}", response_model=PalletOut)
def get_pallet(pallet_id: int, db: Session = Depends(get_db)):
    p = db.get(Pallet, pallet_id)
    if not p:
        raise HTTPException(404, "Паллета не найдена")
    return _to_out(p, db)


@router.get("/{pallet_id}/boxes", response_model=list[PalletBoxShort])
def get_pallet_boxes(pallet_id: int, db: Session = Depends(get_db)):
    p = db.get(Pallet, pallet_id)
    if not p:
        raise HTTPException(404, "Паллета не найдена")
    return (
        db.query(Box)
        .filter(Box.pallet_id == pallet_id)
        .order_by(Box.box_uid)
        .all()
    )


# ─── Перекладывание коробки ───

@router.post("/move-box", response_model=PalletOut | dict)
def move_box(payload: PalletMoveBoxIn, db: Session = Depends(get_db)):
    """
    Три режима:
      - target_pallet_id: переложить на конкретную паллету
      - create_new_pallet=True + create_new_machine_id: создать новую и положить туда
      - reference_box_id: определить паллету по коробке с неё
      - remove_from_pallet=True: просто снять с паллеты (статус → labeled)
    """
    user = _find_user_by_pin(payload.pin, db)
    if user.role not in ALLOWED_MOVE_ROLES:
        raise HTTPException(403, f"Перекладывать может: {', '.join(ALLOWED_MOVE_ROLES)}")

    _get_open_shift(db)

    box = db.get(Box, payload.box_id)
    if not box:
        raise HTTPException(404, "Коробка не найдена")

    # Режим "снять с паллеты"
    if payload.remove_from_pallet:
        if box.pallet_id is None:
            raise HTTPException(400, "Коробка и так не на паллете")
        box.pallet_id = None
        box.status = "labeled"
        db.commit()
        return {"box_id": box.box_id, "status": "labeled", "pallet_id": None}

    # Определяем целевую паллету
    target: Pallet | None = None

    if payload.create_new_pallet:
        if not payload.create_new_machine_id:
            raise HTTPException(400, "Для создания новой паллеты нужен machine_id")
        machine = db.get(Machine, payload.create_new_machine_id)
        if not machine or not machine.is_active:
            raise HTTPException(404, "Станок не найден или неактивен")
        shift = _get_open_shift(db)
        target = Pallet(
            pallet_number=_generate_pallet_number(db),
            shift_id=shift.shift_id,
            machine_id=payload.create_new_machine_id,
            created_by_user_id=user.user_id,
            status="open",
        )
        db.add(target); db.flush()

    elif payload.reference_box_id:
        ref = db.get(Box, payload.reference_box_id)
        if not ref or ref.pallet_id is None:
            raise HTTPException(404, "Коробка-ориентир не найдена или не на паллете")
        target = db.get(Pallet, ref.pallet_id)

    elif payload.target_pallet_id:
        target = db.get(Pallet, payload.target_pallet_id)
        if not target:
            raise HTTPException(404, "Целевая паллета не найдена")
    else:
        raise HTTPException(400, "Укажите target_pallet_id, create_new_pallet или reference_box_id")

    # Если коробка уже на этой же паллете — ничего не делаем
    if box.pallet_id == target.pallet_id:
        raise HTTPException(400, "Коробка уже на этой паллете")

    box.pallet_id = target.pallet_id
    box.status = "on_pallet"
    db.commit(); db.refresh(target)
    return _to_out(target, db)