"""Excel import for vehicles, staff, clients, suppliers and what clients owed when the business started (masterplan 5.29).

All or nothing: if any row has a problem, nothing is imported and every problem is listed with its row number.
`dry_run=true` checks the file and rolls back either way.
"""

import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import Principal, error, require
from app.models import (
    Client,
    ComplianceDocType,
    ComplianceDocument,
    Depot,
    Invoice,
    InvoiceLine,
    OwnershipType,
    Party,
    Role,
    StaffProfile,
    Supplier,
    Vehicle,
)
from app.routers.documents import DocumentIn
from app.routers.staff import ProfileIn
from app.routers.users import invite_member
from app.routers.vehicles import (
    PARTY_FOR_OWNERSHIP,
    VEHICLE_FIELDS,
    VehicleIn,
    normalize_registration,
    validate_vehicle_refs,
)

router = APIRouter(prefix="/imports", tags=["imports"])

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 2000
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

VEHICLE_COLUMNS = [
    "registration", "make", "model", "capacity_tonnes", "fuel_type", "tank_litres", "expected_kmpl_loaded",
    "expected_kmpl_empty", "odometer_km", "tracking_tier", "depot", "ownership_type", "lessor_lender_lessee",
    "gvw_limit_kg", "axle_config",
]  # fmt: skip
VEHICLE_EXAMPLE = [
    "KCA 123A", "Isuzu", "FVR", 10, "diesel", 200, 4.5, 6, 125000, "basic", "Nairobi Yard", "owned", "", 16000, "2",
]  # fmt: skip
STAFF_COLUMNS = ["name", "phone", "email", "roles", "depot", "licence_number", "licence_class", "licence_expiry"]
STAFF_EXAMPLE = ["Peter Otieno", "0712345678", "", "driver", "Nairobi Yard", "DL-123456", "CE", "2027-06-30"]
CLIENT_COLUMNS = ["name", "contact_name", "phone", "email", "kra_pin", "billing_method", "rate_kes", "payment_terms_days", "vat_pct"]
CLIENT_EXAMPLE = ["Mwangi Cement Ltd", "Grace Mwangi", "0712345678", "accounts@mwangi.example.com", "P051234567Z", "per_tonne", 3000, 30, 16]
SUPPLIER_COLUMNS = ["name", "phone", "email", "category", "notes"]
SUPPLIER_EXAMPLE = ["Kiambu Spares", "0722345678", "", "spares", "Ask for Mr Kamau"]
# What clients owed the business on the day it started on FleetTms: one row for each invoice still unpaid on the old system. They become
# invoices (marked "balance brought forward") so the debtors list, the ageing and the reminders work from the first day, and payments match to them.
BALANCE_COLUMNS = ["client", "invoice_number", "invoice_date", "due_date", "amount_kes", "note"]
BALANCE_EXAMPLE = ["Mwangi Cement Ltd", "INV-2026-0412", "2026-09-01", "2026-10-01", 245000, "Cement to Nairobi, unpaid"]
EXAMPLES = {
    "vehicles": (VEHICLE_COLUMNS, VEHICLE_EXAMPLE), "staff": (STAFF_COLUMNS, STAFF_EXAMPLE), "clients": (CLIENT_COLUMNS, CLIENT_EXAMPLE),
    "suppliers": (SUPPLIER_COLUMNS, SUPPLIER_EXAMPLE), "balances": (BALANCE_COLUMNS, BALANCE_EXAMPLE),
}  # fmt: skip


class RowError(Exception):
    def __init__(self, message: str, column: str | None = None):
        self.message, self.column = message, column


def _header(raw: Any) -> str:
    return str(raw or "").strip().lower().replace(" ", "_")


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
    return None if value in ("", None) else value


