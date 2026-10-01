"""
Генератор TSPL из JSON-макета (layout_json).

Принимает JSON-описание макета (см. schemas.LayoutSchema) и словарь значений
переменных, возвращает готовую TSPL-программу (str). Кодирование в CP1251
произойдёт дальше — в форке LabelJetty (print_raw_tspl).

Ключевой момент — маппинг координат:

  * Холст в конструкторе — альбомный 960×600.
  * Печать — портретная этикетка 600×960.
  * Формула точки: X_tspl = LY, Y_tspl = 960 − LX.

Для TEXT / QRCODE / BARCODE команда отправляется с rotation=270 — принтер сам
поворачивает содержимое, координаты X,Y берутся по формуле.
Для BAR/BOX у TSPL нет rotation, поэтому линия и рамка рисуются через BOX,
а координаты углов считаются в портретную систему вручную.
"""

from __future__ import annotations

import re
from typing import Any

from .validators import validate_ean13

# Итоговый размер портретной этикетки (75×120 мм @ 203 dpi).
LABEL_PORTRAIT_WIDTH = 600
LABEL_PORTRAIT_HEIGHT = 960

# Дефолты для QR-кода и штрихкода (совпадают с дефолтами схемы).
DEFAULT_QR_ECC = "M"
DEFAULT_QR_MODEL = "M2"
DEFAULT_QR_MASK = "S8"
DEFAULT_QR_CELL = 5
DEFAULT_QR_MODE = "A"          # авто-режим кодирования — оптимален для принтера

DEFAULT_EAN13_NARROW = 2
DEFAULT_EAN13_WIDE = 4

# Символы, которые TSPL-команды не пропустят внутри строковых литералов.
_UNSAFE_QUOTE = re.compile(r'"')
# Простая проверка «{{variable}}» в тексте.
_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


def generate_tspl(layout: dict[str, Any], data: dict[str, Any]) -> str:
    """Собирает полную TSPL-программу по JSON-макету и данным коробки.

    :param layout: layout_json из LabelTemplate (совместим со схемой LayoutSchema)
    :param data:   словарь {имя_переменной: строковое_значение}
    :return:       полная TSPL-программа (str), готовая к кодированию в CP1251
    """
    if not isinstance(layout, dict):
        raise ValueError("layout должен быть словарём")
    if layout.get("version") != 1:
        raise ValueError(f"неподдерживаемая версия layout: {layout.get('version')!r}")

    elements = layout.get("elements") or []
    if not isinstance(elements, list):
        raise ValueError("layout.elements должен быть списком")

    parts: list[str] = []
    parts.append("SIZE 75 mm, 120 mm")
    parts.append("GAP 2 mm, 0 mm")
    parts.append("DIRECTION 0")
    parts.append("REFERENCE 0,0")
    parts.append("CLS")
    parts.append('CODEPAGE "1251"')
    parts.append("")  # пустая строка — визуальный разделитель

    for el in elements:
        try:
            cmd = _render_element(el, data)
        except Exception as e:
            raise ValueError(f"ошибка в элементе {el.get('id', '?')}: {e}") from e
        if cmd:
            parts.append(cmd)

    parts.append("PRINT 1,1")
    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
#  Внутренние функции
# ─────────────────────────────────────────────────────────────────────────────

def _render_element(el: dict[str, Any], data: dict[str, Any]) -> str | None:
    """Рендерит один элемент в TSPL-команду (или None, если нечего рисовать)."""
    t = el.get("type")
    if t == "text":
        return _render_text(el, data)
    if t == "qr":
        return _render_qr(el, data)
    if t == "barcode":
        return _render_barcode(el, data)
    if t == "line":
        return _render_line(el)
    if t == "rect":
        return _render_rect(el)
    raise ValueError(f"неизвестный тип элемента: {t!r}")


def _substitute(text: str, data: dict[str, Any]) -> str:
    """Подставляет {{var}} из data. Неизвестные переменные → пустая строка."""
    if not text:
        return ""
    return _VAR_RE.sub(lambda m: str(data.get(m.group(1), "")), text)


def _sanitize(text: str) -> str:
    """Убирает двойные кавычки — они сломают строковый литерал TSPL."""
    return _UNSAFE_QUOTE.sub("'", text or "")


def _to_tspl_xy(lx: int, ly: int) -> tuple[int, int]:
    """Маппинг альбомной точки (LX, LY) в портретные координаты TSPL."""
    return (ly, LABEL_PORTRAIT_HEIGHT - lx)


# ─── TEXT ───────────────────────────────────────────────────────────────────

