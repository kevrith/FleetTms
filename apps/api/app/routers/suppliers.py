"""Suppliers and parts orders (masterplan 5.9): keep suppliers, raise an order (or have one drafted from what is running low),
send it by WhatsApp in one tap, and follow it from sent to confirmed to collected to paid. Collecting an order puts the stock
into the parts store."""

import uuid
from datetime import UTC, date, datetime
from urllib.parse import quote

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import Principal, error, require_any
from app.models import Business, Part, PartsOrder, PartsOrderLine, Supplier
from app.numbering import create_numbered
from app.phone import normalize_phone
from app.routers.parts import receive_stock

router = APIRouter(tags=["suppliers"])
WRITE = ("workshop.manage",)
NEXT = {"sent": {"confirmed", "collected", "cancelled"}, "confirmed": {"collected", "cancelled"}, "collected": {"paid"}, "draft": {"cancelled"}}


class SupplierIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    phone: str | None = None
    email: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=60)
    notes: str | None = Field(default=None, max_length=500)
    is_active: bool = True


class LineIn(BaseModel):
    part_id: uuid.UUID | None = None
    description: str = Field(min_length=2, max_length=200)
    quantity: int = Field(gt=0, le=100_000)
    unit_cost_cents: int = Field(default=0, ge=0, le=10_000_000_000)


class OrderIn(BaseModel):
    supplier_id: uuid.UUID
    lines: list[LineIn] = Field(min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=500)
    expected_on: date | None = None


class StatusIn(BaseModel):
    status: str
    reference: str | None = Field(default=None, max_length=60)  # for paid: the M-Pesa code or cheque number


class LowStockIn(BaseModel):
    supplier_id: uuid.UUID | None = None


def supplier_out(s: Supplier) -> dict:
    return {"id": s.id, "name": s.name, "phone": s.phone, "email": s.email, "category": s.category, "notes": s.notes, "is_active": s.is_active}


def _clean(body: SupplierIn) -> dict:
    data = body.model_dump()
    data["name"] = body.name.strip()
    if body.phone:
        phone = normalize_phone(body.phone)
        if phone is None:
            raise error(422, "invalid_phone", "Enter a valid phone number.")
        data["phone"] = phone
    if body.email:
        try:
            data["email"] = validate_email(body.email.strip(), check_deliverability=False).normalized
        except EmailNotValidError:
            raise error(422, "invalid_email", "Enter a valid email address.") from None
    return data


def order_out(o: PartsOrder, supplier: Supplier | None = None) -> dict:
    return {
        "id": o.id, "number": o.number, "supplier_id": o.supplier_id, "supplier_name": supplier.name if supplier else None, "status": o.status, "notes": o.notes,
        "expected_on": o.expected_on, "total_cents": o.total_cents, "sent_at": o.sent_at, "confirmed_at": o.confirmed_at, "collected_at": o.collected_at, "paid_at": o.paid_at,
        "paid_reference": o.paid_reference, "created_at": o.created_at,
        "lines": [{"id": ln.id, "part_id": ln.part_id, "description": ln.description, "quantity": ln.quantity, "unit_cost_cents": ln.unit_cost_cents, "received_quantity": ln.received_quantity} for ln in o.lines],
    }  # fmt: skip


def order_text(o: PartsOrder, supplier: Supplier, business: str) -> str:
    rows = [f"- {ln.quantity} x {ln.description}" + (f" (KES {ln.unit_cost_cents / 100:,.2f} each)" if ln.unit_cost_cents else "") for ln in o.lines]
    total = f"\nTotal: KES {o.total_cents / 100:,.2f}" if o.total_cents else ""
    when = f"\nNeeded by {o.expected_on:%d %b %Y}." if o.expected_on else ""
    note = f"\n{o.notes}" if o.notes else ""
    return f"Hello {supplier.name}, order {o.number} from {business}:\n" + "\n".join(rows) + total + when + note + "\nPlease confirm availability and price. Thank you."


async def _supplier(db: AsyncSession, supplier_id: uuid.UUID) -> Supplier:
    s = (await db.execute(select(Supplier).where(Supplier.id == supplier_id))).scalar_one_or_none()
    if s is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That supplier was not found.")
    return s