def _read_sheet(content: bytes, columns: list[str]) -> list[tuple[int, dict[str, Any]]]:
    """Returns (row number, values) for each non-blank row. Raises 422 if the file is not usable."""
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 - any parse failure means "not a valid Excel file"
        raise error(422, "bad_file", "That file is not a valid .xlsx Excel file.") from None
    rows = wb.active.iter_rows(values_only=True)
    headers = [_header(h) for h in next(rows, ())]
    unknown = [h for h in headers if h and h not in columns]
    missing = [c for c in columns[:1] if c not in headers]
    if missing or unknown:
        raise error(
            422,
            "bad_columns",
            f"Use the template columns. Missing: {', '.join(missing) or 'none'}. Not recognised: {', '.join(unknown) or 'none'}.",
        )
    out = []
    for number, row in enumerate(rows, start=2):
        values = {h: _clean(v) for h, v in zip(headers, row, strict=False) if h}
        if not any(v is not None for v in values.values()):
            continue
        if len(out) >= MAX_ROWS:
            raise error(422, "too_many_rows", f"Import at most {MAX_ROWS} rows at a time.")
        out.append((number, values))
    return out


def _enum_value(raw: Any) -> Any:
    return str(raw).strip().lower().replace(" ", "_").replace("-", "_") if raw is not None else None


def _number(raw: Any, column: str) -> Decimal | None:
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        raise RowError("Must be a number.", column) from None


def _integer(raw: Any, column: str) -> int | None:
    n = _number(raw, column)
    if n is None:
        return None
    if n != n.to_integral_value():
        raise RowError("Must be a whole number.", column)
    return int(n)


def _date(raw: Any, column: str) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        raise RowError("Use a date like 2027-06-30.", column) from None


def _pydantic_errors(exc: ValidationError) -> RowError:
    first = exc.errors()[0]
    column = str(first["loc"][0]) if first["loc"] else None
    return RowError(first["msg"].removeprefix("Value error, "), column)


async def _depot_id(db: AsyncSession, name: Any):
    if name is None:
        return None
    depot = (await db.execute(select(Depot).where(func.lower(Depot.name) == str(name).lower()))).scalars().first()
    if depot is None:
        raise RowError(f"No depot named '{name}'. Create it first.", "depot")
    return depot.id


async def _party_id(db: AsyncSession, actor: Principal, name: Any, ownership: OwnershipType) -> Any:
    kind = PARTY_FOR_OWNERSHIP[ownership]
    if kind is None:
        if name is not None:
            raise RowError("An owned vehicle has no lessor or lender.", "lessor_lender_lessee")
        return None
    if name is None:
        raise RowError(f"Name the {kind.value} for this vehicle.", "lessor_lender_lessee")
    party = (
        await db.execute(select(Party).where(Party.kind == kind, func.lower(Party.name) == str(name).lower()))
    ).scalars().first()
    if party is None:
        party = Party(kind=kind, name=str(name))
        db.add(party)
        await db.flush()
        audit.record(
            db, actor_user_id=actor.user.id, action="party.created", entity_type="party",
            entity_id=party.id, after={"kind": kind.value, "name": party.name}, note="Created by Excel import",
        )  # fmt: skip
    return party.id


async def _vehicle_row(db: AsyncSession, actor: Principal, v: dict[str, Any], seen: set[str]) -> Vehicle:
    if v.get("registration") is None:
        raise RowError("Registration is required.", "registration")
    registration = normalize_registration(str(v["registration"]))
    if registration in seen:
        raise RowError("This registration appears twice in the file.", "registration")
    if (await db.execute(select(Vehicle.id).where(Vehicle.registration == registration))).first() is not None:
        raise RowError("A vehicle with this registration already exists.", "registration")
    seen.add(registration)

    if not _valid_enum(OwnershipType, v.get("ownership_type")):
        raise RowError("Use owned, asset financed, leased in or leased out.", "ownership_type")
    ownership = OwnershipType(_enum_value(v.get("ownership_type")) or "owned")
    try:
        body = VehicleIn(
            registration=registration,
            make=v.get("make"),
            model=v.get("model"),
            capacity_tonnes=_number(v.get("capacity_tonnes"), "capacity_tonnes"),
            fuel_type=_enum_value(v.get("fuel_type")) or "diesel",
            tank_litres=_integer(v.get("tank_litres"), "tank_litres"),
            expected_kmpl_loaded=_number(v.get("expected_kmpl_loaded"), "expected_kmpl_loaded"),
            expected_kmpl_empty=_number(v.get("expected_kmpl_empty"), "expected_kmpl_empty"),
            odometer_km=_integer(v.get("odometer_km"), "odometer_km") or 0,
            tracking_tier=_enum_value(v.get("tracking_tier")) or "basic",
            depot_id=await _depot_id(db, v.get("depot")),
            ownership_type=ownership,
            party_id=await _party_id(db, actor, v.get("lessor_lender_lessee"), ownership),
            gvw_limit_kg=_integer(v.get("gvw_limit_kg"), "gvw_limit_kg"),
            axle_config=str(v["axle_config"]) if v.get("axle_config") is not None else None,
        )
    except ValidationError as exc:
        raise _pydantic_errors(exc) from None
    await validate_vehicle_refs(db, body)
    vehicle = Vehicle(**body.model_dump())
    db.add(vehicle)
    await db.flush()
    audit.record(
        db, actor_user_id=actor.user.id, action="vehicle.created", entity_type="vehicle",
        entity_id=vehicle.id, after=audit.snapshot(vehicle, VEHICLE_FIELDS), note="Created by Excel import",
    )  # fmt: skip
    return vehicle


