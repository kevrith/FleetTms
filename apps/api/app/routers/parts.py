"""Spare parts store (masterplan 5.24): stock, receiving, issuing to work orders, returns, counts and issued-vs-fitted."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import Principal, error, require_any
from app.models import (
    Expense,
    ExpenseCategory,
    ExpenseStatus,
    Part,
    StockKind,
    StockMovement,
    Vehicle,
    WorkOrder,
    WorkOrderPart,
    WorkOrderSource,
    WorkOrderStatus,
)
from app.routers.workshop import _get_wo, work_order_out

router = APIRouter(tags=["parts"])
WRITE = ("workshop.manage",)
CLOSED = (WorkOrderStatus.DONE, WorkOrderStatus.CANCELLED)


class PartIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    sku: str | None = Field(default=None, max_length=60)
    unit: str = Field(default="pcs", min_length=1, max_length=20)
    reorder_level: int = Field(default=0, ge=0, le=1_000_000)
    supplier: str | None = Field(default=None, max_length=120)
    is_active: bool = True


class ReceiveIn(BaseModel):
    quantity: int = Field(gt=0, le=1_000_000)
    unit_cost_cents: int = Field(ge=0, le=1_000_000_000)
    note: str | None = Field(default=None, max_length=255)


class IssueIn(BaseModel):
    part_id: uuid.UUID
    quantity: int = Field(gt=0, le=10_000)


class FittedIn(BaseModel):
    fitted: bool = True


class CountLine(BaseModel):
    part_id: uuid.UUID
    counted: int = Field(ge=0, le=1_000_000)


class CountIn(BaseModel):
    counts: list[CountLine] = Field(min_length=1, max_length=500)
    note: str | None = Field(default=None, max_length=255)


def part_out(p: Part) -> dict:
    return {
        "id": p.id, "name": p.name, "sku": p.sku, "unit": p.unit, "quantity": p.quantity,
        "unit_cost_cents": p.unit_cost_cents, "stock_value_cents": p.quantity * p.unit_cost_cents,
        "reorder_level": p.reorder_level, "low_stock": p.reorder_level > 0 and p.quantity <= p.reorder_level,
        "supplier": p.supplier, "is_active": p.is_active,
    }  # fmt: skip


def movement_out(m: StockMovement) -> dict:
    return {
        "id": m.id, "part_id": m.part_id, "kind": m.kind.value, "quantity_delta": m.quantity_delta,
        "balance_after": m.balance_after, "unit_cost_cents": m.unit_cost_cents, "work_order_id": m.work_order_id,
        "vehicle_id": m.vehicle_id, "note": m.note, "created_at": m.created_at,
    }  # fmt: skip


async def _part(db: AsyncSession, part_id: uuid.UUID) -> Part:
    # Locked, so two people issuing the last filter at once cannot both get it.
    part = (await db.execute(select(Part).where(Part.id == part_id).with_for_update())).scalar_one_or_none()
    if part is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That part was not found.")
    return part


def _move(db: AsyncSession, part: Part, kind: StockKind, delta: int, user_id: uuid.UUID, **extra) -> None:
    part.quantity += delta
    db.add(
        StockMovement(
            part_id=part.id, kind=kind, quantity_delta=delta, balance_after=part.quantity,
            unit_cost_cents=extra.pop("unit_cost_cents", part.unit_cost_cents), created_by_user_id=user_id, **extra,
        )
    )  # fmt: skip


@router.get("/parts")
async def list_parts(
    low_stock: bool = False, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)
):
    rows = [part_out(p) for p in (await db.execute(select(Part).where(Part.is_active.is_(True)).order_by(Part.name))).scalars()]
    return [r for r in rows if r["low_stock"]] if low_stock else rows


@router.post("/parts", status_code=status.HTTP_201_CREATED)
async def add_part(body: PartIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    part = Part(name=body.name.strip(), sku=body.sku, unit=body.unit, reorder_level=body.reorder_level, supplier=body.supplier)
    db.add(part)
    try:
        await db.flush()
    except IntegrityError:
        raise error(status.HTTP_409_CONFLICT, "duplicate_part", "A part with that name already exists.") from None
    audit.record(db, actor_user_id=principal.user.id, action="part.added", entity_type="part", entity_id=part.id, after={"name": part.name})
    await db.commit()
    return part_out(part)


@router.put("/parts/{part_id}")
async def update_part(part_id: uuid.UUID, body: PartIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    part = await _part(db, part_id)
    for field, value in body.model_dump().items():
        setattr(part, field, value.strip() if field == "name" else value)
    try:
        await db.flush()
    except IntegrityError:
        raise error(status.HTTP_409_CONFLICT, "duplicate_part", "A part with that name already exists.") from None
    await db.commit()
    return part_out(part)


def receive_stock(db: AsyncSession, part: Part, quantity: int, unit_cost_cents: int, user_id: uuid.UUID, note: str | None = None) -> None:
    """Stock arrives. The unit cost becomes the weighted average of what is on the shelf and what came in."""
    value = part.quantity * part.unit_cost_cents + quantity * unit_cost_cents
    new_avg = round(value / (part.quantity + quantity))
    _move(db, part, StockKind.RECEIVED, quantity, user_id, unit_cost_cents=unit_cost_cents, note=note)
    part.unit_cost_cents = new_avg


@router.post("/parts/{part_id}/receive")
async def receive(part_id: uuid.UUID, body: ReceiveIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    part = await _part(db, part_id)
    receive_stock(db, part, body.quantity, body.unit_cost_cents, principal.user.id, body.note)
    audit.record(db, actor_user_id=principal.user.id, action="part.received", entity_type="part", entity_id=part.id, after={"quantity": body.quantity, "unit_cost_cents": body.unit_cost_cents})
    await db.commit()
    return part_out(part)


@router.get("/parts/movements")
async def movements(part_id: uuid.UUID | None = None, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    query = select(StockMovement).order_by(StockMovement.created_at.desc()).limit(300)
    if part_id:
        query = query.where(StockMovement.part_id == part_id)
    return [movement_out(m) for m in (await db.execute(query)).scalars()]


@router.post("/parts/counts")
async def stock_count(body: CountIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    """A physical count. Differences from the books are corrected and listed with their value, which exposes leakage."""
    variances = []
    for line in body.counts:
        part = await _part(db, line.part_id)
        delta = line.counted - part.quantity
        if delta:
            variances.append({"part_id": part.id, "name": part.name, "expected": part.quantity, "counted": line.counted, "difference": delta, "value_cents": delta * part.unit_cost_cents})
            _move(db, part, StockKind.COUNTED, delta, principal.user.id, note=body.note or "Stock count")
    audit.record(db, actor_user_id=principal.user.id, action="stock.counted", entity_type="part", after={"lines": len(body.counts), "differences": len(variances)})
    await db.commit()
    return {"counted": len(body.counts), "variances": variances, "net_value_cents": sum(v["value_cents"] for v in variances)}


@router.get("/parts/unfitted")
async def unfitted(principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    """Issued-vs-fitted check: parts taken from the store that nobody has confirmed as fitted."""
    rows = (await db.execute(select(WorkOrderPart).where(WorkOrderPart.part_id.is_not(None), WorkOrderPart.fitted.is_(False)))).scalars().all()
    orders = {w.id: w for w in (await db.execute(select(WorkOrder).where(WorkOrder.id.in_([r.work_order_id for r in rows])))).scalars()} if rows else {}
    vehicles = {v.id: v for v in (await db.execute(select(Vehicle))).scalars()}
    return [
        {
            "id": r.id, "work_order_id": r.work_order_id, "work_order_title": orders[r.work_order_id].title,
            "work_order_status": orders[r.work_order_id].status.value, "registration": vehicles[orders[r.work_order_id].vehicle_id].registration,
            "name": r.name, "quantity": r.quantity, "value_cents": r.quantity * r.unit_cost_cents,
            "closed": orders[r.work_order_id].status in CLOSED,
        }
        for r in rows if r.work_order_id in orders
    ]  # fmt: skip


# ---- Issuing to work orders ------------------------------------------------------------------------


@router.post("/work-orders/{wo_id}/issue", status_code=status.HTTP_201_CREATED)
async def issue(wo_id: uuid.UUID, body: IssueIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    """Takes a part from the store for a work order. Stock goes down and its cost lands on the vehicle at once."""
    wo = await _get_wo(db, principal, wo_id)
    if wo.status in CLOSED:
        raise error(status.HTTP_409_CONFLICT, "closed", "That work order is already closed.")
    part = await _part(db, body.part_id)
    if not part.is_active:
        raise error(status.HTTP_409_CONFLICT, "inactive_part", "That part is no longer stocked.")
    if part.quantity < body.quantity:
        raise error(status.HTTP_409_CONFLICT, "insufficient_stock", f"Only {part.quantity} {part.unit} of {part.name} in stock.")
    cost = body.quantity * part.unit_cost_cents
    expense = None
    if cost > 0:
        expense = Expense(
            vehicle_id=wo.vehicle_id, work_order_id=wo.id,
            category=ExpenseCategory.SERVICE if wo.source == WorkOrderSource.SERVICE else ExpenseCategory.REPAIR,
            amount_cents=cost, note=f"Part: {part.name} x{body.quantity}"[:255], status=ExpenseStatus.RECORDED,
            spent_at=datetime.now(UTC), created_by_user_id=principal.user.id,
        )  # fmt: skip
        db.add(expense)
        await db.flush()
    row = WorkOrderPart(
        work_order_id=wo.id, name=part.name, quantity=body.quantity, unit_cost_cents=part.unit_cost_cents,
        part_id=part.id, fitted=False, expense_id=expense.id if expense else None,
    )  # fmt: skip
    wo.parts.append(row)
    _move(db, part, StockKind.ISSUED, -body.quantity, principal.user.id, work_order_id=wo.id, vehicle_id=wo.vehicle_id)
    audit.record(db, actor_user_id=principal.user.id, action="part.issued", entity_type="work_order", entity_id=wo.id, after={"part": part.name, "quantity": body.quantity, "cost_cents": cost})
    await db.commit()
    return work_order_out(wo)


def _store_row(wo: WorkOrder, row_id: uuid.UUID) -> WorkOrderPart:
    row = next((p for p in wo.parts if p.id == row_id and p.part_id is not None), None)
    if row is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That issued part was not found on this work order.")
    return row


@router.post("/work-orders/{wo_id}/parts/{row_id}/fitted")
async def mark_fitted(wo_id: uuid.UUID, row_id: uuid.UUID, body: FittedIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    wo = await _get_wo(db, principal, wo_id)
    row = _store_row(wo, row_id)
    row.fitted = body.fitted
    audit.record(db, actor_user_id=principal.user.id, action="part.fitted" if body.fitted else "part.unfitted", entity_type="work_order", entity_id=wo.id, after={"part": row.name})
    await db.commit()
    return work_order_out(wo)


@router.post("/work-orders/{wo_id}/parts/{row_id}/return")
async def return_part(wo_id: uuid.UUID, row_id: uuid.UUID, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    """An issued part that was not used goes back on the shelf and its cost comes off the vehicle."""
    wo = await _get_wo(db, principal, wo_id)
    if wo.status in CLOSED:
        raise error(status.HTTP_409_CONFLICT, "closed", "That work order is already closed.")
    row = _store_row(wo, row_id)
    part = await _part(db, row.part_id)
    _move(db, part, StockKind.RETURNED, row.quantity, principal.user.id, work_order_id=wo.id, vehicle_id=wo.vehicle_id, unit_cost_cents=row.unit_cost_cents)
    if row.expense_id:
        expense = (await db.execute(select(Expense).where(Expense.id == row.expense_id))).scalar_one_or_none()
        if expense is not None:
            await db.delete(expense)
    wo.parts.remove(row)
    audit.record(db, actor_user_id=principal.user.id, action="part.returned", entity_type="work_order", entity_id=wo.id, after={"part": part.name, "quantity": row.quantity})
    await db.commit()
    return work_order_out(wo)
