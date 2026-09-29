from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..models import (
    PrintRun, Box, Specification, LabelVariant, LabelTemplate,
    Shift, User, Machine, ShiftAssignment, PrintJob,
)
from ..schemas import PrintRunCreate, PrintRunCancel, PrintRunOut, PrintRunResult
from ..label_builder import build_tspl_for_run
from ..services.printer_client import send_to_printer

router = APIRouter(prefix="/print-runs", tags=["print-runs"])

MAX_QUANTITY = 500


def _build_batch_number(template: LabelTemplate, spec: Specification) -> str | None:
    """Номер партии для СДЭК: КП-{format}-{perf}-{DDMMYYYY}"""
    if template.code != "CDEK":
        return None
    parts = ["КП"]
    if spec.format:
        parts.append(spec.format)
    if spec.perforation:
        parts.append(spec.perforation)
    parts.append(datetime.utcnow().strftime("%d%m%Y"))
    return "-".join(parts)


@router.post("", response_model=PrintRunResult)
def create_print_run(payload: PrintRunCreate, db: Session = Depends(get_db)):
    # 1. Проверки
    if payload.quantity < 1 or payload.quantity > MAX_QUANTITY:
        raise HTTPException(400, f"Количество должно быть от 1 до {MAX_QUANTITY}")

    spec = db.get(Specification, payload.spec_id)
    if not spec or not spec.is_active:
        raise HTTPException(404, "Спецификация не найдена или неактивна")

    variant = db.get(LabelVariant, payload.variant_id)
    if not variant or not variant.is_active:
        raise HTTPException(404, "Вариант этикетки не найден или неактивен")
    if variant.spec_id != spec.spec_id:
        raise HTTPException(400, "Вариант не соответствует спецификации")

    template = db.get(LabelTemplate, variant.template_id)
    if not template:
        raise HTTPException(404, "Шаблон не найден")

    shift = db.get(Shift, payload.shift_id)
    if not shift or shift.status != "open":
        raise HTTPException(400, "Смена не открыта")

    machine = db.get(Machine, payload.machine_id)
    if not machine or not machine.is_active:
        raise HTTPException(404, "Станок не найден или неактивен")

    operator = db.get(User, payload.operator_user_id)
    if not operator or operator.role != "naladchik":
        raise HTTPException(400, "Оператор должен быть наладчиком")

    # Упаковщик на станке — обязателен
    packer_assignment = db.query(ShiftAssignment).filter(
        ShiftAssignment.shift_id == payload.shift_id,
        ShiftAssignment.machine_id == payload.machine_id,
        ShiftAssignment.role_in_shift == "upakovshchik",
        ShiftAssignment.to_time.is_(None),
    ).order_by(ShiftAssignment.from_time).first()
    if not packer_assignment:
        raise HTTPException(400, f"На станке {machine.code} нет активного упаковщика")
    packer = db.get(User, packer_assignment.user_id)

    # 2. batch_number
    batch_number = _build_batch_number(template, spec)

    # 3. Создаём PrintRun
    run = PrintRun(
        spec_id=payload.spec_id,
        variant_id=payload.variant_id,
        shift_id=payload.shift_id,
        machine_id=payload.machine_id,
        operator_user_id=operator.user_id,
        packer_user_id=packer.user_id,
        quantity=payload.quantity,
        batch_number=batch_number,
        status="active",
    )
    db.add(run); db.flush()

    # 4. Начальный номер коробки в смене
    last_num = db.query(func.coalesce(func.max(Box.box_number_in_shift), 0)).filter(
        Box.shift_id == payload.shift_id
    ).scalar() or 0

    # 5. Создаём N коробок
    boxes = []
    for i in range(payload.quantity):
        box_number = last_num + i + 1
        b = Box(
            box_barcode="TMP", qr_content="TMP",
            spec_id=payload.spec_id, variant_id=payload.variant_id,
            shift_id=payload.shift_id, machine_id=payload.machine_id,
            print_run_id=run.run_id,
            box_number_in_shift=box_number,
            quantity_total=payload.quantity_total,
            quantity_packs=payload.quantity_packs,
            quantity_per_pack=payload.quantity_per_pack,
            packer_user_id=packer.user_id,
            operator_user_id=operator.user_id,
            packer_fio=packer.full_name,
            operator_fio=operator.full_name,
            batch_number=batch_number,
            weight_brutto_g=spec.weight_brutto_g,
        )
        db.add(b)
        boxes.append(b)
    db.flush()  # получаем box_uid для каждой

    # 6. Заполняем qr_content и box_barcode
    for b in boxes:
        parts = [f"UID={b.box_uid:013d}", f"SKU={spec.sku_1c}"]
        if b.quantity_packs and b.quantity_per_pack:
            parts.append(f"PACKS={b.quantity_packs}")
            parts.append(f"PER_PACK={b.quantity_per_pack}")
        parts.append(f"TOTAL={b.quantity_total}")
        if spec.film_sku:
            parts.append(f"MAT={spec.film_sku}")
        if spec.film_name:
            parts.append(f"MAT_NAME={spec.film_name}")
        parts.append(f"UPAK={packer.employee_code}")
        parts.append(f"NALAD={operator.employee_code}")
        parts.append(f"DATE={datetime.utcnow():%Y-%m-%d}")
        b.qr_content = ";".join(parts)
        b.box_barcode = f"BOX-{datetime.utcnow():%Y%m%d}-{b.box_uid:06d}"

    db.flush()

    # 7. Собираем большой TSPL
    try:
        tspl = build_tspl_for_run(db, boxes)
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Ошибка построения TSPL партии: {e}")

    # 8. Отправляем одним POST
    result = send_to_printer(tspl, profile="75x120")
    ok = result["status"] in ("saved", "queued")

    # 9. Обновляем статусы
    now = datetime.utcnow()
    for b in boxes:
        if ok:
            b.status = "printed"
            b.printed_at = now

    # 10. Один PrintJob на всю партию
    job = PrintJob(
        template_id=variant.template_id,
        variant_id=variant.variant_id,
        box_id=None,  # партия — не одна коробка
        status="printed" if ok else "failed",
        printer_id=result.get("mode", "unknown"),
        error_message=result.get("error"),
    )
    db.add(job)

    if ok:
        run.status = "done"

    db.commit(); db.refresh(run)

    return PrintRunResult(
        run_id=run.run_id,
        quantity=payload.quantity,
        first_box_uid=boxes[0].box_uid,
        last_box_uid=boxes[-1].box_uid,
        transport=result["mode"],
        print_status=result["status"],
        details=result,
    )