def _valid_enum(enum_cls, raw: Any) -> bool:
    return raw is None or _enum_value(raw) in {m.value for m in enum_cls}


async def _staff_row(db: AsyncSession, actor: Principal, v: dict[str, Any]) -> str | None:
    if v.get("name") is None:
        raise RowError("Name is required.", "name")
    roles = set()
    for part in str(v.get("roles") or "").replace(";", ",").split(","):
        if part.strip():
            if not _valid_enum(Role, part):
                raise RowError(f"'{part.strip()}' is not a role.", "roles")
            roles.add(Role(_enum_value(part)))
    if not roles:
        raise RowError("Give at least one role.", "roles")
    if roles & {Role.LESSOR}:
        raise RowError("Lessors are added from the lease screens, not here.", "roles")

    licence_number, licence_class = v.get("licence_number"), v.get("licence_class")
    try:
        profile = ProfileIn(
            licence_number=str(licence_number) if licence_number is not None else None,
            licence_class=str(licence_class) if licence_class is not None else None,
        )
    except ValidationError as exc:
        raise _pydantic_errors(exc) from None
    licence_expiry = _date(v.get("licence_expiry"), "licence_expiry")
    if licence_expiry and Role.DRIVER not in roles:
        raise RowError("Only drivers have a driving licence expiry.", "licence_expiry")

    membership, token = await invite_member(
        db, actor,
        name=str(v["name"]),
        email=str(v["email"]) if v.get("email") is not None else None,
        phone=str(v["phone"]) if v.get("phone") is not None else None,
        roles=roles,
        depot_id=await _depot_id(db, v.get("depot")),
    )  # fmt: skip
    db.add(
        StaffProfile(
            membership_id=membership.id, licence_number=profile.licence_number, licence_class=profile.licence_class
        )
    )
    if licence_expiry:
        doc = DocumentIn(
            doc_type=ComplianceDocType.DRIVING_LICENCE, membership_id=membership.id, expires_on=licence_expiry
        )
        db.add(ComplianceDocument(**doc.model_dump()))
    return token


def _cents(raw: Any, column: str) -> int:
    """Shillings as typed in the sheet (245000 or 245,000.50) to whole cents, refusing more than two decimals so nothing is silently rounded."""
    value = _number(raw, column)
    if value is None:
        raise RowError("Enter an amount in shillings.", column)
    cents = value * 100
    if cents != cents.to_integral_value():
        raise RowError("Use at most two decimals (cents).", column)
    return int(cents)


