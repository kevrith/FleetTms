"""Quotes (masterplan 5.17): price a job from the client's billing method, the route, expected fuel, tolls and crew costs,
show the expected profit before accepting, send it, and turn an accepted quote into a job."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, fraud, fuel_prices, predictions
from app.db import get_db
from app.deps import Principal, error, require_any
from app.models import (
    Business,
    Client,
    FuelEntry,
    FuelType,
    Job,
    Quote,
    QuoteStatus,
    SavedRoute,
    Vehicle,
)
from app.numbering import create_numbered
from app.quote_files import kes, quote_pdf
from app.quote_rules import BillingMethod, QuoteInput
from app.quote_rules import quote as compute
from app.reminders import nairobi_today
from app.report_delivery import DeliveryError, get_report_sender
from app.routers.clients import get_client
from app.sms import get_sms_sender

router = APIRouter(tags=["quotes"])
MANAGE = ("clients.manage",)
FALLBACK_KMPL = (Decimal("4.5"), Decimal(6))  # a lorry's usual loaded and empty fuel economy when nothing else is known
EDITABLE = (QuoteStatus.DRAFT, QuoteStatus.SENT)


class QuoteIn(BaseModel):
    client_id: uuid.UUID
    route_id: uuid.UUID | None = None
    vehicle_id: uuid.UUID | None = None  # for its fuel economy
    cargo_description: str | None = Field(default=None, max_length=255)
    weight_tonnes: Decimal = Field(default=Decimal(0), ge=0, le=1000, decimal_places=2)
    trips: int = Field(default=1, ge=1, le=500)
    return_empty: bool = True
    billing_method: BillingMethod | None = None  # the client's, unless set here
    rate_cents: int | None = Field(default=None, ge=0, le=10_000_000_000)
    distance_km: int | None = Field(default=None, ge=0, le=20_000)
    kmpl_loaded: Decimal | None = Field(default=None, gt=0, le=50, decimal_places=2)
    kmpl_empty: Decimal | None = Field(default=None, gt=0, le=50, decimal_places=2)
    fuel_price_cents: int | None = Field(default=None, gt=0, le=100_000)
    tolls_cents: int | None = Field(default=None, ge=0, le=1_000_000_000)
    crew_cents: int | None = Field(default=None, ge=0, le=1_000_000_000)
    other_cents: int | None = Field(default=None, ge=0, le=1_000_000_000)
    valid_days: int = Field(default=14, ge=1, le=365)
    pickup_at: datetime | None = None
    deliver_by: datetime | None = None
    instructions: str | None = Field(default=None, max_length=2000)


class SendIn(BaseModel):
    channel: Literal["email", "whatsapp", "sms"]
    recipient: str | None = Field(default=None, max_length=255)  # the client's own address or number if left out


class DeclineIn(BaseModel):
    note: str | None = Field(default=None, max_length=255)


async def pump_price(db: AsyncSession, fuel: FuelType = FuelType.DIESEL) -> int | None:
    """The pump price a quote starts from: EPRA's price for the business's town this month (typed in or fetched) when there is one,
    otherwise the average price per litre of the latest fuel entries."""
    epra = await fuel_prices.current(db, fuel)
    if epra is not None:
        return epra["cents"]
    prices = (await db.execute(select(FuelEntry.price_per_litre_cents).order_by(FuelEntry.captured_at.desc()).limit(5))).scalars().all()
    return round(sum(prices) / len(prices)) if prices else None


async def fleet_kmpl(db: AsyncSession) -> tuple[Decimal, Decimal]:
    rows = (await db.execute(select(Vehicle.expected_kmpl_loaded, Vehicle.expected_kmpl_empty))).all()
    loaded = [r[0] for r in rows if r[0]]
    empty = [r[1] for r in rows if r[1]]
    return (sum(loaded) / len(loaded) if loaded else FALLBACK_KMPL[0], sum(empty) / len(empty) if empty else FALLBACK_KMPL[1])


async def resolve(db: AsyncSession, body: QuoteIn, *, strict: bool = True) -> tuple[dict, dict | None]:
    """Fills what the caller left out from the client, the route, the vehicle and the pump price, and prices it.
    Returns the fields to store and the calculation (None when a job is set up without enough to cost it)."""
    client = await get_client(db, body.client_id)
    route = None
    if body.route_id:
        route = (await db.execute(select(SavedRoute).where(SavedRoute.id == body.route_id))).scalar_one_or_none()
        if route is None or (route.client_id not in (None, client.id)):
            raise error(status.HTTP_404_NOT_FOUND, "not_found", "That route was not found for this client.")
    vehicle = None
    if body.vehicle_id:
        vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == body.vehicle_id))).scalar_one_or_none()
        if vehicle is None:
            raise error(status.HTTP_404_NOT_FOUND, "not_found", "That vehicle was not found.")
    method = body.billing_method or client.billing_method
    rate = body.rate_cents if body.rate_cents is not None else client.rate_cents
    if rate <= 0 and strict:
        raise error(422, "rate_required", "Set a rate: on the client, or on this quote.")
    distance = body.distance_km if body.distance_km is not None else (route.distance_km if route else None)
    if distance is None and strict:
        raise error(422, "distance_required", "Choose a saved route, or enter the distance.")
    avg_loaded, avg_empty = await fleet_kmpl(db)
    kmpl_loaded = body.kmpl_loaded or (vehicle.expected_kmpl_loaded if vehicle and vehicle.expected_kmpl_loaded else avg_loaded)
    kmpl_empty = body.kmpl_empty or (vehicle.expected_kmpl_empty if vehicle and vehicle.expected_kmpl_empty else avg_empty)
    fuel_source, fuel_detail = ("typed in" if body.kmpl_loaded or body.kmpl_empty else ("declared" if vehicle and (vehicle.expected_kmpl_loaded or vehicle.expected_kmpl_empty) else "fleet average")), []
    if vehicle is not None and distance is not None and (body.kmpl_loaded is None or body.kmpl_empty is None):
        thresholds, _ = await fraud.load_settings(db)
        known = await predictions.consumption(db, vehicle, distance_km=distance, weight_kg=float(body.weight_tonnes) * 1000, origin=route.pickup if route else None, destination=route.dropoff if route else None, t=thresholds)
        if known is not None:
            if body.kmpl_loaded is None and known["kmpl_loaded"]:
                kmpl_loaded = Decimal(str(known["kmpl_loaded"]))
            if body.kmpl_empty is None and known["kmpl_empty"]:
                kmpl_empty = Decimal(str(known["kmpl_empty"]))
            fuel_source, fuel_detail = known["source"], known["steps"]
    if not fuel_detail:
        fuel_detail = {"typed in": ["The fuel economy was typed into the quote."], "declared": [f"The consumption entered for the vehicle: {kmpl_loaded} km a litre loaded and {kmpl_empty} empty. Its own trip history is not enough to use yet."],
                       "fleet average": [f"No consumption is set for the vehicle, so the fleet's average is used: {float(kmpl_loaded):g} km a litre loaded and {float(kmpl_empty):g} empty."]}[fuel_source]
    fuel_price = body.fuel_price_cents or await pump_price(db, vehicle.fuel_type if vehicle else FuelType.DIESEL)
    if fuel_price is None and strict:
        raise error(422, "fuel_price_required", "No fuel has been recorded yet, so enter today's pump price per litre.")
    fields = {
        "client_id": client.id, "route_id": route.id if route else None, "vehicle_id": vehicle.id if vehicle else None,
        "cargo_description": body.cargo_description, "weight_tonnes": body.weight_tonnes, "trips": body.trips,
        "return_empty": body.return_empty, "billing_method": method, "rate_cents": rate, "distance_km": distance or 0,
        "kmpl_loaded": kmpl_loaded, "kmpl_empty": kmpl_empty, "fuel_price_cents": fuel_price or 0,
        "tolls_cents": body.tolls_cents if body.tolls_cents is not None else (route.tolls_cents if route else 0),
        "crew_cents": body.crew_cents if body.crew_cents is not None else (route.crew_cents if route else 0),
        "other_cents": body.other_cents if body.other_cents is not None else (route.other_cents if route else 0),
        "pickup_at": body.pickup_at, "deliver_by": body.deliver_by, "instructions": body.instructions,
    }  # fmt: skip
    can_cost = distance is not None and fuel_price is not None
    result = compute(_input(fields)) if can_cost else None
    price = result["price_cents"] if result else _price_only(fields)
    fields["price_cents"] = price
    fields["total_cost_cents"] = result["total_cost_cents"] if result else 0
    fields["expected_profit_cents"] = result["profit_cents"] if result else 0
    fields["margin_pct"] = result["margin_pct"] if result else None
    fields["fuel_source"], fields["fuel_detail"] = fuel_source, fuel_detail
    fields["lease_charge_cents"], fields["net_profit_cents"], fields["lease_detail"] = 0, None, None
    if vehicle is not None and result is not None:
        lease = await predictions.lease_for_job(db, vehicle.id, price_cents=result["price_cents"], gross_profit_cents=result["profit_cents"], trips=body.trips, distance_km=distance or 0, return_empty=body.return_empty, expected_hours=route.expected_hours if route else None, today=nairobi_today())
        if lease is not None:
            fields["lease_charge_cents"], fields["net_profit_cents"], fields["lease_detail"] = lease["total_cents"], result["profit_cents"] - lease["total_cents"], lease
    return fields, result


def _input(f: dict) -> QuoteInput:
    return QuoteInput(
        method=BillingMethod(f["billing_method"]), rate_cents=f["rate_cents"], distance_km=f["distance_km"], weight_tonnes=float(f["weight_tonnes"]),
        trips=f["trips"], return_empty=f["return_empty"], kmpl_loaded=float(f["kmpl_loaded"]), kmpl_empty=float(f["kmpl_empty"]),
        fuel_price_cents=f["fuel_price_cents"], tolls_cents=f["tolls_cents"], crew_cents=f["crew_cents"], other_cents=f["other_cents"],
    )  # fmt: skip


def _price_only(f: dict) -> int:
    from app.quote_rules import price_for

    return price_for(_input({**f, "distance_km": f["distance_km"], "fuel_price_cents": f["fuel_price_cents"]}))


def quote_out(q: Quote, client: Client | None = None, route: SavedRoute | None = None, job: Job | None = None) -> dict:
    calc = compute(_input({
        "billing_method": q.billing_method, "rate_cents": q.rate_cents, "distance_km": q.distance_km, "weight_tonnes": q.weight_tonnes,
        "trips": q.trips, "return_empty": q.return_empty, "kmpl_loaded": q.kmpl_loaded, "kmpl_empty": q.kmpl_empty,
        "fuel_price_cents": q.fuel_price_cents, "tolls_cents": q.tolls_cents, "crew_cents": q.crew_cents, "other_cents": q.other_cents,
    }))  # fmt: skip
    expired = q.status in EDITABLE and q.valid_until is not None and q.valid_until < nairobi_today()
    return {
        "id": q.id, "number": q.number, "client_id": q.client_id, "client_name": client.name if client else None,
        "route_id": q.route_id, "route_name": route.name if route else None, "vehicle_id": q.vehicle_id,
        "cargo_description": q.cargo_description, "weight_tonnes": float(q.weight_tonnes), "trips": q.trips,
        "return_empty": q.return_empty, "billing_method": q.billing_method.value, "rate_cents": q.rate_cents,
        "distance_km": q.distance_km, "kmpl_loaded": float(q.kmpl_loaded), "kmpl_empty": float(q.kmpl_empty),
        "fuel_price_cents": q.fuel_price_cents, "tolls_cents": q.tolls_cents, "crew_cents": q.crew_cents, "other_cents": q.other_cents,
        "price_cents": q.price_cents, "fuel_litres": calc["fuel_litres"], "fuel_cents": calc["fuel_cents"],
        "cost_per_trip_cents": calc["cost_per_trip_cents"], "total_cost_cents": q.total_cost_cents,
        "expected_profit_cents": q.expected_profit_cents, "margin_pct": q.margin_pct, "fuel_source": q.fuel_source, "fuel_detail": q.fuel_detail,
        "lease_charge_cents": q.lease_charge_cents, "net_profit_cents": q.net_profit_cents, "lease_detail": q.lease_detail,
        "status": q.status.value, "expired": expired, "valid_until": q.valid_until, "pickup_at": q.pickup_at,
        "deliver_by": q.deliver_by, "instructions": q.instructions, "sent_via": q.sent_via, "sent_to": q.sent_to,
        "sent_at": q.sent_at, "decided_at": q.decided_at, "decision_note": q.decision_note, "created_at": q.created_at,
        "job_id": job.id if job else None, "job_number": job.number if job else None,
    }  # fmt: skip


async def _get(db: AsyncSession, quote_id: uuid.UUID) -> Quote:
    quote = (await db.execute(select(Quote).where(Quote.id == quote_id))).scalar_one_or_none()
    if quote is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That quote was not found.")
    return quote


async def _out(db: AsyncSession, q: Quote) -> dict:
    client = (await db.execute(select(Client).where(Client.id == q.client_id))).scalar_one_or_none()
    route = (await db.execute(select(SavedRoute).where(SavedRoute.id == q.route_id))).scalar_one_or_none() if q.route_id else None
    job = (await db.execute(select(Job).where(Job.quote_id == q.id))).scalar_one_or_none()
    return quote_out(q, client, route, job)


@router.get("/quotes/defaults")
async def defaults(
    client_id: uuid.UUID, route_id: uuid.UUID | None = None, vehicle_id: uuid.UUID | None = None,
    principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db),
):
    """What a new quote would start with, so the form (and its live preview) begins from the real numbers."""
    fields, _ = await resolve(db, QuoteIn(client_id=client_id, route_id=route_id, vehicle_id=vehicle_id), strict=False)
    return {k: (float(v) if isinstance(v, Decimal) else (v.value if hasattr(v, "value") else v)) for k, v in fields.items() if k in (
        "billing_method", "rate_cents", "distance_km", "kmpl_loaded", "kmpl_empty", "fuel_price_cents", "tolls_cents", "crew_cents", "other_cents")}  # fmt: skip


@router.post("/quotes/preview")
async def preview_quote(body: QuoteIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """The numbers a quote would have, with how they were worked out: where the fuel estimate came from, and for a lorry hired in what
    its lease charges for the job and the profit left after that. Nothing is saved."""
    fields, calc = await resolve(db, body, strict=False)
    lines = []
    if calc is not None:
        lines = [
            {"label": "Price to the client", "cents": calc["price_cents"]},
            {"label": f"Fuel: {calc['fuel_litres']:g} litres a trip at {kes(fields['fuel_price_cents'])} a litre, {body.trips} trip{'s' if body.trips != 1 else ''}", "cents": -calc["fuel_cents"] * body.trips},
            {"label": "Tolls, crew and other costs", "cents": -(fields["tolls_cents"] + fields["crew_cents"] + fields["other_cents"]) * body.trips},
            {"label": "Expected profit", "cents": calc["profit_cents"], "total": True},
        ]
        if fields["lease_detail"]:
            lines += [{"label": f"Lease: {x['label']}", "cents": -x["cents"]} for x in fields["lease_detail"]["lines"]]
            lines.append({"label": "Expected profit after the lease", "cents": fields["net_profit_cents"], "total": True})
    return {
        "price_cents": fields["price_cents"], "total_cost_cents": fields["total_cost_cents"], "expected_profit_cents": fields["expected_profit_cents"], "margin_pct": fields["margin_pct"],
        "fuel_litres": calc["fuel_litres"] if calc else None, "kmpl_loaded": float(fields["kmpl_loaded"]), "kmpl_empty": float(fields["kmpl_empty"]), "fuel_price_cents": fields["fuel_price_cents"],
        "fuel_source": fields["fuel_source"], "fuel_detail": fields["fuel_detail"], "lease_charge_cents": fields["lease_charge_cents"], "net_profit_cents": fields["net_profit_cents"],
        "lease_note": fields["lease_detail"]["note"] if fields["lease_detail"] else None, "lines": lines,
    }  # fmt: skip


@router.get("/quotes")
async def list_quotes(status_filter: QuoteStatus | None = None, client_id: uuid.UUID | None = None, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    query = select(Quote).order_by(Quote.created_at.desc()).limit(300)
    if status_filter:
        query = query.where(Quote.status == status_filter)
    if client_id:
        query = query.where(Quote.client_id == client_id)
    clients = {c.id: c for c in (await db.execute(select(Client))).scalars()}
    jobs = {j.quote_id: j for j in (await db.execute(select(Job).where(Job.quote_id.is_not(None)))).scalars()}
    return [quote_out(q, clients.get(q.client_id), None, jobs.get(q.id)) for q in (await db.execute(query)).scalars()]


@router.post("/quotes", status_code=status.HTTP_201_CREATED)
async def create_quote(body: QuoteIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    fields, _ = await resolve(db, body)
    q = await create_numbered(
        db, Quote, "Q", valid_until=nairobi_today() + timedelta(days=body.valid_days), created_by_user_id=principal.user.id, **fields
    )
    audit.record(db, actor_user_id=principal.user.id, action="quote.created", entity_type="quote", entity_id=q.id, after={"number": q.number, "price_cents": q.price_cents, "profit_cents": q.expected_profit_cents})
    await db.commit()
    return await _out(db, q)


@router.get("/quotes/{quote_id}")
async def read_quote(quote_id: uuid.UUID, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    return await _out(db, await _get(db, quote_id))


@router.put("/quotes/{quote_id}")
async def update_quote(quote_id: uuid.UUID, body: QuoteIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    q = await _get(db, quote_id)
    if q.status not in EDITABLE:
        raise error(status.HTTP_409_CONFLICT, "closed", "That quote has been accepted or declined and can no longer be changed.")
    fields, _ = await resolve(db, body)
    for key, value in fields.items():
        setattr(q, key, value)
    q.valid_until = nairobi_today() + timedelta(days=body.valid_days)
    q.status = QuoteStatus.DRAFT  # a changed quote must be sent again
    audit.record(db, actor_user_id=principal.user.id, action="quote.updated", entity_type="quote", entity_id=q.id, after={"price_cents": q.price_cents})
    await db.commit()
    return await _out(db, q)


@router.post("/quotes/{quote_id}/send")
async def send_quote(quote_id: uuid.UUID, body: SendIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Sends the client the quote: a PDF by email or WhatsApp, or a short text by SMS. Our costs and profit are never in it."""
    q = await _get(db, quote_id)
    if q.status not in EDITABLE:
        raise error(status.HTTP_409_CONFLICT, "closed", "That quote has been accepted or declined.")
    client = await get_client(db, q.client_id)
    recipient = (body.recipient or (client.email if body.channel == "email" else client.phone) or "").strip()
    if not recipient:
        raise error(422, "no_recipient", f"The client has no {'email address' if body.channel == 'email' else 'phone number'}. Enter one.")
    business = (await db.execute(select(Business).where(Business.id == principal.business_id))).scalar_one()
    try:
        if body.channel == "sms":
            until = f" Valid until {q.valid_until.isoformat()}." if q.valid_until else ""
            await get_sms_sender().send(recipient, f"{business.name}: quote {q.number} for {client.name} is {kes(q.price_cents)}.{until}")
        else:
            route = (await db.execute(select(SavedRoute).where(SavedRoute.id == q.route_id))).scalar_one_or_none() if q.route_id else None
            pdf = quote_pdf(q, client, route, business.name)
            await get_report_sender(body.channel).send(recipient, f"Quote {q.number} from {business.name}", f"quote-{q.number}.pdf", pdf)
    except DeliveryError as e:
        raise error(502, "delivery_failed", str(e)) from None
    q.status, q.sent_via, q.sent_to, q.sent_at = QuoteStatus.SENT, body.channel, recipient, datetime.now(UTC)
    audit.record(db, actor_user_id=principal.user.id, action="quote.sent", entity_type="quote", entity_id=q.id, after={"channel": body.channel})
    await db.commit()
    return await _out(db, q)


