"""Helpers for the subscription tests: moving a business's dates, and answering the M-Pesa prompt the way Safaricom would."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app import platform_mpesa
from app.models import Subscription
from tests.helpers import bearer
from tests.leasing import in_db


def callback_body(checkout_id, *, ok=True, amount=None, receipt="QWE1234567", note="The service request is processed successfully."):
    body = {"MerchantRequestID": "m-1", "CheckoutRequestID": checkout_id, "ResultCode": 0 if ok else 1032, "ResultDesc": note if ok else "Request cancelled by user"}
    if ok:
        body["CallbackMetadata"] = {"Item": [{"Name": "Amount", "Value": amount}, {"Name": "MpesaReceiptNumber", "Value": receipt}, {"Name": "PhoneNumber", "Value": 254712345678}]}
    return {"Body": {"stkCallback": body}}


async def answer_prompt(client, *, ok=True, amount=None, receipt="QWE1234567", key=None):
    """Safaricom answering the newest payment request: the amount defaults to what was asked for."""
    sent = platform_mpesa.fake_prompts().sent[-1]
    amount = sent["amount_kes"] if amount is None else amount
    return await client.post(f"/hooks/subscription-pay/{key or platform_mpesa.callback_key()}", json=callback_body(sent["checkout_id"], ok=ok, amount=amount, receipt=receipt))


async def set_dates(trial_ends=None, paid_until="keep"):
    """Moves the trial end and the paid-until date (None clears it), to look at a business as it will be some days from now."""

    async def go(db):
        values = {}
        if trial_ends is not None:
            values["trial_ends_at"] = trial_ends
        if paid_until != "keep":
            values["paid_until"] = paid_until
        await db.execute(update(Subscription).values(**values))

    await in_db(go)


def days(n: float) -> datetime:
    return datetime.now(UTC) + timedelta(days=n)


async def subscription(client, who):
    res = await client.get("/subscription", headers=bearer(who))
    assert res.status_code == 200, res.text
    return res.json()


async def pay_invoice(client, who, phone="0712345678"):
    """Raises the next invoice, asks for payment, and has Safaricom say yes. Returns the paid invoice's status response."""
    invoice = (await client.post("/subscription/invoices", headers=bearer(who))).json()
    res = await client.post(f"/subscription/invoices/{invoice['id']}/pay", headers=bearer(who), json={"phone": phone})
    assert res.status_code == 200, res.text
    assert (await answer_prompt(client)).status_code == 200
    return (await client.get(f"/subscription/invoices/{invoice['id']}", headers=bearer(who))).json()