async def _client_row(db: AsyncSession, actor: Principal, v: dict[str, Any], seen: set[str]) -> None:
    from app.routers.clients import ClientIn
    from app.routers.clients import _clean as clean_client

    name = str(v.get("name") or "").strip()
    if not name:
        raise RowError("Name the client.", "name")
    key = name.lower()
    if key in seen or (await db.execute(select(Client.id).where(func.lower(Client.name) == key))).first() is not None:
        raise RowError("A client with this name already exists (or is twice in the file).", "name")
    seen.add(key)
    rate = _cents(v["rate_kes"], "rate_kes") if v.get("rate_kes") is not None else 0
    terms = _integer(v.get("payment_terms_days"), "payment_terms_days")
    method = _enum_value(v.get("billing_method")) or "per_trip"
    vat = _number(v.get("vat_pct"), "vat_pct")
    try:
        body = ClientIn(
            name=name, contact_name=v.get("contact_name"), phone=str(v["phone"]) if v.get("phone") is not None else None, email=v.get("email"),
            kra_pin=v.get("kra_pin"), billing_method=method, rate_cents=rate, payment_terms_days=30 if terms is None else terms, vat_pct=vat or Decimal(0),
        )  # fmt: skip
    except ValidationError as exc:
        raise _pydantic_errors(exc) from None
    client = Client(**clean_client(body))
    db.add(client)
    await db.flush()
    audit.record(db, actor_user_id=actor.user.id, action="client.added", entity_type="client", entity_id=client.id, after={"name": client.name}, note="Created by Excel import")


async def _supplier_row(db: AsyncSession, actor: Principal, v: dict[str, Any], seen: set[str]) -> None:
    from app.routers.suppliers import SupplierIn
    from app.routers.suppliers import _clean as clean_supplier

    name = str(v.get("name") or "").strip()
    if not name:
        raise RowError("Name the supplier.", "name")
    key = name.lower()
    if key in seen or (await db.execute(select(Supplier.id).where(func.lower(Supplier.name) == key))).first() is not None:
        raise RowError("A supplier with this name already exists (or is twice in the file).", "name")
    seen.add(key)
    try:
        body = SupplierIn(name=name, phone=str(v["phone"]) if v.get("phone") is not None else None, email=v.get("email"), category=v.get("category"), notes=v.get("notes"))
    except ValidationError as exc:
        raise _pydantic_errors(exc) from None
    supplier = Supplier(**clean_supplier(body))
    db.add(supplier)
    await db.flush()
    audit.record(db, actor_user_id=actor.user.id, action="supplier.added", entity_type="supplier", entity_id=supplier.id, after={"name": supplier.name}, note="Created by Excel import")


async def _balance_row(db: AsyncSession, actor: Principal, v: dict[str, Any], seen: set[str]) -> None:
    name = str(v.get("client") or "").strip()
    if not name:
        raise RowError("Name the client.", "client")
    client = (await db.execute(select(Client).where(func.lower(Client.name) == name.lower()))).scalars().first()
    if client is None:
        raise RowError(f"No client called {name}. Import the clients first, with exactly the same name.", "client")
    old_number = str(v.get("invoice_number") or "").strip()
    if not old_number or len(old_number) > 17:
        raise RowError("Give the old invoice number (up to 17 characters).", "invoice_number")
    number = f"OB-{old_number}"
    if number in seen or (await db.execute(select(Invoice.id).where(Invoice.number == number))).first() is not None:
        raise RowError("This invoice number is already there (or twice in the file).", "invoice_number")
    seen.add(number)
    issued, due = _date(v.get("invoice_date"), "invoice_date"), _date(v.get("due_date"), "due_date")
    if issued is None:
        raise RowError("Give the invoice date.", "invoice_date")
    if due is None:
        due = issued
    if due < issued:
        raise RowError("The due date is before the invoice date.", "due_date")
    cents = _cents(v.get("amount_kes"), "amount_kes")
    if cents <= 0:
        raise RowError("The amount still owed must be more than nothing.", "amount_kes")
    note = str(v.get("note") or "").strip()
    description = f"Balance brought forward: invoice {old_number}" + (f", {note}" if note else "")
    invoice = Invoice(
        number=number, client_id=client.id, kind="opening", issue_date=issued, due_date=due, status="issued", subtotal_cents=cents, vat_pct=Decimal(0), vat_cents=0, total_cents=cents,
        created_by_user_id=actor.user.id,
        lines=[InvoiceLine(description=description[:255], quantity=Decimal(1), unit_cents=cents, amount_cents=cents, sort_order=1)],
    )  # fmt: skip
    db.add(invoice)
    await db.flush()
    # No tax-authority submission and no income: it was invoiced, and counted, on the old system. It is only what is still owed.
    audit.record(db, actor_user_id=actor.user.id, action="invoice.opening_balance", entity_type="invoice", entity_id=invoice.id, after={"number": number, "total_cents": cents, "client": client.name}, note="Created by Excel import")


