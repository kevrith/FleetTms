"""Support access: the tenant owner grants Kastra staff time-limited, read-only access (masterplan 3)."""

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.auth_service import now
from app.db import get_db
from app.deps import Principal, error, platform_admin, require
from app.models import Business, SupportGrant
from app.tenancy import current_business_id

router = APIRouter(tags=["support"])


class GrantIn(BaseModel):
    hours: int = Field(ge=1, le=72)
    reason: str = Field(min_length=3, max_length=500)


def _grant_out(g: SupportGrant) -> dict:
    return {"id": g.id, "reason": g.reason, "expires_at": g.expires_at, "revoked_at": g.revoked_at}


@router.post("/support/grants", status_code=status.HTTP_201_CREATED)
async def grant_support(
    body: GrantIn, principal: Principal = Depends(require("support.grant")), db: AsyncSession = Depends(get_db)
):
    grant = SupportGrant(
        granted_by_user_id=principal.user.id, reason=body.reason, expires_at=now() + timedelta(hours=body.hours)
    )
    db.add(grant)
    await db.flush()
    audit.record(
        db, actor_user_id=principal.user.id, action="support.granted", entity_type="support_grant",
        entity_id=grant.id, after={"hours": body.hours, "reason": body.reason},
    )
    await db.commit()
    return _grant_out(grant)


@router.get("/support/grants")
async def list_grants(_: Principal = Depends(require("support.grant")), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(SupportGrant).order_by(SupportGrant.created_at.desc()))).scalars()
    return [_grant_out(g) for g in rows]


@router.delete("/support/grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_grant(
    grant_id: uuid.UUID, principal: Principal = Depends(require("support.grant")), db: AsyncSession = Depends(get_db)
):
    grant = (await db.execute(select(SupportGrant).where(SupportGrant.id == grant_id))).scalar_one_or_none()
    if grant is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That grant was not found.")
    grant.revoked_at = now()
    audit.record(
        db, actor_user_id=principal.user.id, action="support.revoked", entity_type="support_grant", entity_id=grant.id
    )
    await db.commit()


@router.post("/platform/support/{business_id}/enter")
async def enter_support(
    business_id: uuid.UUID, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)
):
    """A platform admin can only enter a company that has an active grant. Every entry is logged."""
    current_business_id.set(business_id)
    grant = (
        await db.execute(
            select(SupportGrant).where(SupportGrant.revoked_at.is_(None), SupportGrant.expires_at > now())
        )
    ).first()
    if grant is None:
        current_business_id.set(None)
        raise error(status.HTTP_403_FORBIDDEN, "no_grant", "This company has not granted support access.")
    principal.session.business_id = business_id
    principal.session.support_access = True
    audit.record(
        db, actor_user_id=principal.user.id, action="support.entered", entity_type="business", entity_id=business_id
    )
    await db.commit()
    return {"business_id": business_id}


@router.post("/platform/support/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_support(principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    if principal.business_id is not None:
        audit.record(
            db, actor_user_id=principal.user.id, action="support.left", entity_type="business",
            entity_id=principal.business_id,
        )
    principal.session.business_id = None
    principal.session.support_access = False
    await db.commit()


@router.get("/platform/businesses")
async def platform_businesses(_: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Names only. Tenant data stays closed until the tenant grants access."""
    rows = (await db.execute(select(Business.id, Business.name).order_by(Business.name))).all()
    return [{"id": r.id, "name": r.name} for r in rows]
