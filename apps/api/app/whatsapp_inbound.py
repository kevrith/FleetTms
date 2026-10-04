"""What Meta sends to /hooks/whatsapp: reports on messages we sent (sent, delivered, read, failed) and replies. A supplier answers an order
by pressing a button on it: "Confirm" moves the order to confirmed, "Cannot supply" tells the managers by text. Messages are found by
the id Meta gave them, and a reply counts only from the number the order was sent to; anything else is ignored.

This works across businesses (the message is found before its business is known), then sets the business for everything it changes."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.models import PartsOrder, Supplier, WhatsAppMessage
from app.phone import normalize_phone
from app.tenancy import current_business_id
from app.tracking_jobs import notify_managers
from app.whatsapp import BUTTONS, apply_report

log = logging.getLogger(__name__)


async def _message(db: AsyncSession, wa_message_id: str) -> WhatsAppMessage | None:
    return (await db.execute(select(WhatsAppMessage).where(WhatsAppMessage.wa_message_id == wa_message_id).execution_options(skip_tenant=True))).scalar_one_or_none()


def _items(value: object) -> list[dict]:
    """The objects in a list, whatever else is in it: a delivery is only trusted as far as its signature, not for its shape."""
    return [i for i in value if isinstance(i, dict)] if isinstance(value, list) else []


def _at(stamp: str | None) -> datetime:
    try:
        return datetime.fromtimestamp(int(stamp or 0), UTC) if stamp else datetime.now(UTC)
    except (ValueError, OSError, OverflowError):
        return datetime.now(UTC)


async def _answer_to_order(db: AsyncSession, row: WhatsAppMessage, choice: str, at: datetime) -> None:
    order = (await db.execute(select(PartsOrder).where(PartsOrder.id == row.entity_id))).scalar_one_or_none()
    if order is None:
        return
    supplier = (await db.execute(select(Supplier).where(Supplier.id == order.supplier_id))).scalar_one_or_none()
    name = supplier.name if supplier else "The supplier"
    if choice == "confirm":
        if order.status == "sent":
            order.status, order.confirmed_at = "confirmed", at
        audit.record(db, actor_user_id=None, action="order.confirmed_on_whatsapp", entity_type="parts_order", entity_id=order.id, after={"number": order.number, "status": order.status}, note=f"{name} pressed Confirm on WhatsApp")
    else:
        audit.record(db, actor_user_id=None, action="order.declined_on_whatsapp", entity_type="parts_order", entity_id=order.id, after={"number": order.number}, note=f"{name} pressed Cannot supply on WhatsApp")
        await notify_managers(db, f"{name} cannot supply order {order.number} (WhatsApp reply). Open the order to choose another supplier.")


async def process(db: AsyncSession, payload: dict) -> dict:
    """Applies everything in one delivery from Meta. Returns how many reports and replies changed something."""
    changed = {"reports": 0, "replies": 0}
    for entry in _items(payload.get("entry")):
        for change in _items(entry.get("changes")):
            value = change.get("value") if isinstance(change.get("value"), dict) else {}
            for report in _items(value.get("statuses")):
                row = await _message(db, str(report.get("id") or ""))
                if row is None:
                    continue
                current_business_id.set(row.business_id)
                before = row.status
                apply_report(row, str(report.get("status") or ""), _items(report.get("errors")), _at(report.get("timestamp")))
                changed["reports"] += row.status != before
                await db.flush()  # inside this row's business: an entry added now would take whichever business is set at the next flush
            for message in _items(value.get("messages")):
                context, button = message.get("context"), message.get("button")
                original = str(context.get("id") or "") if isinstance(context, dict) else ""
                payload_text = str(button.get("payload") or "") if isinstance(button, dict) else ""
                if message.get("type") != "button" or payload_text not in BUTTONS or not original:
                    continue
                row = await _message(db, original)
                if row is None or row.purpose != "order" or row.reply is not None or normalize_phone(str(message.get("from") or "")) != row.to_phone:
                    continue  # not ours, not an answer to an order, already answered, or from some other number
                current_business_id.set(row.business_id)
                row.reply, row.replied_at = payload_text, _at(message.get("timestamp"))
                await _answer_to_order(db, row, payload_text, row.replied_at)
                await db.flush()
                changed["replies"] += 1
    return changed
