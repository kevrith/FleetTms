"""Excel import for vehicles and staff (masterplan 5.29).

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
    ComplianceDocType,
    ComplianceDocument,
    Depot,
    OwnershipType,
    Party,
    Role,
    StaffProfile,
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
EXAMPLES = {"vehicles": (VEHICLE_COLUMNS, VEHICLE_EXAMPLE), "staff": (STAFF_COLUMNS, STAFF_EXAMPLE)}


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
