"""The report catalogue (masterplan 5.15): list the reports a person may run, run one for any period up to a year, and export it as PDF or
Excel. The older /reports/summary and /reports/export keep working."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import plan_rules, report_catalog, subscriptions
from app.db import get_db
from app.deps import Principal, current_principal, error

router = APIRouter(tags=["reports"])


def _allowed(principal: Principal, definition: report_catalog.Report) -> bool:
    return any(p in principal.permissions for p in definition.permissions)


async def _run(db: AsyncSession, principal: Principal, key: str, start: date | None, end: date | None) -> dict:
    if key not in report_catalog.CATALOG:
        raise error(404, "not_found", "There is no such report.")
    definition, build = report_catalog.CATALOG[key]
    if not _allowed(principal, definition):
        raise error(403, "forbidden", "You do not have permission to see that report.")
    if definition.feature:
        await subscriptions.require_feature(db, principal.business_id, definition.feature)
    start, end = report_catalog.check_range(start, end)
    if end < start:
        raise error(422, "bad_range", "The end date is before the start date.")
    if (end - start).days >= report_catalog.MAX_DAYS:
        raise error(422, "range_too_long", "Choose a range of a year or less.")
    return await build(db, start, end, principal)


@router.get("/report-catalog")
async def catalog(principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    """The reports this person may run, and whether the plan has them yet."""
    access = await subscriptions.access_for(db, principal.business_id) if principal.business_id else {"complimentary": True}
    fleet = plan_rules.best_plan([subscriptions.effective_plan(v.plan, access) for v in await subscriptions.active_vehicles(db)]) if principal.business_id else "premium"
    out = []
    for key, (d, _) in report_catalog.CATALOG.items():
        if not _allowed(principal, d):
            continue
        plan_ok = d.feature is None or access.get("complimentary") or not subscriptions.settings.enforce_plans or plan_rules.allows(fleet, d.feature)
        out.append({"key": key, "title": d.title, "description": d.description, "has_period": d.period, "available": bool(plan_ok), "plan_needed": plan_rules.FEATURES.get(d.feature) if d.feature else None})
    return out


@router.get("/report-catalog/{key}")
async def run_report(key: str, start: date | None = None, end: date | None = None, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    return await _run(db, principal, key, start, end)


@router.get("/report-catalog/{key}/export")
async def export_report(key: str, file_format: Literal["pdf", "xlsx"] = "pdf", start: date | None = None, end: date | None = None, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    data = await _run(db, principal, key, start, end)
    body, name, mime = report_catalog.render(data, file_format)
    return Response(content=body, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})
