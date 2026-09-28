from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import UserOut, UserCreate, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])

VALID_ROLES = ("naladchik", "pomoshchnik", "stager", "upakovshchik", "kladovshchik", "shift_lead", "admin")


@router.get("", response_model=list[UserOut])
def list_users(
    role: str | None = None,
    active: bool | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(User)
    if role is not None:
        q = q.filter(User.role == role)
    if active is not None:
        q = q.filter(User.active == active)
    return q.order_by(User.employee_code).all()


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    return u


@router.post("", response_model=UserOut)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    if payload.role not in VALID_ROLES:
        raise HTTPException(400, f"Недопустимая роль. Возможные: {', '.join(VALID_ROLES)}")

    if db.query(User).filter(User.employee_code == payload.employee_code).first():
        raise HTTPException(400, f"Табельный номер {payload.employee_code} уже занят")

    if payload.pin:
        if db.query(User).filter(User.pin == payload.pin).first():
            raise HTTPException(400, f"PIN {payload.pin} уже используется")

    u = User(
        full_name=payload.full_name,
        employee_code=payload.employee_code,
        role=payload.role,
        pin=payload.pin,
        active=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")

    if payload.role is not None:
        if payload.role not in VALID_ROLES:
            raise HTTPException(400, f"Недопустимая роль. Возможные: {', '.join(VALID_ROLES)}")
        u.role = payload.role

    if payload.employee_code is not None and payload.employee_code != u.employee_code:
        if db.query(User).filter(User.employee_code == payload.employee_code).first():
            raise HTTPException(400, f"Табельный номер {payload.employee_code} уже занят")
        u.employee_code = payload.employee_code

    if payload.pin is not None and payload.pin != u.pin:
        if payload.pin and db.query(User).filter(User.pin == payload.pin).first():
            raise HTTPException(400, f"PIN {payload.pin} уже используется")
        u.pin = payload.pin or None

    if payload.full_name is not None:
        u.full_name = payload.full_name
    if payload.active is not None:
        u.active = payload.active

    db.commit(); db.refresh(u)
    return u


@router.delete("/{user_id}", response_model=UserOut)
def deactivate_user(user_id: int, db: Session = Depends(get_db)):
    """Мягкое удаление: пользователь помечается неактивным, история сохраняется.
    Табельный номер остаётся за ним навсегда."""
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    u.active = False
    db.commit(); db.refresh(u)
    return u