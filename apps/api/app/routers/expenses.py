import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, mpesa
from app.clock import capture_time
from app.db import get_db
from app.deps import Principal, error, require, require_any
from app.floatcalc import day_bounds
from app.models import (
    TRIP_CATEGORIES,
    CrewAssignment,
    Expense,
    ExpenseCategory,
    ExpenseStatus,
    Photo,
    PhotoKind,
    Role,
    RouteCost,
    SpendLimit,
    Trip,
    TripStatus,
    Vehicle,
)
from app.photos import claim_photo, photo_out
from app.routers.inspections import can_act_on_vehicle
from app.routers.vehicles import get_vehicle
from app.vehicle_scope import scope_vehicles

router = APIRouter(tags=["expenses"])
EXPENSE_FIELDS = ["vehicle_id", "trip_id", "category", "amount_cents", "note", "mpesa_code", "status", "from_float"]
DRIVER_CATEGORIES = TRIP_CATEGORIES | {ExpenseCategory.OTHER}
NEEDS_VEHICLE = TRIP_CATEGORIES | {
    ExpenseCategory.REPAIR,
    ExpenseCategory.TYRES,
    ExpenseCategory.GARAGE,
    ExpenseCategory.SERVICE,
}


class ExpenseIn(BaseModel):
    category: ExpenseCategory
    amount_cents: int = Field(gt=0, le=1_000_000_000)
    vehicle_id: uuid.UUID | None = None  # a driver's own vehicle is used when left out
    trip_id: uuid.UUID | None = None  # the driver's trip in progress is used when left out
    note: str | None = Field(default=None, max_length=255)
    mpesa_code: str | None = None
    receipt_photo_id: uuid.UUID | None = None
    receipt_photo_client_id: uuid.UUID | None = None
    client_id: uuid.UUID | None = None  # chosen by the phone, so a retried entry is stored once
    captured_at: datetime | None = None
    driver_membership_id: uuid.UUID | None = None  # for a manager recording on a driver's behalf
    from_float: bool | None = None  # managers may say whether it came out of a driver's float


class DecisionIn(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=255)


class LimitIn(BaseModel):
    category: ExpenseCategory | None = None
    role: Role | None = None
    limit_cents: int = Field(gt=0, le=1_000_000_000)


class RouteCostIn(BaseModel):
    origin: str = Field(min_length=2, max_length=160)
    destination: str = Field(min_length=2, max_length=160)
    category: ExpenseCategory
    usual_cents: int = Field(gt=0, le=1_000_000_000)
    tolerance_pct: int = Field(default=50, ge=0, le=500)


def expense_out(e: Expense, receipt: Photo | None = None) -> dict:
    return {
        "id": e.id, "vehicle_id": e.vehicle_id, "trip_id": e.trip_id, "driver_membership_id": e.driver_membership_id,
        "category": e.category.value, "amount_cents": e.amount_cents, "note": e.note, "mpesa_code": e.mpesa_code,
        "status": e.status.value, "from_float": e.from_float, "flags": e.flags, "spent_at": e.spent_at,
        "decision_note": e.decision_note, "decided_at": e.decided_at, "client_id": e.client_id,
        "has_receipt": e.receipt_photo_id is not None, "receipt": photo_out(receipt),
    }  # fmt: skip


async def _with_receipts(db: AsyncSession, rows: list[Expense]) -> list[dict]:
    ids = [e.receipt_photo_id for e in rows if e.receipt_photo_id]
    photos = {p.id: p for p in (await db.execute(select(Photo).where(Photo.id.in_(ids)))).scalars()} if ids else {}
    return [expense_out(e, photos.get(e.receipt_photo_id)) for e in rows]


async def limit_for(db: AsyncSession, category: ExpenseCategory, roles: set[Role]) -> int | None:
    """The spend limit that applies. The most specific rule wins (category and role, then either, then neither);
    for someone with several roles the most generous limit counts."""
    rules = (await db.execute(select(SpendLimit))).scalars().all()
    best: int | None = None
    for role in roles or {None}:
        fits = [r for r in rules if r.category in (None, category) and r.role in (None, role)]
        if not fits:
            continue
        pick = max(fits, key=lambda r: ((r.category is not None) * 2 + (r.role is not None), -r.limit_cents))
        best = pick.limit_cents if best is None else max(best, pick.limit_cents)
    return best


