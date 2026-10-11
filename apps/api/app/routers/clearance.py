"""Document clearance (masterplan 5.1): whether a trip may start while the driver's licence or the vehicle's insurance has run out. The owner
chooses off, warn or block and which documents count, and can allow one blocked trip with a reason. The rules are in app/clearance_rules.py."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, clearance, clearance_rules
from app.db import get_db
from app.deps import Principal, error, require
from app.models import Business, TripStatus
from app.routers.trips import get_trip
from app.tenancy import current_business_id

router = APIRouter(tags=["clearance"])


class RuleIn(BaseModel):
    mode: Literal["off", "warn", "block"]
    required: list[Literal["driving_licence", "insurance", "inspection", "ntsa_licence", "tlb_licence", "permit"]] = Field(max_length=6)


class OverrideIn(BaseModel):
    reason: str = Field(min_length=5, max_length=200)


def rule_out(mode: str, required: list[str]) -> dict:
    return {"mode": mode, "required": required, "options": [{"doc_type": d, "label": clearance_rules.LABELS[d], "subject": "driver" if d in clearance_rules.DRIVER_DOCS else "vehicle"} for d in clearance.ALLOWED_REQUIRED]}


@router.get("/document-rule")
async def read_rule(principal: Principal = Depends(require("vehicles.view")), db: AsyncSession = Depends(get_db)):
    return rule_out(*await clearance.rule_of(db))


@router.put("/document-rule")
async def save_rule(body: RuleIn, principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    """Off says nothing, warn says what has run out but never stops a trip, block refuses to start a trip while a required document has run
    out (or is not recorded at all)."""
    business = (await db.execute(select(Business).where(Business.id == current_business_id.get()))).scalar_one()
    before = {"mode": business.document_rule, "required": business.required_documents}
    business.document_rule, business.required_documents = body.mode, list(dict.fromkeys(body.required))
    audit.record(db, actor_user_id=principal.user.id, action="document_rule.changed", entity_type="business", entity_id=business.id, before=before, after={"mode": body.mode, "required": business.required_documents})
    await db.commit()
    return rule_out(business.document_rule, business.required_documents)


@router.post("/trips/{trip_id}/compliance-override")
async def override(trip_id: uuid.UUID, body: OverrideIn, principal: Principal = Depends(require("compliance.override")), db: AsyncSession = Depends(get_db)):
    """The owner lets this one trip start although a required document has run out. The reason is kept and audited; the next trip is checked again."""
    trip = await get_trip(db, principal, trip_id)
    if trip.status != TripStatus.SCHEDULED:
        raise error(status.HTTP_409_CONFLICT, "wrong_status", "Only a trip that has not started can be allowed.")
    trip.compliance_override_reason = body.reason.strip()
    trip.compliance_override_by_user_id, trip.compliance_override_at = principal.user.id, datetime.now(UTC)
    audit.record(
        db, actor_user_id=principal.user.id, action="trip.compliance_override", entity_type="trip", entity_id=trip.id,
        after={"reason": trip.compliance_override_reason}, note=trip.compliance_override_reason,
    )  # fmt: skip
    await db.commit()
    return {"trip_id": trip.id, "reason": trip.compliance_override_reason, "at": trip.compliance_override_at}
