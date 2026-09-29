from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..models import (
    Shift, ShiftAssignment, User, Box, Specification, Machine,
)
from ..schemas import (
    ShiftReport, ReportUserShort, ReportPacker, ReportSpec,
    ReportMachine, ReportTotals,
)

router = APIRouter(prefix="/reports", tags=["reports"])

ALLOWED_REPORT_ROLES = ("naladchik", "shift_lead", "admin")


def _require_report_access(requester_pin: str, db: Session) -> User:
    """Проверка доступа к отчётам: только наладчик / начальник смены / админ."""
    u = db.query(User).filter(User.pin == requester_pin, User.active == True).first()
    if not u:
        raise HTTPException(401, "Неверный PIN")
    if u.role not in ALLOWED_REPORT_ROLES:
        raise HTTPException(403, "Доступ к отчётам только у наладчика и начальника смены")
    return u


@router.get("/shift/{shift_id}", response_model=ShiftReport)
def get_shift_report(
    shift_id: int,
    requester_pin: str = Query(..., description="PIN запрашивающего (наладчик / начальник смены)"),
    db: Session = Depends(get_db),
):
    _require_report_access(requester_pin, db)

    shift = db.get(Shift, shift_id)
    if not shift:
        raise HTTPException(404, "Смена не найдена")

    # Период
    end_time = shift.closed_at or datetime.utcnow()
    if shift.opened_at:
        delta = end_time - shift.opened_at.replace(tzinfo=None) if shift.opened_at.tzinfo else end_time - shift.opened_at
        duration_min = max(0, int(delta.total_seconds() // 60))
    else:
        duration_min = 0

    # Состав смены (активные + закрытые назначения)
    assignments = db.query(ShiftAssignment).filter(
        ShiftAssignment.shift_id == shift_id
    ).all()

    operator = None
    helpers: list[ReportUserShort] = []
    stagers: list[ReportUserShort] = []
    seen_packers = set()

    for a in assignments:
        u = db.get(User, a.user_id)
        if not u:
            continue
        user_short = ReportUserShort(
            user_id=u.user_id, full_name=u.full_name, employee_code=u.employee_code
        )
        if a.role_in_shift == "operator" and operator is None:
            operator = user_short
        elif a.role_in_shift == "pomoshchnik":
            if u.user_id not in {h.user_id for h in helpers}:
                helpers.append(user_short)
        elif a.role_in_shift == "stager":
            if u.user_id not in {s.user_id for s in stagers}:
                stagers.append(user_short)

    # ── Сводка по упаковщикам ──
    # Только labeled коробки этой смены. Группируем по labeled_by_user_id.
    packers_rows = (
        db.query(
            Box.labeled_by_user_id,
            func.count(Box.box_id).label("cnt"),
        )
        .filter(
            Box.shift_id == shift_id,
            Box.status == "labeled",
            Box.labeled_by_user_id.isnot(None),
        )
        .group_by(Box.labeled_by_user_id)
        .all()
    )

    packers: list[ReportPacker] = []
    for user_id, cnt in packers_rows:
        u = db.get(User, user_id)
        if not u:
            continue
        # Какие станки у этого упаковщика в смене
        machines_rows = (
            db.query(Machine.code)
            .join(Box, Box.machine_id == Machine.machine_id)
            .filter(
                Box.shift_id == shift_id,
                Box.status == "labeled",
                Box.labeled_by_user_id == user_id,
            )
            .distinct()
            .all()
        )
        machine_codes = [row[0] for row in machines_rows]
        packers.append(ReportPacker(
            user_id=u.user_id,
            full_name=u.full_name,
            employee_code=u.employee_code,
            boxes_labeled=cnt,
            machines=machine_codes,
        ))
    packers.sort(key=lambda p: -p.boxes_labeled)

    # ── Сводка по спецификациям (только labeled) ──
    specs_rows = (
        db.query(
            Box.spec_id,
            func.count(Box.box_id).label("cnt"),
            func.coalesce(func.sum(Box.quantity_total), 0).label("pkts"),
        )
        .filter(
            Box.shift_id == shift_id,
            Box.status == "labeled",
        )
        .group_by(Box.spec_id)
        .all()
    )

    specifications: list[ReportSpec] = []
    for spec_id, cnt, pkts in specs_rows:
        s = db.get(Specification, spec_id)
        if not s:
            continue
        specifications.append(ReportSpec(
            spec_id=s.spec_id,
            sku_1c=s.sku_1c,
            name_1c=s.name_1c,
            size_label=s.size_label,
            boxes_labeled=cnt,
            total_packets=int(pkts),
        ))
    specifications.sort(key=lambda x: -x.boxes_labeled)

    # ── Сводка по станкам ──
    machines_rows = (
        db.query(
            Box.machine_id,
            func.count(Box.box_id).label("cnt"),
        )
        .filter(
            Box.shift_id == shift_id,
            Box.status == "labeled",
            Box.machine_id.isnot(None),
        )
        .group_by(Box.machine_id)
        .all()
    )
    machines: list[ReportMachine] = []
    for mid, cnt in machines_rows:
        m = db.get(Machine, mid)
        if not m:
            continue
        machines.append(ReportMachine(
            machine_id=m.machine_id, code=m.code, name=m.name, boxes_labeled=cnt,
        ))
    machines.sort(key=lambda x: x.code)

    # ── Общие итоги ──
    # Все коробки этой смены
    status_counts = dict(
        db.query(Box.status, func.count(Box.box_id))
        .filter(Box.shift_id == shift_id)
        .group_by(Box.status)
        .all()
    )

    boxes_printed = status_counts.get("printed", 0)
    boxes_labeled = status_counts.get("labeled", 0)
    boxes_cancelled = status_counts.get("cancelled", 0)
    boxes_quarantined = status_counts.get("quarantined", 0)

    # total_packets — только по labeled коробкам
    total_packets = (
        db.query(func.coalesce(func.sum(Box.quantity_total), 0))
        .filter(Box.shift_id == shift_id, Box.status == "labeled")
        .scalar()
    ) or 0

    return ShiftReport(
        shift_id=shift.shift_id,
        date=shift.date,
        shift_number=shift.shift_number,
        status=shift.status,
        opened_at=shift.opened_at,
        closed_at=shift.closed_at,
        duration_minutes=duration_min,
        operator=operator,
        helpers=helpers,
        stagers=stagers,
        packers=packers,
        specifications=specifications,
        machines=machines,
        totals=ReportTotals(
            boxes_printed=boxes_printed,
            boxes_labeled=boxes_labeled,
            boxes_cancelled=boxes_cancelled,
            boxes_quarantined=boxes_quarantined,
            total_packets=int(total_packets),
        ),
    )