from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.config import settings
from app.db import get_db
from app.deps import Principal, current_principal, error
from app.models import Document, PolicyAcceptance

router = APIRouter(prefix="/privacy", tags=["privacy"])


class AcceptIn(BaseModel):
    document: Document
    version: str


def current_versions() -> dict[Document, str]:
    return {
        Document.TERMS: settings.terms_version,
        Document.PRIVACY: settings.privacy_version,
        Document.DPA: settings.dpa_version,
        Document.MONITORING_NOTICE: settings.monitoring_notice_version,
    }


@router.get("/documents")
async def documents():
    return [{"document": d.value, "version": v} for d, v in current_versions().items()]


@router.post("/accept", status_code=status.HTTP_204_NO_CONTENT)
async def accept(
    body: AcceptIn, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)
):
    if principal.business_id is None or principal.support:
        raise error(status.HTTP_403_FORBIDDEN, "forbidden", "You do not have permission to do this.")
    if current_versions()[body.document] != body.version:
        raise error(status.HTTP_409_CONFLICT, "outdated_version", "A newer version of this document exists.")
    db.add(PolicyAcceptance(user_id=principal.user.id, document=body.document, version=body.version))
    audit.record(
        db, actor_user_id=principal.user.id, action="privacy.accepted", entity_type="policy",
        entity_id=body.document.value, after={"version": body.version},
    )
    await db.commit()
