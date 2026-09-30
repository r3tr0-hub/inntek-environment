from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..models import (
    Box, Specification, LabelVariant, Shift, User, Machine,
    ShiftAssignment, PrintJob, LabelTemplate, Pallet,
)

from ..schemas import BoxCreate, BoxOut, BoxQuarantine, BoxCancel, BoxScanIn, BoxScanOut
from ..label_builder import build_tspl
from ..services.printer_client import send_to_printer

router = APIRouter(prefix="/boxes", tags=["boxes"])

VALID_QUARANTINE_REASONS = {
    "брак: адгезия клапана", "брак: шов", "брак: слипание",
    "брак: складки", "брак: геометрия", "брак: QR-код",
    "ошибка оператора", "пересортица", "пересчёт", "другое",
}


# ─── Создание коробки ───

def _build_qr_content(box: Box, spec: Specification, payload: BoxCreate,
                     packer: User | None, operator: User | None) -> str:
    parts = [f"UID={box.box_uid:013d}", f"SKU={spec.sku_1c}"]
    if payload.quantity_packs and payload.quantity_per_pack:
        parts.append(f"PACKS={payload.quantity_packs}")
        parts.append(f"PER_PACK={payload.quantity_per_pack}")
    parts.append(f"TOTAL={payload.quantity_total}")
    if spec.film_sku:
        parts.append(f"MAT={spec.film_sku}")
    if spec.film_name:
        parts.append(f"MAT_NAME={spec.film_name}")
    if packer:
        parts.append(f"UPAK={packer.employee_code}")
    if operator:
        parts.append(f"NALAD={operator.employee_code}")
    parts.append(f"DATE={datetime.utcnow():%Y-%m-%d}")
    return ";".join(parts)


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
    machine = db.get(Machine, payload.machine_id)
    if not machine:
        raise HTTPException(404, "Станок не найден")

    packer_assignment = db.query(ShiftAssignment).filter(
        ShiftAssignment.shift_id == payload.shift_id,
        ShiftAssignment.machine_id == payload.machine_id,
        ShiftAssignment.role_in_shift == "upakovshchik",
        ShiftAssignment.to_time.is_(None),
    ).order_by(ShiftAssignment.from_time).first()
    if not packer_assignment:
        raise HTTPException(400, f"На станке {machine.code} нет активного упаковщика")

    packer = db.get(User, packer_assignment.user_id)

    operator_assignment = db.query(ShiftAssignment).filter(
        ShiftAssignment.shift_id == payload.shift_id,
        ShiftAssignment.role_in_shift == "operator",
        ShiftAssignment.to_time.is_(None),
    ).first()
    operator = db.get(User, operator_assignment.user_id) if operator_assignment else None

    last_num = db.query(func.coalesce(func.max(Box.box_number_in_shift), 0)).filter(
        Box.shift_id == payload.shift_id
    ).scalar() or 0
    box_number = last_num + 1

    b = Box(
        box_barcode="TMP", qr_content="TMP",
        spec_id=payload.spec_id, variant_id=payload.variant_id,
        shift_id=payload.shift_id, machine_id=payload.machine_id,
        box_number_in_shift=box_number,
        quantity_total=payload.quantity_total,
        quantity_packs=payload.quantity_packs,
        quantity_per_pack=payload.quantity_per_pack,
        packer_user_id=packer.user_id if packer else None,
        operator_user_id=operator.user_id if operator else None,
        weight_brutto_g=spec.weight_brutto_g,
    )
    db.add(b); db.flush()

    b.qr_content = _build_qr_content(b, spec, payload, packer, operator)
    b.box_barcode = f"BOX-{datetime.utcnow():%Y%m%d}-{b.box_uid:06d}"
    if packer:
        b.packer_fio = packer.full_name
    if operator:
        b.operator_fio = operator.full_name

    db.commit(); db.refresh(b)
    return b


# ─── Список и карточка ───

