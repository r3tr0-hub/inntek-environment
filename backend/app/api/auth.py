from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..database import get_db
from ..models import User

router = APIRouter(prefix="/auth", tags=["auth"])

class LoginIn(BaseModel):
    pin: str

@router.post("/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.pin == payload.pin, User.active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="Неверный PIN или неактивный пользователь")
    # TODO: вернуть JWT
    return {"user_id": user.user_id, "full_name": user.full_name, "role": user.role}