@router.get("", response_model=list[PrintRunOut])
def list_print_runs(
    shift_id: int | None = None,
    machine_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(PrintRun)
    if shift_id is not None:
        q = q.filter(PrintRun.shift_id == shift_id)
    if machine_id is not None:
        q = q.filter(PrintRun.machine_id == machine_id)
    if status:
        q = q.filter(PrintRun.status == status)
    return q.order_by(PrintRun.run_id.desc()).limit(200).all()


@router.get("/{run_id}", response_model=PrintRunOut)
def get_print_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(PrintRun, run_id)
    if not run:
        raise HTTPException(404, "Партия не найдена")
    return run


@router.get("/{run_id}/boxes")
def get_run_boxes(run_id: int, db: Session = Depends(get_db)):
    """Список коробок в партии."""
    run = db.get(PrintRun, run_id)
    if not run:
        raise HTTPException(404, "Партия не найдена")
    boxes = db.query(Box).filter(Box.print_run_id == run_id).order_by(Box.box_uid).all()
    return [{
        "box_id": b.box_id,
        "box_uid": b.box_uid,
        "box_number_in_shift": b.box_number_in_shift,
        "status": b.status,
    } for b in boxes]


@router.post("/{run_id}/cancel", response_model=PrintRunOut)
def cancel_print_run(run_id: int, payload: PrintRunCancel, db: Session = Depends(get_db)):
    """Отмена партии: только printed → cancelled. labeled остаются как есть.
    Операция доступна только в открытой смене."""
    run = db.get(PrintRun, run_id)
    if not run:
        raise HTTPException(404, "Партия не найдена")
    if run.status == "cancelled":
        raise HTTPException(400, "Партия уже отменена")

    shift = db.get(Shift, run.shift_id)
    if not shift or shift.status != "open":
        raise HTTPException(400, "Смена не открыта — операция невозможна")

    now = datetime.utcnow()
    boxes = db.query(Box).filter(Box.print_run_id == run_id).all()
    cancelled_count = 0
    for b in boxes:
        if b.status == "printed":
            b.status = "cancelled"
            b.cancelled_at = now
            b.cancel_reason = f"отмена партии: {payload.reason}"
            cancelled_count += 1
        # labeled, quarantined и т.д. — не трогаем

    run.status = "cancelled"
    run.cancelled_at = now
    run.cancel_reason = payload.reason
    db.commit(); db.refresh(run)
    return run