@router.get("", response_model=list[BoxOut])
def list_boxes(
    shift_id: int | None = None,
    machine_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(Box)
    if shift_id is not None:
        q = q.filter(Box.shift_id == shift_id)
    if machine_id is not None:
        q = q.filter(Box.machine_id == machine_id)
    if status:
        q = q.filter(Box.status == status)
    return q.order_by(Box.box_id.desc()).limit(500).all()


@router.get("/{box_id}", response_model=BoxOut)
def get_box(box_id: int, db: Session = Depends(get_db)):
    b = db.get(Box, box_id)
    if not b:
        raise HTTPException(404, "Коробка не найдена")
    return b


# ─── Печать ───

def _check_operator_shift(box: Box, db: Session) -> None:
    """Проверка: коробка в открытой смене."""
    shift = db.get(Shift, box.shift_id)
    if not shift or shift.status != "open":
        raise HTTPException(400, "Смена не открыта — операция невозможна")


def _do_print(box: Box, db: Session) -> dict:
    """Общая логика печати TSPL через LabelJetty."""
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

    result = send_to_printer(tspl, profile="75x120")
    ok = result["status"] in ("saved", "queued")

    if ok:
        box.printed_at = datetime.utcnow()
        box.status = "printed"

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


@router.post("/{box_id}/print")
def print_box(box_id: int, db: Session = Depends(get_db)):
    box = db.get(Box, box_id)
    if not box:
        raise HTTPException(404, "Коробка не найдена")
    if box.status not in ("created", "printed"):
        raise HTTPException(400, f"Нельзя печатать коробку в статусе {box.status}")
    _check_operator_shift(box, db)
    return _do_print(box, db)


# ─── Перепечатка (старая → cancelled, новая коробка с новым UID) ───

@router.post("/{box_id}/reprint", response_model=BoxOut)
def reprint_box(box_id: int, db: Session = Depends(get_db)):
    old = db.get(Box, box_id)
    if not old:
        raise HTTPException(404, "Коробка не найдена")
    if old.status not in ("printed", "labeled"):
        raise HTTPException(400, f"Перепечатка недоступна для статуса {old.status}")
    _check_operator_shift(old, db)

    # Старая → cancelled
    old.status = "cancelled"
    old.cancelled_at = datetime.utcnow()
    old.cancel_reason = "перепечатка"

    # Новая копия
    new = Box(
        box_barcode="TMP", qr_content="TMP",
        spec_id=old.spec_id, variant_id=old.variant_id,
        shift_id=old.shift_id, machine_id=old.machine_id,
        box_number_in_shift=old.box_number_in_shift,
        quantity_total=old.quantity_total,
        quantity_packs=old.quantity_packs,
        quantity_per_pack=old.quantity_per_pack,
        weight_brutto_g=old.weight_brutto_g,
        packer_user_id=old.packer_user_id,
        operator_user_id=old.operator_user_id,
        packer_fio=old.packer_fio,
        operator_fio=old.operator_fio,
        batch_number=old.batch_number,
    )
    db.add(new); db.flush()

    # Пересобираем qr_content и box_barcode с новым UID
    spec = db.get(Specification, old.spec_id)
    parts = [f"UID={new.box_uid:013d}", f"SKU={spec.sku_1c}"]
    if new.quantity_packs and new.quantity_per_pack:
        parts.append(f"PACKS={new.quantity_packs}")
        parts.append(f"PER_PACK={new.quantity_per_pack}")
    parts.append(f"TOTAL={new.quantity_total}")
    if spec.film_sku:
        parts.append(f"MAT={spec.film_sku}")
    if spec.film_name:
        parts.append(f"MAT_NAME={spec.film_name}")
    packer = db.get(User, new.packer_user_id) if new.packer_user_id else None
    operator = db.get(User, new.operator_user_id) if new.operator_user_id else None
    if packer:
        parts.append(f"UPAK={packer.employee_code}")
    if operator:
        parts.append(f"NALAD={operator.employee_code}")
    parts.append(f"DATE={datetime.utcnow():%Y-%m-%d}")
    new.qr_content = ";".join(parts)
    new.box_barcode = f"BOX-{datetime.utcnow():%Y%m%d}-{new.box_uid:06d}"

    db.commit(); db.refresh(new)

    # Печатаем новую
    _do_print(new, db)
    db.refresh(new)
    return new


# ─── Карантин ───

@router.post("/{box_id}/quarantine", response_model=BoxOut)
def quarantine_box(box_id: int, payload: BoxQuarantine, db: Session = Depends(get_db)):
    box = db.get(Box, box_id)
    if not box:
        raise HTTPException(404, "Коробка не найдена")
    if box.status not in ("labeled", "on_pallet"):
        raise HTTPException(400, f"В карантин можно отправить только labeled или on_pallet. Текущий: {box.status}")
    if payload.reason not in VALID_QUARANTINE_REASONS:
        raise HTTPException(400, f"Недопустимая причина. Возможные: {', '.join(sorted(VALID_QUARANTINE_REASONS))}")
    _check_operator_shift(box, db)

    # Если на паллете — запоминаем, с какой сняли
    if box.status == "on_pallet" and box.pallet_id is not None:
        box.quarantine_from_pallet_id = box.pallet_id
        box.pallet_id = None

    box.status = "quarantined"
    box.quarantined_at = datetime.utcnow()
    box.quarantine_reason = payload.reason
    db.commit(); db.refresh(box)
    return box


@router.post("/{box_id}/restore", response_model=BoxOut)
def restore_box(box_id: int, db: Session = Depends(get_db)):
    box = db.get(Box, box_id)
    if not box:
        raise HTTPException(404, "Коробка не найдена")
    if box.status != "quarantined":
        raise HTTPException(400, f"Восстановить можно только из quarantined. Текущий: {box.status}")
    _check_operator_shift(box, db)

    box.status = "labeled"
    box.quarantined_at = None
    box.quarantine_reason = None
    db.commit(); db.refresh(box)
    return box


# ─── Окончательное списание ───

@router.post("/{box_id}/cancel", response_model=BoxOut)
def cancel_box(box_id: int, payload: BoxCancel, db: Session = Depends(get_db)):
    box = db.get(Box, box_id)
    if not box:
        raise HTTPException(404, "Коробка не найдена")
    # Разрешаем отмену только из printed (ещё не наклеена) или quarantined (разобрались).
    if box.status not in ("printed", "quarantined"):
        raise HTTPException(400, f"Отменить можно только printed или quarantined. Текущий: {box.status}. Для labeled — сначала в карантин.")
    _check_operator_shift(box, db)

    box.status = "cancelled"
    box.cancelled_at = datetime.utcnow()
    box.cancel_reason = payload.reason
    db.commit(); db.refresh(box)
    return box


# ─── Сканирование упаковщиком ───

def _extract_uid(qr_or_barcode: str) -> int | None:
    """Извлекает UID из сырой строки QR или возвращает None, если не нашли."""
    # Ищем UID=NNN; в строке
    for part in qr_or_barcode.split(";"):
        part = part.strip()
        if part.startswith("UID="):
            try:
                return int(part[4:])
            except ValueError:
                return None
    return None


@router.post("/scan", response_model=BoxScanOut)
def scan_box(payload: BoxScanIn, db: Session = Depends(get_db)):
    """Упаковщик сканирует QR этикетки. Коробка переводится в labeled,
    и сразу привязывается к активной паллете на станке (если она открыта)."""
    packer = db.query(User).filter(User.pin == payload.pin, User.active == True).first()
    if not packer:
        raise HTTPException(401, "Неверный PIN")
    if packer.role != "upakovshchik":
        raise HTTPException(400, "Этот пользователь не упаковщик")

    shift = db.query(Shift).filter(Shift.status == "open").first()
    if not shift:
        raise HTTPException(400, "Нет активной смены")

    assignment = db.query(ShiftAssignment).filter(
        ShiftAssignment.shift_id == shift.shift_id,
        ShiftAssignment.user_id == packer.user_id,
        ShiftAssignment.role_in_shift == "upakovshchik",
        ShiftAssignment.to_time.is_(None),
    ).first()
    if not assignment or not assignment.machine_id:
        raise HTTPException(400, "Упаковщик не зарегистрирован на станке в текущей смене")

    # Активная паллета на станке — обязательна
    pallet = db.query(Pallet).filter(
        Pallet.shift_id == shift.shift_id,
        Pallet.machine_id == assignment.machine_id,
        Pallet.status == "open",
    ).first()
    if not pallet:
        raise HTTPException(400, "Сначала откройте паллету на станке")

    # Ищем коробку
    box: Box | None = None
    if payload.qr.startswith("BOX-"):
        box = db.query(Box).filter(Box.box_barcode == payload.qr.strip()).first()
    if box is None:
        uid = _extract_uid(payload.qr)
        if uid is not None:
            box = db.query(Box).filter(Box.box_uid == uid).first()
    if not box:
        raise HTTPException(404, "Коробка не найдена по отсканированному коду")

    if box.status != "printed":
        raise HTTPException(400, f"Коробка в статусе {box.status} — нельзя наклеить")
    if box.shift_id != shift.shift_id:
        raise HTTPException(400, "Коробка из другой смены")
    if box.machine_id != assignment.machine_id:
        raise HTTPException(400, "Коробка с другого станка — операция запрещена")

    # labeled + на паллету
    now = datetime.utcnow()
    box.status = "on_pallet"
    box.labeled_at = now
    box.labeled_by_user_id = packer.user_id
    box.pallet_id = pallet.pallet_id
    db.commit(); db.refresh(box)
    return box