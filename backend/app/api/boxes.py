from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..models import Box, Specification, LabelVariant, Shift, User, LabelTemplate, PrintJob
from ..schemas import BoxCreate, BoxOut
from ..label_builder import build_tspl
from ..services.printer_client import send_to_printer

router = APIRouter(prefix="/boxes", tags=["boxes"])


def _translit(s: str) -> str:
    table = {
        'А':'A','Б':'B','В':'V','Г':'G','Д':'D','Е':'E','Ё':'E','Ж':'Zh','З':'Z','И':'I','Й':'Y',
        'К':'K','Л':'L','М':'M','Н':'N','О':'O','П':'P','Р':'R','С':'S','Т':'T','У':'U','Ф':'F',
        'Х':'Kh','Ц':'Ts','Ч':'Ch','Ш':'Sh','Щ':'Shch','Ы':'Y','Э':'E','Ю':'Yu','Я':'Ya','ь':'','ъ':'',
    }
    out = []
    for ch in s:
        if ch.upper() in table:
            out.append(table[ch.upper()])
        elif ch.isalpha() or ch.isdigit():
            out.append(ch)
    return ''.join(out)


@router.post("", response_model=BoxOut)
def create_box(payload: BoxCreate, db: Session = Depends(get_db)):
    spec = db.get(Specification, payload.spec_id)
    if not spec:
        raise HTTPException(404, "Спецификация не найдена")
    variant = db.get(LabelVariant, payload.variant_id)
    if not variant:
        raise HTTPException(404, "Вариант этикетки не найден")
    shift = db.get(Shift, payload.shift_id)
    if not shift:
        raise HTTPException(404, "Смена не найдена")

    last_num = db.query(func.coalesce(func.max(Box.box_number_in_shift), 0)).filter(
        Box.shift_id == payload.shift_id
    ).scalar() or 0
    box_number = last_num + 1

    b = Box(
        box_barcode="TMP",
        qr_content="TMP",
        spec_id=payload.spec_id,
        variant_id=payload.variant_id,
        shift_id=payload.shift_id,
        box_number_in_shift=box_number,
        quantity_total=payload.quantity_total,
        quantity_packs=payload.quantity_packs,
        quantity_per_pack=payload.quantity_per_pack,
        packer_user_id=payload.packer_user_id,
        operator_user_id=payload.operator_user_id,
        weight_brutto_g=spec.weight_brutto_g,
    )
    db.add(b); db.flush()

    parts = [f"UID={b.box_uid:013d}", f"SKU={spec.sku_1c}"]
    if payload.quantity_packs and payload.quantity_per_pack:
        parts.append(f"PACKS={payload.quantity_packs}")
        parts.append(f"PER_PACK={payload.quantity_per_pack}")
    parts.append(f"TOTAL={payload.quantity_total}")
    if spec.film_sku:
        parts.append(f"MAT={spec.film_sku}")
    if spec.film_name:
        parts.append(f"MAT_NAME={spec.film_name}")

    packer = db.get(User, payload.packer_user_id) if payload.packer_user_id else None
    operator = db.get(User, payload.operator_user_id) if payload.operator_user_id else None
    if packer:
        parts.append(f"UPAK={_translit(packer.full_name)}")
        b.packer_fio = packer.full_name
    if operator:
        parts.append(f"NALAD={_translit(operator.full_name)}")
        b.operator_fio = operator.full_name

    parts.append(f"DATE={b.created_at.strftime('%Y-%m-%d') if b.created_at else ''}")
    b.qr_content = ";".join(parts)
    b.box_barcode = f"BOX-{datetime.utcnow():%Y%m%d}-{b.box_uid:06d}"

    db.commit(); db.refresh(b)
    return b


@router.get("", response_model=list[BoxOut])
def list_boxes(shift_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(Box)
    if shift_id:
        q = q.filter(Box.shift_id == shift_id)
    return q.order_by(Box.box_id.desc()).limit(200).all()


@router.post("/{box_id}/print")
def print_box(box_id: int, db: Session = Depends(get_db)):
    box = db.get(Box, box_id)
    if not box:
        raise HTTPException(404, "Коробка не найдена")

    variant = db.get(LabelVariant, box.variant_id)
    if not variant:
        raise HTTPException(404, "Вариант этикетки не найден")

    try:
        tspl = build_tspl(db, box)
    except Exception as e:
        job = PrintJob(
            box_id=box.box_id, variant_id=box.variant_id,
            status="failed", error_message=str(e), printer_id="unknown",
        )
        db.add(job); db.commit()
        raise HTTPException(500, f"Ошибка построения TSPL: {e}")

    # Пока только один принтер — профиль фиксирован.
    # Когда появится второй принтер — брать профиль из настроек/Machine.
    result = send_to_printer(tspl, profile="75x120")

    box.printed_at = datetime.utcnow()
    ok = result["status"] in ("saved", "queued")
    if ok:
        box.status = "labeled"

    job = PrintJob(
        template_id=variant.template_id,
        variant_id=variant.variant_id,
        box_id=box.box_id,
        status="printed" if ok else "failed",
        printer_id=result.get("mode", "unknown"),
        error_message=result.get("error"),
    )
    db.add(job); db.commit(); db.refresh(job)

    return {
        "job_id": job.job_id,
        "box_id": box.box_id,
        "transport": result["mode"],
        "status": result["status"],
        "details": result,
    }