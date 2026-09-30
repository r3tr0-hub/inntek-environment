"""
Pydantic-схемы JSON-макета этикетки.

Все координаты и размеры — в точках TSPL (целые числа).
Холст конструктора — альбомный 960×600 (ширина × высота).
При генерации TSPL элементы будут пересчитаны в портретную систему 600×960
по формуле X_tspl = LY, Y_tspl = 960 − LX (для элементов с rotation=270).

Этот модуль не знает про БД и TSPL — только описывает формат данных.
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


# --- Константы формата ---------------------------------------------------

# Этикетка 75×120 мм при 203 dpi (8 точек/мм) = 600×960 точек.
LABEL_PORTRAIT_WIDTH_DOTS = 600
LABEL_PORTRAIT_HEIGHT_DOTS = 960

# Альбомный холст в UI: ширина = высота портрета, высота = ширина портрета.
CANVAS_WIDTH_DOTS = LABEL_PORTRAIT_HEIGHT_DOTS   # 960
CANVAS_HEIGHT_DOTS = LABEL_PORTRAIT_WIDTH_DOTS   # 600

LAYOUT_FORMAT_VERSION = 1


# --- Холст ---------------------------------------------------------------

class CanvasSchema(BaseModel):
    """Параметры холста. Пока фиксированные, но вынесены в JSON на будущее."""
    width: int = CANVAS_WIDTH_DOTS
    height: int = CANVAS_HEIGHT_DOTS
    units: Literal["dots"] = "dots"
    orientation: Literal["landscape"] = "landscape"


# --- Элементы ------------------------------------------------------------

class TextElement(BaseModel):
    """
    Текстовый элемент. Поле text может быть:
      - статикой: "Курьерский пакет"
      - чистой переменной: "{{sku}}"
      - шаблоном: "Коробка № {{box_number_in_shift}}"
    """
    type: Literal["text"]
    id: str
    x: int
    y: int
    width: int
    height: int
    text: str = ""
    # Встроенные шрифты TSPL: "1"=8×12, "2"=12×20, "3"=16×24, "4"=24×32, "5"=32×48
    fontName: Literal["1", "2", "3", "4", "5"] = "3"
    xMul: int = Field(default=1, ge=1, le=10)
    yMul: int = Field(default=1, ge=1, le=10)
    rotation: int = 270
    alignment: Literal["left", "center", "right"] = "left"


class QrElement(BaseModel):
    """QR-код. Дефолты — проверенная на принтере комбинация."""
    type: Literal["qr"]
    id: str
    x: int
    y: int
    content: str  # обычно "{{qr_content}}"
    size: int = 120
    model: Literal["M1", "M2"] = "M2"
    ecc: Literal["L", "M", "Q", "H"] = "M"
    cell: int = Field(default=5, ge=1, le=10)
    mask: Literal["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"] = "S8"
    rotation: int = 270


class BarcodeElement(BaseModel):
    """Штрихкод. Пока только EAN-13 (13 цифр + проверка контрольной суммы)."""
    type: Literal["barcode"]
    id: str
    x: int
    y: int
    content: str  # обычно "{{barcode}}"
    barcodeType: Literal["EAN13"] = "EAN13"
    height: int = 60
    humanReadable: bool = True
    rotation: int = 270


class LineElement(BaseModel):
    """
    Линия. Координаты — в альбомной системе холста (960×600).
    Маппинг в TSPL: BAR/BOX не поддерживают rotation, поэтому
    пересчёт координат для линий/рамок — отдельная задача Этапа 4.
    Сейчас поля только описывают геометрию в UI.
    """
    type: Literal["line"]
    id: str
    x1: int
    y1: int
    x2: int
    y2: int
    thickness: int = 2


class RectElement(BaseModel):
    """Прямоугольник (рамка). Координаты — в альбомной системе холста."""
    type: Literal["rect"]
    id: str
    x: int
    y: int
    width: int
    height: int
    thickness: int = 2


# Discriminated union по полю "type" — Pydantic сам выберет нужную модель.
Element = Annotated[
    Union[TextElement, QrElement, BarcodeElement, LineElement, RectElement],
    Field(discriminator="type"),
]


# --- Корневая схема ------------------------------------------------------

class LayoutSchema(BaseModel):
    """Корневая схема JSON-макета этикетки."""
    version: int = LAYOUT_FORMAT_VERSION
    canvas: CanvasSchema = Field(default_factory=CanvasSchema)
    elements: list[Element] = Field(default_factory=list)