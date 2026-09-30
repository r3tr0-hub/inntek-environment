"""
Справочник переменных, доступных в макете этикетки.

Используется:
  - в UI конструктора (палитра переменных и предпросмотр),
  - в будущем генераторе TSPL (подстановка значений).

Файл не знает про БД — просто статический список.
"""

from dataclasses import dataclass
from typing import Literal


VariableGroup = Literal["Specification", "LabelVariant", "Box", "LabelTemplate"]


@dataclass(frozen=True)
class Variable:
    """Описание одной переменной."""
    name: str
    label: str
    group: VariableGroup
    example: str
    description: str = ""


# Порядок элементов в кортеже = порядок в палитре конструктора.
VARIABLES: tuple[Variable, ...] = (
    # --- Specification --------------------------------------------------
    Variable("sku",                  "Артикул 1С",           "Specification", "00-00000000"),
    Variable("name_1c",              "Наименование",         "Specification", "Пакет курьерский 250x400+35"),
    Variable("size_label",           "Размер",               "Specification", "250x400+35"),
    Variable("format",               "Формат",               "Specification", "A4"),
    Variable("perforation",          "Перфорация",           "Specification", "2П"),
    Variable("color",                "Цвет",                 "Specification", "БЕЛЫЙ"),

    # --- LabelVariant ---------------------------------------------------
    Variable("label_name",           "Название этикетки",    "LabelVariant",  "Вайлдберриз 250x400+35"),
    Variable("barcode",              "Штрихкод EAN-13",      "LabelVariant",  "2000000000017"),
    Variable("external_sku",         "Артикул СДЭК",         "LabelVariant",  "CDEK-0001"),
    Variable("supplier",             "Поставщик",            "LabelVariant",  "ООО «ИННТЕК»"),

    # --- Box ------------------------------------------------------------
    Variable("qr_content",           "QR-контент",           "Box",           "INNTEK|SKU|0001|..."),
    Variable("box_number_in_shift",  "Номер коробки в смене","Box",           "1"),
    Variable("box_uid",              "UID коробки",          "Box",           "abc-123-def"),
    Variable("quantity_total",       "Всего, шт",            "Box",           "1000"),
    Variable("quantity_packs",       "Упаковок",             "Box",           "10"),
    Variable("quantity_per_pack",    "В упаковке",           "Box",           "100"),
    Variable("quantity_packs_text",  "Упаковки текстом",     "Box",           "10 уп × 100 шт"),
    Variable("weight_brutto",        "Вес, кг (с запятой)",  "Box",           "9,3"),
    Variable("weight_brutto_g",      "Вес, г",               "Box",           "9300"),
    Variable("packer_fio",           "ФИО упаковщика",       "Box",           "Иванов И.И."),
    Variable("operator_fio",         "ФИО оператора",        "Box",           "Петров П.П."),
    Variable("employee_code_packer", "Табельный упаковщика", "Box",           "001"),
    Variable("employee_code_operator","Табельный оператора", "Box",           "002"),
    Variable("date",                 "Дата (ДД.ММ.ГГГГ)",    "Box",           "26.09.2026"),
    Variable("date_short",           "Дата (ДД.ММ)",         "Box",           "26.09"),
    Variable("batch_number",         "Номер партии",         "Box",           "КП-А4-2П-26092026"),
    Variable("shift_number",         "Смена",                "Box",           "1"),

    # --- LabelTemplate --------------------------------------------------
    Variable("producer_info",        "Информация о производителе", "LabelTemplate", "ООО «ИННТЕК», г. Москва"),
)


VARIABLE_NAMES: frozenset[str] = frozenset(v.name for v in VARIABLES)


def get_example_values() -> dict[str, str]:
    """Словарь {имя: пример}. Используется для предпросмотра в конструкторе."""
    return {v.name: v.example for v in VARIABLES}