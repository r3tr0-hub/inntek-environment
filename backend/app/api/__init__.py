from fastapi import APIRouter
from . import auth, shifts, specifications, boxes, variants, machines

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(shifts.router)
api_router.include_router(specifications.router)
api_router.include_router(variants.router)
api_router.include_router(machines.router)
api_router.include_router(boxes.router)