async def _route_flag(db: AsyncSession, trip: Trip | None, category: ExpenseCategory, amount: int) -> bool:
    """True if the claim is well above what this category usually costs on the trip's route."""
    if trip is None or not trip.origin or not trip.destination:
        return False
    usual = (
        await db.execute(
            select(RouteCost).where(
                func.lower(func.trim(RouteCost.origin)) == trip.origin.strip().lower(),
                func.lower(func.trim(RouteCost.destination)) == trip.destination.strip().lower(),
                RouteCost.category == category,
            )
        )
    ).scalars().first()
    return usual is not None and amount > usual.usual_cents * (100 + usual.tolerance_pct) / 100


async def do_add_expense(db: AsyncSession, principal: Principal, body: ExpenseIn) -> tuple[Expense, bool]:
    """Records an expense. Returns (expense, created); a repeat of the same client_id returns the first one."""
    if body.client_id is not None:
        again = (await db.execute(select(Expense).where(Expense.client_id == body.client_id))).scalar_one_or_none()
        if again is not None:
            return again, False
    at = capture_time(body.captured_at)
    manager = "expenses.manage" in principal.permissions
    if not manager and body.category not in DRIVER_CATEGORIES:
        raise error(status.HTTP_403_FORBIDDEN, "category_not_allowed", "Drivers record trip expenses. Ask the office for this one.")

    # Whose float it came from.
    driver_id = body.driver_membership_id if manager and body.driver_membership_id else None
    if driver_id is None and "trips.own" in principal.permissions:
        driver_id = principal.membership_id
    from_float = driver_id is not None and body.category in DRIVER_CATEGORIES
    if manager and body.from_float is not None:
        from_float = body.from_float and driver_id is not None

    # Which vehicle and trip.
    vehicle_id = body.vehicle_id
    if vehicle_id is None and driver_id is not None:
        vehicle_id = (
            await db.execute(
                select(CrewAssignment.vehicle_id).where(
                    CrewAssignment.membership_id == driver_id, CrewAssignment.ended_at.is_(None)
                )
            )
        ).scalar_one_or_none()
    vehicle = await get_vehicle(db, principal, vehicle_id) if vehicle_id else None
    if vehicle is None and body.category in NEEDS_VEHICLE:
        raise error(422, "vehicle_required", "Choose the vehicle this expense was for.")
    if vehicle is not None and not manager and not await can_act_on_vehicle(db, principal, vehicle):
        raise error(status.HTTP_403_FORBIDDEN, "not_your_vehicle", "You are not assigned to this vehicle.")
    trip = None
    if body.trip_id is not None:
        trip = (await db.execute(select(Trip).where(Trip.id == body.trip_id))).scalar_one_or_none()
        if trip is None or vehicle is None or trip.vehicle_id != vehicle.id:
            raise error(422, "wrong_trip", "That trip is not for this vehicle.")
    elif vehicle is not None and driver_id is not None and body.category in TRIP_CATEGORIES:
        trip = (
            await db.execute(
                select(Trip).where(
                    Trip.vehicle_id == vehicle.id,
                    Trip.driver_membership_id == driver_id,
                    Trip.status.in_((TripStatus.IN_PROGRESS, TripStatus.DELIVERED)),
                )
            )
        ).scalars().first()

    try:
        code = mpesa.tidy(body.mpesa_code)
    except ValueError as exc:
        raise error(422, "invalid_mpesa_code", str(exc)) from None
    if code and await mpesa.taken(db, code):
        raise error(status.HTTP_409_CONFLICT, "duplicate_mpesa_code", "That M-Pesa code was already claimed.")
    receipt = await claim_photo(
        db, principal, body.receipt_photo_id, PhotoKind.RECEIPT, required=False,
        client_id=body.receipt_photo_client_id, near=at,
    )  # fmt: skip

    flags = []
    limit = await limit_for(db, body.category, principal.roles)
    waits = limit is not None and body.amount_cents > limit and "expenses.approve_limit" not in principal.permissions
    if limit is not None and body.amount_cents > limit:
        flags.append("over_limit")
    if await _route_flag(db, trip, body.category, body.amount_cents):
        flags.append("unusual_for_route")
    if receipt is None and code is None:
        flags.append("no_receipt")

    expense = Expense(
        vehicle_id=vehicle.id if vehicle else None, trip_id=trip.id if trip else None, driver_membership_id=driver_id,
        category=body.category, amount_cents=body.amount_cents, note=body.note, mpesa_code=code,
        receipt_photo_id=receipt.id if receipt else None,
        status=ExpenseStatus.AWAITING_APPROVAL if waits else ExpenseStatus.RECORDED,
        from_float=from_float, flags=flags, client_id=body.client_id, spent_at=at, created_by_user_id=principal.user.id,
    )  # fmt: skip
    db.add(expense)
    try:
        await db.flush()
    except IntegrityError:
        raise error(status.HTTP_409_CONFLICT, "duplicate_expense", "That expense was already recorded.") from None
    audit.record(
        db, actor_user_id=principal.user.id, action="expense.added", entity_type="expense", entity_id=expense.id,
        after=audit.snapshot(expense, EXPENSE_FIELDS) | {"flags": flags},
    )  # fmt: skip
    return expense, True


