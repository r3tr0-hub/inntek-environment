"""Утилиты валидации, специфичные для этикеток.

Вынесено отдельно, чтобы использовать в двух местах: при сохранении
LabelVariant (app/api/variants.py) и в генераторе TSPL.
"""


def validate_ean13(barcode: str) -> bool:
    """Проверяет EAN-13: 13 цифр + контрольная сумма.

    Алгоритм: для первых 12 цифр, считая позиции слева направо с 1,
    цифры на нечётных позициях (1, 3, 5, 7, 9, 11) идут с весом 1,
    на чётных (2, 4, 6, 8, 10, 12) — с весом 3. Контрольная цифра — то,
    что нужно добавить к сумме, чтобы она стала кратной 10.
    """
    if not isinstance(barcode, str):
        return False
    if len(barcode) != 13 or not barcode.isdigit():
        return False

    total = 0
    for i, ch in enumerate(barcode[:12]):
        # i = 0 соответствует позиции 1 (вес 1)
        weight = 1 if i % 2 == 0 else 3
        total += int(ch) * weight

    check_digit = (10 - total % 10) % 10
    return int(barcode[12]) == check_digit


def ean13_error_message(barcode: str) -> str:
    """Человекочитаемая причина, почему штрихкод не валиден."""
    if not isinstance(barcode, str):
        return "штрихкод должен быть строкой"
    if len(barcode) != 13:
        return f"EAN-13 должен содержать ровно 13 цифр, получено {len(barcode)}"
    if not barcode.isdigit():
        return "EAN-13 может содержать только цифры 0-9"
    return "неверная контрольная сумма EAN-13"