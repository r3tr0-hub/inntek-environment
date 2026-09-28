from sqlalchemy.orm import Session
from .models import User, Specification, LabelTemplate, LabelVariant, Machine

USERS = [
    ("Тестовый Наладчик",   "naladchik",     "1001", "0001"),
    ("Тестовый Упаковщик 1","upakovshchik",  "1002", "0002"),
    ("Тестовый Упаковщик 2","upakovshchik",  "1003", "0003"),
    ("Тестовый Упаковщик 3","upakovshchik",  "1004", "0004"),
    ("Тестовый Помощник",   "pomoshchnik",   "1005", "0005"),
]

MACHINES = [
    ("КП1", "Станок КП1"),
    ("КП2", "Станок КП2"),
    ("КП3", "Станок КП3"),
    ("КП4", "Станок КП4"),
    ("КП5", "Станок КП5"),
]

PACKS = [
    ("00-00007692", "Курьерский пакет 160х255+30 QR", "160x255+30", "чёрно-белый", 50),
    ("00-00006215", "Курьерский пакет 250х400+35 QR", "250x400+35", "чёрно-белый", 45),
    ("00-00006451", "Курьерский пакет 450х650+40 QR", "450x650+40", "чёрно-белый", 50),
    ("00-00006972", "Курьерский пакет СДЭК 160х230+40 мм, 45 мкм ЛАЙТ А5", "160x230+40", "чёрно-белый", 45),
    ("00-00006971", "Курьерский пакет СДЭК 260х340+40 мм, 45 мкм ЛАЙТ А4", "260x340+40", "чёрно-белый", 45),
    ("00-00007955", "Курьерский пакет СДЭК 260х340+50 мм, 45 мкм ЛАЙТ А4", "260x340+50", "чёрно-белый", 45),
    ("00-00007667", "Курьерский пакет, 120х400+40, без кармана, 45 мкм", "120x400+40", "чёрно-белый", 45),
    ("00-00000706", "Курьерский пакет, 150х240+40, без кармана, 45 мкм", "150x240+40", "чёрно-белый", 45),
    ("00-00000709", "Курьерский пакет, 170х240+40, без кармана, 45 мкм", "170x240+40", "чёрно-белый", 45),
]

FILMS = {
    "00-00007643": "ПОФ 0,040х450(455)/210 (черно-белая)",
    "00-00007644": "ПОФ 0,040х510(515)/240 (черно-белая)",
    "00-00008647": "ПОФ 0,040х835 (черно-белая)",
    "00-00007001": "ПОФ 0,045х450 СДЭК (черно-белая)",
    "00-00007410": "ПОФ 0,043х835/400 (черно-белая)",
}

# ── TSPL-шаблоны (альбомная ориентация) ──
# Физическая этикетка 75×120 мм (портрет), но контент повёрнут на 90° так,
# что читается при повороте этикетки против часовой стрелки.
# Формула: X_tspl = LY, Y_tspl = 960 - LX, rotation = 270 для всех команд.
# LY — расстояние от левого края в альбоме (в точках), LX — от верхнего.

TEMPLATE_VBK = """SIZE 75 mm, 120 mm
GAP 2 mm, 0 mm
DIRECTION 0
REFERENCE 0,0
CLS
CODEPAGE "1251"

TEXT 30,930,"2",270,1,1,"Поставщик: {{supplier}}"
TEXT 70,930,"3",270,2,2,"Курьерский пакет"
TEXT 120,930,"3",270,2,2,"Курьерпак"
TEXT 175,930,"3",270,2,2,"{{label_name}}"
BARCODE 230,900,"EAN13",60,1,270,2,4,"{{barcode}}"

TEXT 340,930,"5",270,1,1,"Коробка № {{box_number_in_shift}}"
TEXT 430,930,"2",270,1,1,"Количество {{quantity_total}}шт, Вес БРУТТО - {{weight_brutto}} кг"
TEXT 480,930,"2",270,1,1,"Размер: {{size_label}}"
TEXT 510,930,"2",270,1,1,"Дата: {{date}}"
TEXT 545,930,"2",270,1,1,"{{packer_fio}} / {{operator_fio}} / смена {{shift_number}}"

QRCODE 380,240,L,4,A,270,M2,S8,"{{qr_content}}"
PRINT 1,1
"""

