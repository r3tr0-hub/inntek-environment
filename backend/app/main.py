from fastapi import FastAPI
from .database import Base, engine, SessionLocal
from .api import api_router
from .seed import seed

app = FastAPI(title="INNTEK ENVIRONMENT", version="0.1.0")

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()

@app.get("/")
def root():
    return {"service": "INNTEK ENVIRONMENT", "status": "ok"}

app.include_router(api_router)