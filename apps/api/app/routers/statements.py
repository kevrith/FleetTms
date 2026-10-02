"""M-Pesa statement import (masterplan 5.10): upload the business's statement, see what matched what, and what did not."""

import uuid

from fastapi import APIRouter, Depends, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import Principal, error, require_any
from app.models import MpesaStatementImport, MpesaStatementLine
from app.mpesa_statement import MAX_BYTES, StatementError, import_statement, parse

router = APIRouter(tags=["statements"])
MANAGE = ("invoices.manage",)
KINDS = {"fuel": "Fuel", "expense": "Expense", "float": "Float", "client_payment": "Client payment", "lease": "Lease payment", "finance": "Loan repayment", "advance": "Salary advance"}


class IgnoreIn(BaseModel):
    note: str = Field(min_length=3, max_length=255)


def line_out(ln: MpesaStatementLine) -> dict:
    return {
        "id": ln.id, "receipt": ln.receipt, "completed_at": ln.completed_at, "details": ln.details, "paid_in_cents": ln.paid_in_cents, "withdrawn_cents": ln.withdrawn_cents,
        "match_kind": ln.match_kind, "match_label": KINDS.get(ln.match_kind or ""), "match_id": ln.match_id, "state": ln.state, "note": ln.note,
    }  # fmt: skip


def import_out(i: MpesaStatementImport) -> dict:
    return {"id": i.id, "filename": i.filename, "rows": i.rows, "new_rows": i.new_rows, "period_start": i.period_start, "period_end": i.period_end, "summary": i.summary, "created_at": i.created_at}


@router.post("/payments/statements", status_code=status.HTTP_201_CREATED)
async def upload_statement(file: UploadFile, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Reads a statement and matches it. Safe to upload again: a line already imported is not added twice."""
    content = await file.read(MAX_BYTES + 1)
    try:
        lines, skipped = parse(content, file.filename)
    except StatementError as e:
        raise error(422, "bad_statement", str(e)) from None
    imported = await import_statement(db, lines, skipped, filename=file.filename, user_id=principal.user.id)
    audit.record(db, actor_user_id=principal.user.id, action="mpesa.statement_imported", entity_type="mpesa_statement_import", entity_id=imported.id, after={"rows": imported.rows, "new_rows": imported.new_rows})
    await db.commit()
    return import_out(imported)


@router.get("/payments/statements")
async def list_imports(principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    return [import_out(i) for i in (await db.execute(select(MpesaStatementImport).order_by(MpesaStatementImport.created_at.desc()).limit(50))).scalars()]


@router.get("/payments/statements/lines")
async def list_lines(state: str | None = None, direction: str | None = None, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Statement lines, newest first. `state`: matched, amount_differs, unmatched or ignored. `direction`: in or out."""
    query = select(MpesaStatementLine).order_by(MpesaStatementLine.completed_at.desc()).limit(500)
    if state == "attention":
        query = query.where(MpesaStatementLine.state.in_(("unmatched", "amount_differs")))
    elif state:
        query = query.where(MpesaStatementLine.state == state)
    if direction == "out":
        query = query.where(MpesaStatementLine.withdrawn_cents > 0)
    elif direction == "in":
        query = query.where(MpesaStatementLine.paid_in_cents > 0)
    return [line_out(ln) for ln in (await db.execute(query)).scalars()]


@router.post("/payments/statements/lines/{line_id}/ignore")
async def ignore_line(line_id: uuid.UUID, body: IgnoreIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Marks a line as looked at and not a problem (for example a personal transfer), with the reason."""
    line = (await db.execute(select(MpesaStatementLine).where(MpesaStatementLine.id == line_id))).scalar_one_or_none()
    if line is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That line was not found.")
    if line.state == "matched":
        raise error(status.HTTP_409_CONFLICT, "already_matched", "That line is already matched.")
    line.state, line.note = "ignored", body.note
    audit.record(db, actor_user_id=principal.user.id, action="mpesa.statement_line_ignored", entity_type="mpesa_statement_line", entity_id=line.id, after={"receipt": line.receipt}, note=body.note)
    await db.commit()
    return line_out(line)
