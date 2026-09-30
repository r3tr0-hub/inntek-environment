"""
HTTP-роутер конструктора макетов этикеток.

Эндпоинты:
  GET  /label-designer                       — HTML-страница конструктора
  GET  /api/label-designer/variables         — список переменных
  GET  /api/label-designer/layout/{id}       — загрузить layout_json
  PUT  /api/label-designer/layout/{id}       — сохранить layout_json
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import LabelTemplate

from ..services.label_designer.schemas import LayoutSchema
from ..services.label_designer.variables import VARIABLES, get_example_values


router = APIRouter(tags=["label-designer"])

# Путь до статики конструктора.
# file: app/api/label_designer.py → parent.parent = app → /static/label_designer
STATIC_DIR = Path(__file__).resolve().parent.parent / "static" / "label_designer"


# --- HTML-страница -------------------------------------------------------

@router.get("/label-designer", include_in_schema=False)
def get_designer_page(
    # requester_pin пока не проверяется. Параметр заложен на будущее,
    # чтобы URL-форма была такой же, как у отчётов.
    requester_pin: str | None = Query(default=None),
) -> FileResponse:
    """Отдаёт HTML-страницу конструктора."""
    html_path = STATIC_DIR / "designer.html"
    if not html_path.exists():
        raise HTTPException(status_code=500, detail="designer.html не найден")
    return FileResponse(html_path, media_type="text/html")


# --- Справочник переменных ----------------------------------------------

@router.get("/api/label-designer/variables")
def list_variables() -> dict:
    """
    Список переменных для палитры конструктора.
    Плюс example_values — словарь примеров для предпросмотра.
    """
    return {
        "variables": [
            {
                "name": v.name,
                "label": v.label,
                "group": v.group,
                "example": v.example,
                "description": v.description,
            }
            for v in VARIABLES
        ],
        "example_values": get_example_values(),
    }


# --- Макет --------------------------------------------------------------

@router.get("/api/label-designer/layout/{template_id}")
def get_layout(template_id: int, db: Session = Depends(get_db)) -> dict:
    """Возвращает layout_json указанного шаблона."""
    template = db.get(LabelTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    if template.layout_json is None:
        raise HTTPException(status_code=404, detail="У шаблона нет layout_json")
    return template.layout_json


@router.put("/api/label-designer/layout/{template_id}")
def save_layout(
    template_id: int,
    layout: LayoutSchema,
    db: Session = Depends(get_db),
) -> dict:
    """
    Сохраняет layout_json у шаблона.
    Структуру валидирует Pydantic (LayoutSchema). При ошибке FastAPI сам вернёт 422.
    """
    template = db.get(LabelTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")

    # mode="json" — на всякий случай приводим к JSON-совместимым типам
    # (например, если появятся Enum'ы). Сейчас все поля уже примитивные.
    template.layout_json = layout.model_dump(mode="json")
    db.commit()
    db.refresh(template)
    return {"status": "ok", "template_id": template_id}