TEMPLATE_MP = """SIZE 75 mm, 120 mm
GAP 2 mm, 0 mm
DIRECTION 0
REFERENCE 0,0
CLS
CODEPAGE "1251"

TEXT 30,930,"3",270,2,2,"Курьерский пакет"
TEXT 100,930,"3",270,1,1,"{{color}}"
TEXT 180,760,"5",270,1,1,"{{size_label}}"
TEXT 300,930,"2",270,1,1,"{{pack_info}}"
TEXT 360,930,"2",270,1,1,"Дата упаковки:  {{date}}"
TEXT 410,930,"2",270,1,1,"Упаковщик:      {{packer_fio}}"
TEXT 460,930,"2",270,1,1,"Оператор:       {{operator_fio}}"
TEXT 510,930,"2",270,1,1,"Смена:          {{shift_number}}"

QRCODE 380,240,L,4,A,270,M2,S8,"{{qr_content}}"
PRINT 1,1
"""

TEMPLATE_CDEK = """SIZE 75 mm, 120 mm
GAP 2 mm, 0 mm
DIRECTION 0
REFERENCE 0,0
CLS
CODEPAGE "1251"

TEXT 30,930,"2",270,1,1,"Артикул СДЭК: {{external_sku}}"
TEXT 70,930,"3",270,1,1,"{{label_name}}"
TEXT 130,930,"2",270,1,1,"{{producer_info}}"
TEXT 220,930,"2",270,1,1,"Количество: {{quantity_total}} шт"
TEXT 260,930,"2",270,1,1,"Номер партии: {{batch_number}}"
TEXT 300,930,"2",270,1,1,"Дата производства: {{date}}"
TEXT 340,930,"2",270,1,1,"Упаковщик: {{packer_fio}}"
TEXT 380,930,"2",270,1,1,"Оператор: {{operator_fio}}"
TEXT 420,930,"2",270,1,1,"Смена: {{shift_number}}"

QRCODE 380,240,L,4,A,270,M2,S8,"{{qr_content}}"
PRINT 1,1
"""

TEMPLATES = [
    ("VBK", "ВБ Контракт", TEMPLATE_VBK),
    ("MP", "Маркетплейс", TEMPLATE_MP),
    ("CDEK", "СДЭК", TEMPLATE_CDEK,
     "ООО «ИННТЕК», 170032, г.Тверь, посёлок Новое Власьево, 14с1"),
]

# Маппинг: (sku_1c, код шаблона, label_name, barcode, external_sku)
VARIANTS = [
    ("00-00007692", "VBK", "Вайлдберриз 160x255+30", None, None),
    ("00-00006215", "VBK", "Вайлдберриз 250x400+35", None, None),
    ("00-00006451", "VBK", "Вайлдберриз 450x650+40", None, None),
    ("00-00006972", "CDEK", "Пакет курьерский «Лайт» А5", None, "001972"),
    ("00-00006971", "CDEK", "Пакет курьерский «Лайт» А4", None, "001973"),
    ("00-00007955", "CDEK", "Пакет курьерский «Лайт» А4", None, "001973"),
    ("00-00007667", "MP", "120x400+40", None, None),
    ("00-00000706", "MP", "150x240+40", None, None),
    ("00-00000709", "MP", "170x240+40", None, None),
]


def seed(db: Session):
    if db.query(User).count() == 0:
        for name, role, pin, emp_code in USERS:
            db.add(User(full_name=name, role=role, pin=pin, employee_code=emp_code))

    if db.query(LabelTemplate).count() == 0:
        for t in TEMPLATES:
            code, name, content, *rest = t
            db.add(LabelTemplate(
                code=code, name=name, template_content=content,
                producer_info=(rest[0] if rest else None),
            ))

    from .models import Machine  # добавь импорт вверху файла
    if db.query(Machine).count() == 0:
        for code, name in MACHINES:
            db.add(Machine(code=code, name=name))

    if db.query(Specification).count() == 0:
        for sku, name in FILMS.items():
            db.add(Specification(
                sku_1c=sku, name_1c=name, size_label="-", color="чёрно-белый",
            ))
        for sku, name, size, color, thickness in PACKS:
            db.add(Specification(
                sku_1c=sku, name_1c=name, size_label=size, color=color,
                thickness_mkm=thickness,
            ))
    db.commit()

    # Варианты этикеток — создаём после того, как спецификации и шаблоны есть
    if db.query(LabelVariant).count() == 0:
        spec_by_sku = {s.sku_1c: s for s in db.query(Specification).all()}
        tpl_by_code = {t.code: t for t in db.query(LabelTemplate).all()}
        for sku, tpl_code, label_name, barcode, ext_sku in VARIANTS:
            spec = spec_by_sku.get(sku)
            tpl = tpl_by_code.get(tpl_code)
            if not spec or not tpl:
                continue
            db.add(LabelVariant(
                spec_id=spec.spec_id, template_id=tpl.template_id,
                label_name=label_name, barcode=barcode, external_sku=ext_sku,
                supplier="ООО «ИННТЕК»",
            ))
        db.commit()