@router.post("/quotes/{quote_id}/accept")
async def accept_quote(quote_id: uuid.UUID, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """The client said yes: the quote becomes a job, ready to dispatch."""
    from app.routers.jobs import job_from_quote, job_out

    q = await _get(db, quote_id)
    if q.status not in EDITABLE:
        raise error(status.HTTP_409_CONFLICT, "closed", "That quote has already been accepted or declined.")
    if q.valid_until is not None and q.valid_until < nairobi_today():
        raise error(status.HTTP_409_CONFLICT, "expired", "That quote has expired. Change its validity to accept it.")
    q.status, q.decided_at = QuoteStatus.ACCEPTED, datetime.now(UTC)
    job = await job_from_quote(db, principal, q)
    audit.record(db, actor_user_id=principal.user.id, action="quote.accepted", entity_type="quote", entity_id=q.id, after={"job": job.number})
    await db.commit()
    return {"quote": await _out(db, q), "job": await job_out(db, principal, job)}


@router.post("/quotes/{quote_id}/decline")
async def decline_quote(quote_id: uuid.UUID, body: DeclineIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    q = await _get(db, quote_id)
    if q.status not in EDITABLE:
        raise error(status.HTTP_409_CONFLICT, "closed", "That quote has already been accepted or declined.")
    q.status, q.decided_at, q.decision_note = QuoteStatus.DECLINED, datetime.now(UTC), body.note
    audit.record(db, actor_user_id=principal.user.id, action="quote.declined", entity_type="quote", entity_id=q.id, note=body.note)
    await db.commit()
    return await _out(db, q)