async def _order(db: AsyncSession, order_id: uuid.UUID) -> PartsOrder:
    o = (await db.execute(select(PartsOrder).where(PartsOrder.id == order_id).with_for_update())).scalar_one_or_none()
    if o is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That order was not found.")
    return o


@router.get("/suppliers")
async def list_suppliers(principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    return [supplier_out(s) for s in (await db.execute(select(Supplier).order_by(Supplier.name))).scalars()]


@router.post("/suppliers", status_code=status.HTTP_201_CREATED)
async def add_supplier(body: SupplierIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    s = Supplier(**_clean(body))
    db.add(s)
    try:
        await db.flush()
    except IntegrityError:
        raise error(status.HTTP_409_CONFLICT, "duplicate_supplier", "A supplier with that name already exists.") from None
    audit.record(db, actor_user_id=principal.user.id, action="supplier.added", entity_type="supplier", entity_id=s.id, after={"name": s.name})
    await db.commit()
    return supplier_out(s)


@router.put("/suppliers/{supplier_id}")
async def update_supplier(supplier_id: uuid.UUID, body: SupplierIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    s = await _supplier(db, supplier_id)
    for k, v in _clean(body).items():
        setattr(s, k, v)
    try:
        await db.flush()
    except IntegrityError:
        raise error(status.HTTP_409_CONFLICT, "duplicate_supplier", "A supplier with that name already exists.") from None
    audit.record(db, actor_user_id=principal.user.id, action="supplier.updated", entity_type="supplier", entity_id=s.id, after={"name": s.name})
    await db.commit()
    return supplier_out(s)


def _lines(order: PartsOrder, lines: list[LineIn]) -> None:
    order.lines = [PartsOrderLine(part_id=ln.part_id, description=ln.description.strip(), quantity=ln.quantity, unit_cost_cents=ln.unit_cost_cents, sort_order=n) for n, ln in enumerate(lines)]
    order.total_cents = sum(ln.quantity * ln.unit_cost_cents for ln in lines)


@router.get("/orders")
async def list_orders(status_filter: str | None = None, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    suppliers = {s.id: s for s in (await db.execute(select(Supplier))).scalars()}
    query = select(PartsOrder).order_by(PartsOrder.created_at.desc()).limit(200)
    if status_filter:
        query = query.where(PartsOrder.status == status_filter)
    return [order_out(o, suppliers.get(o.supplier_id)) for o in (await db.execute(query)).scalars()]


@router.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_order(body: OrderIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    supplier = await _supplier(db, body.supplier_id)
    order = await create_numbered(db, PartsOrder, "PO", supplier_id=supplier.id, notes=body.notes, expected_on=body.expected_on, created_by_user_id=principal.user.id, lines=[])
    _lines(order, body.lines)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="order.created", entity_type="parts_order", entity_id=order.id, after={"number": order.number, "supplier": supplier.name, "total_cents": order.total_cents})
    await db.commit()
    return order_out(order, supplier)


@router.post("/orders/from-low-stock", status_code=status.HTTP_201_CREATED)
async def draft_from_low_stock(body: LowStockIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    """Drafts orders for parts at or below their reorder level, enough to bring each back to twice that level. Parts are grouped by the
    supplier named on them; pass a supplier to put everything on one order."""
    low = (await db.execute(select(Part).where(Part.is_active.is_(True), Part.reorder_level > 0, Part.quantity <= Part.reorder_level))).scalars().all()
    suppliers = {s.name.lower(): s for s in (await db.execute(select(Supplier).where(Supplier.is_active.is_(True)))).scalars()}
    groups: dict[uuid.UUID, tuple[Supplier, list[Part]]] = {}
    if body.supplier_id:
        sup = await _supplier(db, body.supplier_id)
        groups[sup.id] = (sup, list(low))
    else:
        for p in low:
            sup = suppliers.get((p.supplier or "").lower())
            if sup is not None:
                groups.setdefault(sup.id, (sup, []))[1].append(p)
    made = []
    for sup, parts in groups.values():
        if not parts:
            continue
        order = await create_numbered(db, PartsOrder, "PO", supplier_id=sup.id, notes="Drafted from low stock", created_by_user_id=principal.user.id, lines=[])
        _lines(order, [LineIn(part_id=p.id, description=p.name, quantity=max(1, p.reorder_level * 2 - p.quantity), unit_cost_cents=p.unit_cost_cents) for p in parts])
        await db.flush()
        audit.record(db, actor_user_id=principal.user.id, action="order.created", entity_type="parts_order", entity_id=order.id, after={"number": order.number, "from": "low_stock"})
        made.append(order_out(order, sup))
    await db.commit()
    return made


@router.get("/orders/{order_id}")
async def read_order(order_id: uuid.UUID, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    o = await _order(db, order_id)
    return order_out(o, await _supplier(db, o.supplier_id))


@router.put("/orders/{order_id}")
async def update_order(order_id: uuid.UUID, body: OrderIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    o = await _order(db, order_id)
    if o.status != "draft":
        raise error(status.HTTP_409_CONFLICT, "locked", "Only a draft order can be changed.")
    supplier = await _supplier(db, body.supplier_id)
    before = {"supplier_id": str(o.supplier_id), "lines": len(o.lines)}
    o.supplier_id, o.notes, o.expected_on = supplier.id, body.notes, body.expected_on
    _lines(o, body.lines)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="order.updated", entity_type="parts_order", entity_id=o.id, before=before, after={"supplier_id": str(supplier.id), "lines": len(body.lines)})
    await db.commit()
    return order_out(o, supplier)


@router.post("/orders/{order_id}/send")
async def send_order(order_id: uuid.UUID, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    """Marks the order sent and gives the WhatsApp link that opens the chat with the order already written."""
    o = await _order(db, order_id)
    if o.status not in ("draft", "sent"):
        raise error(status.HTTP_409_CONFLICT, "locked", "That order has already moved on.")
    supplier = await _supplier(db, o.supplier_id)
    if not supplier.phone:
        raise error(422, "no_phone", f"{supplier.name} has no phone number on file. Add one first.")
    business = (await db.execute(select(Business).where(Business.id == principal.business_id))).scalar_one()
    text = order_text(o, supplier, business.name)
    if o.status == "draft":
        o.status, o.sent_at = "sent", datetime.now(UTC)
        audit.record(db, actor_user_id=principal.user.id, action="order.sent", entity_type="parts_order", entity_id=o.id, after={"number": o.number})
    await db.commit()
    return {**order_out(o, supplier), "message": text, "whatsapp_url": f"https://wa.me/{supplier.phone.lstrip('+')}?text={quote(text)}"}


@router.post("/orders/{order_id}/status")
async def move_order(order_id: uuid.UUID, body: StatusIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    """sent to confirmed to collected to paid, or cancelled. Collecting puts the ordered parts into the store."""
    o = await _order(db, order_id)
    if body.status not in NEXT.get(o.status, set()):
        raise error(status.HTTP_409_CONFLICT, "bad_step", f"An order that is {o.status} cannot become {body.status}.")
    now = datetime.now(UTC)
    if body.status == "confirmed":
        o.confirmed_at = now
    elif body.status == "collected":
        o.collected_at = now
        for ln in o.lines:
            if ln.part_id and ln.received_quantity == 0:
                part = (await db.execute(select(Part).where(Part.id == ln.part_id).with_for_update())).scalar_one_or_none()
                if part is not None:
                    receive_stock(db, part, ln.quantity, ln.unit_cost_cents or part.unit_cost_cents, principal.user.id, f"Order {o.number}")
                    ln.received_quantity = ln.quantity
    elif body.status == "paid":
        o.paid_at, o.paid_reference = now, body.reference
    o.status = body.status
    audit.record(db, actor_user_id=principal.user.id, action=f"order.{body.status}", entity_type="parts_order", entity_id=o.id, after={"number": o.number})
    await db.commit()
    return order_out(o, await _supplier(db, o.supplier_id))