def _render_text(el: dict[str, Any], data: dict[str, Any]) -> str | None:
    content = _substitute(el.get("text", ""), data)
    if not content.strip():
        return None
    content = _sanitize(content)

    lx = int(el["x"])
    ly = int(el["y"])
    x_tspl, y_tspl = _to_tspl_xy(lx, ly)

    font = str(el.get("fontName", "3"))
    if font not in {"1", "2", "3", "4", "5"}:
        raise ValueError(f"недопустимый fontName: {font!r}")

    xmul = int(el.get("xMul", 1))
    ymul = int(el.get("yMul", 1))
    rotation = int(el.get("rotation", 270))

    # alignment применяется при движке TSPL неявно через точку привязки;
    # здесь оставляем выравнивание как есть (в схеме оно есть, но у TSPL
    # нет параметра alignment — при необходимости его учитывать надо
    # менять X, что мы и делали в UI. Значение alignment сохраняем для
    # совместимости, но оно не влияет на TSPL-команду.)
    return (
        f'TEXT {x_tspl},{y_tspl},"{font}",{rotation},'
        f'{xmul},{ymul},"{content}"'
    )


# ─── QR ─────────────────────────────────────────────────────────────────────

def _render_qr(el: dict[str, Any], data: dict[str, Any]) -> str | None:
    content = _substitute(el.get("content", ""), data)
    if not content.strip():
        return None
    content = _sanitize(content)

    lx = int(el["x"])
    ly = int(el["y"])
    x_tspl, y_tspl = _to_tspl_xy(lx, ly)

    ecc = str(el.get("ecc", DEFAULT_QR_ECC))
    if ecc not in {"L", "M", "Q", "H"}:
        raise ValueError(f"недопустимый ecc: {ecc!r}")

    model = str(el.get("model", DEFAULT_QR_MODEL))
    if model not in {"M1", "M2"}:
        raise ValueError(f"недопустимый model: {model!r}")

    mask = str(el.get("mask", DEFAULT_QR_MASK))
    if not re.fullmatch(r"S[0-8]", mask):
        raise ValueError(f"недопустимый mask: {mask!r}")

    cell = int(el.get("cell", DEFAULT_QR_CELL))
    if not (1 <= cell <= 10):
        raise ValueError(f"cell вне диапазона 1..10: {cell}")

    rotation = int(el.get("rotation", 270))

    # Синтаксис: QRCODE X,Y,ecc,cell,mode,rotation,model,mask,"data"
    return (
        f'QRCODE {x_tspl},{y_tspl},{ecc},{cell},{DEFAULT_QR_MODE},'
        f'{rotation},{model},{mask},"{content}"'
    )


# ─── BARCODE ────────────────────────────────────────────────────────────────

def _render_barcode(el: dict[str, Any], data: dict[str, Any]) -> str | None:
    content = _substitute(el.get("content", ""), data)
    if not content.strip():
        return None
    content = _sanitize(content)

    lx = int(el["x"])
    ly = int(el["y"])
    x_tspl, y_tspl = _to_tspl_xy(lx, ly)

    bc_type = str(el.get("barcodeType", "EAN13"))
    if bc_type != "EAN13":
        raise ValueError(f"пока поддерживается только EAN13, получено {bc_type!r}")

    # Проверяем контрольную сумму — печатать мусорный EAN-13 нельзя.
    if not validate_ean13(content):
        raise ValueError(
            f"EAN-13 {content!r} не проходит проверку контрольной суммы"
        )

    height = int(el.get("height", 60))
    human = 1 if el.get("humanReadable", True) else 0
    rotation = int(el.get("rotation", 270))

    # Синтаксис: BARCODE X,Y,"type",height,readable,rotation,narrow,wide,"data"
    return (
        f'BARCODE {x_tspl},{y_tspl},"EAN13",{height},{human},'
        f'{rotation},{DEFAULT_EAN13_NARROW},{DEFAULT_EAN13_WIDE},"{content}"'
    )


# ─── LINE ───────────────────────────────────────────────────────────────────

def _render_line(el: dict[str, Any]) -> str | None:
    x1 = int(el["x1"]); y1 = int(el["y1"])
    x2 = int(el["x2"]); y2 = int(el["y2"])
    if x1 == x2 and y1 == y2:
        return None  # точка, не линия

    xa, ya = _to_tspl_xy(x1, y1)
    xb, yb = _to_tspl_xy(x2, y2)
    thickness = max(1, int(el.get("thickness", 2)))

    # У TSPL нет «линии» — используем BOX между двумя точками.
    # При xa==xb или ya==yb получается линия; в остальных случаях — тонкий
    # прямоугольник, что визуально то же самое.
    return f"BOX {xa},{ya},{xb},{yb},{thickness}"


# ─── RECT ───────────────────────────────────────────────────────────────────

def _render_rect(el: dict[str, Any]) -> str | None:
    x = int(el["x"]); y = int(el["y"])
    w = int(el["width"]); h = int(el["height"])
    if w <= 0 or h <= 0:
        return None

    # Углы в альбоме: (x, y) и (x+w, y+h).
    x1, y1 = _to_tspl_xy(x, y)
    x2, y2 = _to_tspl_xy(x + w, y + h)

    thickness = max(1, int(el.get("thickness", 2)))
    return f"BOX {x1},{y1},{x2},{y2},{thickness}"