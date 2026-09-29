from datetime import datetime
from jinja2 import Template
from .models import Box, Specification, LabelVariant, LabelTemplate, Shift, User


def _fmt_date(d: datetime) -> str:
    return d.strftime("%d.%m.%Y")


def _fmt_brutto(g: int | None) -> str:
    if g is None:
        return "-"
    return f"{g/1000:.1f}".replace(".", ",")


def _pack_info(quantity_packs: int | None, quantity_per_pack: int | None,
               quantity_total: int) -> str:
    if quantity_packs and quantity_per_pack:
        return f"{quantity_per_pack} шт/уп          {quantity_total} шт/кор"
    return f"{quantity_total} шт/кор"


def build_tspl(db, box: Box) -> str:
    spec: Specification = db.get(Specification, box.spec_id)
    variant: LabelVariant = db.get(LabelVariant, box.variant_id)
    template: LabelTemplate = db.get(LabelTemplate, variant.template_id)
    shift: Shift = db.get(Shift, box.shift_id)

    context = {
        "supplier": variant.supplier or "ООО «ИННТЕК»",
        "label_name": variant.label_name,
        "size_label": spec.size_label,
        "color": (spec.color or "").upper(),
        "barcode": variant.barcode or "",
        "external_sku": variant.external_sku or "",
        "producer_info": template.producer_info or "",
        "box_number_in_shift": box.box_number_in_shift or 0,
        "quantity_total": box.quantity_total,
        "quantity_packs": box.quantity_packs,
        "quantity_per_pack": box.quantity_per_pack,
        "pack_info": _pack_info(box.quantity_packs, box.quantity_per_pack, box.quantity_total),
        "weight_brutto": _fmt_brutto(box.weight_brutto_g),
        "packer_fio": box.packer_fio or "",
        "operator_fio": box.operator_fio or "",
        "date": _fmt_date(box.created_at),
        "shift_number": shift.shift_number if shift else "",
        "qr_content": box.qr_content,
        "batch_number": box.batch_number or "",
    }
    return Template(template.template_content).render(**context)

def build_tspl_for_run(db, boxes: list[Box]) -> str:
    """Собирает один TSPL со всеми этикетками партии.
    Каждая этикетка — полный блок (SIZE ... PRINT 1,1), они склеиваются через \\n.
    Принтер обрабатывает последовательно, печатает N штук подряд."""
    parts = []
    for box in boxes:
        parts.append(build_tspl(db, box))
    return "\n".join(parts)