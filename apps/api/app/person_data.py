"""Everything a business holds about one person, for their right of access and portability (Data Protection Act, 2019).

It is found by structure, not by a list someone has to keep up to date: any record in any table that points at the person's login or
their place in the business is included. A new table that records who did something is therefore covered the day it is added.
Passwords, tokens and two-step keys are never included."""

import csv
import io
import json
import zipfile
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data_export import SECRET_WORDS, _cell
from app.models import Base, Membership
from app.tenancy import current_business_id

ROW_LIMIT = 200_000  # per kind of record; a year of one driver's location points is far below this


def _links(table, target: str):
    return [c for c in table.c if any(fk.column.table.name == target for fk in c.foreign_keys)]


async def build(db: AsyncSession, membership: Membership) -> tuple[bytes, dict[str, int]]:
    business_id = current_business_id.get()
    user = membership.user
    tables = Base.metadata.tables
    out = io.BytesIO()
    counts: dict[str, int] = {}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for table in sorted(tables.values(), key=lambda t: t.name):
            if table.name == "users":
                condition = table.c.id == user.id
            elif table.name == "memberships":
                condition = table.c.id == membership.id
            elif "business_id" in table.c or table.name == "device_logins":
                ties = [c == membership.id for c in _links(table, "memberships")] + [c == user.id for c in _links(table, "users")]
                if not ties:
                    continue
                condition = or_(*ties)
                if "business_id" in table.c:
                    condition = condition & (table.c.business_id == business_id)
            else:
                continue
            columns = [c.name for c in table.c if not any(w in c.name for w in SECRET_WORDS)]
            buffer = io.StringIO(newline="")
            writer = csv.writer(buffer)
            writer.writerow(columns)
            rows = (await db.execute(select(*[table.c[c] for c in columns]).where(condition).limit(ROW_LIMIT))).all()
            if not rows:
                continue
            for row in rows:
                writer.writerow([_cell(v) for v in row])
            counts[table.name] = len(rows)
            zf.writestr(f"{table.name}.csv", buffer.getvalue())
        zf.writestr("manifest.json", json.dumps({"made_at": datetime.now(UTC).isoformat(), "person": user.name, "rows": counts}, indent=1))
        zf.writestr("README.txt", _readme(user.name, counts))
    return out.getvalue(), counts


def _readme(name: str, counts: dict[str, int]) -> str:
    lines = [
        f"A copy of the information held about {name} in FleetTms.", "",
        "Each .csv file is one kind of record that is about this person or was made by them (their details, their trips, the fuel and",
        "expenses they entered, where the phone reported them to be during trips, messages sent to them, their sign-in history and so on).",
        "Times are in UTC and money is in cents. Passwords, tokens and two-step keys are never included.", "",
        "Files and how many records each holds:",
    ]  # fmt: skip
    lines += [f"  {t}.csv: {n}" for t, n in sorted(counts.items())]
    return "\n".join(lines) + "\n"