@router.post("/expenses", status_code=status.HTTP_201_CREATED)
async def add_expense(
    body: ExpenseIn,
    principal: Principal = Depends(require_any("expenses.own", "expenses.manage")),
    db: AsyncSession = Depends(get_db),
):
    expense, _ = await do_add_expense(db, principal, body)
    await db.commit()
    return (await _with_receipts(db, [expense]))[0]


@router.get("/expenses")
async def list_expenses(
    vehicle_id: uuid.UUID | None = None,
    status_filter: ExpenseStatus | None = None,
    driver_membership_id: uuid.UUID | None = None,
    day: date | None = None,
    limit: int = 100,
    principal: Principal = Depends(require("expenses.view")),
    db: AsyncSession = Depends(get_db),
):
    query = select(Expense).order_by(Expense.spent_at.desc()).limit(min(max(limit, 1), 500))
    if principal.vehicle_scope is not None:
        query = query.where(Expense.vehicle_id.in_(scope_vehicles(select(Vehicle.id), principal)))
    if vehicle_id:
        query = query.where(Expense.vehicle_id == vehicle_id)
    if status_filter:
        query = query.where(Expense.status == status_filter)
    if driver_membership_id:
        query = query.where(Expense.driver_membership_id == driver_membership_id)
    if day:
        start, end = day_bounds(day)
        query = query.where(Expense.spent_at >= start, Expense.spent_at < end)
    return await _with_receipts(db, list((await db.execute(query)).scalars()))


@router.get("/me/expenses")
async def my_expenses(principal: Principal = Depends(require("expenses.own")), db: AsyncSession = Depends(get_db)):
    if principal.membership_id is None:
        return []
    query = (
        select(Expense).where(Expense.driver_membership_id == principal.membership_id).order_by(Expense.spent_at.desc()).limit(30)
    )
    return await _with_receipts(db, list((await db.execute(query)).scalars()))


@router.post("/expenses/{expense_id}/decision")
async def decide_expense(
    expense_id: uuid.UUID,
    body: DecisionIn,
    principal: Principal = Depends(require("expenses.approve_limit")),
    db: AsyncSession = Depends(get_db),
):
    """The owner approves or rejects an expense that went over a spend limit. Until then it does not count."""
    expense = (await db.execute(select(Expense).where(Expense.id == expense_id))).scalar_one_or_none()
    if expense is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That expense was not found.")
    if expense.status != ExpenseStatus.AWAITING_APPROVAL:
        raise error(status.HTTP_409_CONFLICT, "not_waiting", "That expense is not waiting for approval.")
    before = audit.snapshot(expense, EXPENSE_FIELDS)
    expense.status = ExpenseStatus.APPROVED if body.approve else ExpenseStatus.REJECTED
    expense.decided_by_user_id = principal.user.id
    expense.decided_at = datetime.now(UTC)
    expense.decision_note = body.note
    audit.record(
        db, actor_user_id=principal.user.id, action="expense.approved" if body.approve else "expense.rejected",
        entity_type="expense", entity_id=expense.id, before=before, after=audit.snapshot(expense, EXPENSE_FIELDS),
        note=body.note,
    )  # fmt: skip
    await db.commit()
    return (await _with_receipts(db, [expense]))[0]