async def _run(kind: str, file: UploadFile, dry_run: bool, principal: Principal, db: AsyncSession) -> dict:
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise error(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file_too_large", "Keep the file under 5 MB.")
    columns, _ = EXAMPLES[kind]
    rows = _read_sheet(content, columns)

    errors: list[dict] = []
    tokens: list[dict] = []
    seen: set[str] = set()
    for number, values in rows:
        try:
            async with db.begin_nested():  # a failed row undoes only itself, so later rows are still checked
                if kind == "vehicles":
                    await _vehicle_row(db, principal, values, seen)
                elif kind == "clients":
                    await _client_row(db, principal, values, seen)
                elif kind == "suppliers":
                    await _supplier_row(db, principal, values, seen)
                elif kind == "balances":
                    await _balance_row(db, principal, values, seen)
                else:
                    token = await _staff_row(db, principal, values)
                    if token:
                        tokens.append({"row": number, "name": values["name"], "invite_token": token})
        except RowError as exc:
            errors.append({"row": number, "column": exc.column, "message": exc.message})
        except Exception as exc:  # noqa: BLE001 - HTTPException from shared helpers carries a message
            detail = getattr(exc, "detail", None)
            message = detail["message"] if isinstance(detail, dict) else "This row could not be imported."
            errors.append({"row": number, "column": None, "message": message})

    ok = not errors and not dry_run
    if ok:
        await db.commit()
    else:
        await db.rollback()
    return {
        "dry_run": dry_run,
        "rows": len(rows),
        "imported": len(rows) if ok else 0,
        "errors": errors,
        "invite_tokens": tokens if ok else [],
    }


@router.get("/{kind}/template")
async def template(kind: str, _: Principal = Depends(require("data.import"))):
    if kind not in EXAMPLES:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "No such import.")
    columns, example = EXAMPLES[kind]
    wb = Workbook()
    ws = wb.active
    ws.title = kind
    ws.append(columns)
    ws.append(example)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="fleettms-{kind}-template.xlsx"'}
    )


@router.post("/vehicles")
async def import_vehicles(
    file: UploadFile,
    dry_run: bool = Query(default=False),
    principal: Principal = Depends(require("data.import", "vehicles.manage")),
    db: AsyncSession = Depends(get_db),
):
    return await _run("vehicles", file, dry_run, principal, db)


@router.post("/staff")
async def import_staff(
    file: UploadFile,
    dry_run: bool = Query(default=False),
    principal: Principal = Depends(require("data.import", "users.manage")),
    db: AsyncSession = Depends(get_db),
):
    return await _run("staff", file, dry_run, principal, db)


@router.post("/clients")
async def import_clients(
    file: UploadFile,
    dry_run: bool = Query(default=False),
    principal: Principal = Depends(require("data.import", "clients.manage")),
    db: AsyncSession = Depends(get_db),
):
    return await _run("clients", file, dry_run, principal, db)


@router.post("/suppliers")
async def import_suppliers(
    file: UploadFile,
    dry_run: bool = Query(default=False),
    principal: Principal = Depends(require("data.import", "workshop.manage")),
    db: AsyncSession = Depends(get_db),
):
    return await _run("suppliers", file, dry_run, principal, db)


@router.post("/balances")
async def import_balances(
    file: UploadFile,
    dry_run: bool = Query(default=False),
    principal: Principal = Depends(require("data.import", "invoices.manage")),
    db: AsyncSession = Depends(get_db),
):
    """What clients still owed when the business started: one row for each unpaid invoice from the old system."""
    return await _run("balances", file, dry_run, principal, db)
