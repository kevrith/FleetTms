import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog

# Never write these into audit snapshots.
_REDACT = {"password_hash", "totp_secret", "refresh_hash", "invite_token_hash", "code_hash"}


def snapshot(obj: Any, fields: list[str]) -> dict:
    out = {}
    for f in fields:
        if f in _REDACT:
            continue
        v = getattr(obj, f)
        out[f] = str(v) if isinstance(v, uuid.UUID) else getattr(v, "value", v)
    return out


def record(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: Any = None,
    before: dict | None = None,
    after: dict | None = None,
    note: str | None = None,
) -> None:
    """Adds an audit entry to the current transaction, so it commits or rolls back with the change."""
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            before=before,
            after=after,
            note=note,
        )
    )