# ---- Spend limits (owner) --------------------------------------------------------------------------


def _limit_out(r: SpendLimit) -> dict:
    return {
        "id": r.id, "category": r.category.value if r.category else None, "role": r.role.value if r.role else None,
        "limit_cents": r.limit_cents,
    }  # fmt: skip


@router.get("/spend-limits")
async def list_limits(_: Principal = Depends(require_any("expenses.view", "business.manage")), db: AsyncSession = Depends(get_db)):
    return [_limit_out(r) for r in (await db.execute(select(SpendLimit))).scalars()]


@router.put("/spend-limits")
async def replace_limits(
    body: list[LimitIn], principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)
):
    """Sets the owner's spend limits as a whole list. A blank category or role means "any"."""
    keys = [(r.category, r.role) for r in body]
    if len(set(keys)) != len(keys):
        raise error(422, "duplicate_rule", "Each category and role combination can have only one limit.")
    old = [_limit_out(r) for r in (await db.execute(select(SpendLimit))).scalars()]
    for row in (await db.execute(select(SpendLimit))).scalars().all():
        await db.delete(row)
    new = [SpendLimit(category=r.category, role=r.role, limit_cents=r.limit_cents) for r in body]
    db.add_all(new)
    await db.flush()
    audit.record(
        db, actor_user_id=principal.user.id, action="spend_limits.changed", entity_type="business",
        before={"limits": [{k: str(v) for k, v in o.items() if k != "id"} for o in old]},
        after={"limits": [{k: str(v) for k, v in _limit_out(n).items() if k != "id"} for n in new]},
    )  # fmt: skip
    await db.commit()
    return [_limit_out(r) for r in new]


# ---- Expected costs per route ------------------------------------------------------------------------


def _route_out(r: RouteCost) -> dict:
    return {
        "id": r.id, "origin": r.origin, "destination": r.destination, "category": r.category.value,
        "usual_cents": r.usual_cents, "tolerance_pct": r.tolerance_pct,
    }  # fmt: skip


@router.get("/route-costs")
async def list_route_costs(_: Principal = Depends(require_any("expenses.view", "vehicles.view")), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(RouteCost).order_by(RouteCost.origin, RouteCost.destination))).scalars()
    return [_route_out(r) for r in rows]


@router.post("/route-costs", status_code=status.HTTP_201_CREATED)
async def add_route_cost(
    body: RouteCostIn, principal: Principal = Depends(require("vehicles.manage")), db: AsyncSession = Depends(get_db)
):
    row = RouteCost(**{**body.model_dump(), "origin": body.origin.strip(), "destination": body.destination.strip()})
    db.add(row)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="route_cost.added", entity_type="route_cost", entity_id=row.id, after=_route_out(row) | {"id": str(row.id)})
    await db.commit()
    return _route_out(row)


@router.put("/route-costs/{row_id}")
async def update_route_cost(
    row_id: uuid.UUID, body: RouteCostIn, principal: Principal = Depends(require("vehicles.manage")), db: AsyncSession = Depends(get_db)
):
    row = (await db.execute(select(RouteCost).where(RouteCost.id == row_id))).scalar_one_or_none()
    if row is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That route cost was not found.")
    for field, value in {**body.model_dump(), "origin": body.origin.strip(), "destination": body.destination.strip()}.items():
        setattr(row, field, value)
    audit.record(db, actor_user_id=principal.user.id, action="route_cost.updated", entity_type="route_cost", entity_id=row.id, after=_route_out(row) | {"id": str(row.id)})
    await db.commit()
    return _route_out(row)


@router.delete("/route-costs/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route_cost(
    row_id: uuid.UUID, principal: Principal = Depends(require("vehicles.manage")), db: AsyncSession = Depends(get_db)
):
    row = (await db.execute(select(RouteCost).where(RouteCost.id == row_id))).scalar_one_or_none()
    if row is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That route cost was not found.")
    audit.record(db, actor_user_id=principal.user.id, action="route_cost.deleted", entity_type="route_cost", entity_id=row.id, before=_route_out(row) | {"id": str(row.id)})
    await db.delete(row)
    await db.commit()
