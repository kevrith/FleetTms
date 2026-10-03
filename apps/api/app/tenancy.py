"""Automatic tenant scoping.

Every model that mixes in TenantMixin is filtered by the current business on every SELECT,
UPDATE and DELETE, and stamped with it on INSERT. If no tenant context is set, tenant queries
fail closed with TenantContextError. Cross-tenant work (login, switching company) must opt in
explicitly with `.execution_options(skip_tenant=True)`.
"""

import uuid
from contextvars import ContextVar

from sqlalchemy import ForeignKey, event
from sqlalchemy.orm import (
    Mapped,
    ORMExecuteState,
    Session,
    mapped_column,
    with_loader_criteria,
)

current_business_id: ContextVar[uuid.UUID | None] = ContextVar("current_business_id", default=None)


class TenantContextError(RuntimeError):
    pass


class TenantMixin:
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )


def _mappers_of(state: ORMExecuteState) -> list:
    """The mappers a statement touches, including one that only appears in its FROM clause: `select(func.count()).select_from(Vehicle)`
    names no column of the model, so state.all_mappers alone would miss it and the count would span every business."""
    found = list(state.all_mappers)
    if state.is_select:
        for source in state.statement.get_final_froms():
            entity = getattr(source, "_annotations", {}).get("parententity")
            entity = getattr(entity, "mapper", entity)
            if entity is not None and hasattr(entity, "class_"):
                found.append(entity)
    return found


@event.listens_for(Session, "do_orm_execute")
def _scope_to_tenant(state: ORMExecuteState) -> None:
    if state.execution_options.get("skip_tenant"):
        return
    if not (state.is_select or state.is_update or state.is_delete):
        return
    if not any(issubclass(m.class_, TenantMixin) for m in _mappers_of(state)):
        return
    business_id = current_business_id.get()
    if business_id is None:
        raise TenantContextError("Query on tenant data without a tenant context")
    state.statement = state.statement.options(
        with_loader_criteria(
            TenantMixin,
            lambda cls: cls.business_id == business_id,
            include_aliases=True,
        )
    )


@event.listens_for(Session, "before_flush")
def _stamp_and_guard(session: Session, flush_context, instances) -> None:
    tenant_objects = [o for o in (*session.new, *session.dirty) if isinstance(o, TenantMixin)]
    if not tenant_objects:
        return
    business_id = current_business_id.get()
    if business_id is None:
        raise TenantContextError("Write to tenant data without a tenant context")
    for obj in tenant_objects:
        if obj.business_id is None:
            obj.business_id = business_id
        elif obj.business_id != business_id:
            raise TenantContextError("Write to another tenant's data blocked")
