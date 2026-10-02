"""KRA eTIMS (masterplan 5.10): what an invoice looks like to KRA, and how long to wait before trying again.

Written to KRA's OSCU specification from its documentation. It has not yet been run against KRA's sandbox (that needs
the business's own registered device), so treat field names and codes as the first thing to check there."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.billing_rules import half

NAIROBI = ZoneInfo("Africa/Nairobi")
# Minutes to wait after the 1st, 2nd, ... failed attempt. After the last one the invoice goes to a person.
RETRY_MINUTES = (5, 15, 60, 240, 720, 1440, 1440, 1440)
TAX_RATES = {"A": 0, "B": 16, "C": 0, "D": 0, "E": 8}  # A exempt, B 16 percent, C zero-rated, D not VAT, E 8 percent
REFUND_REASON_OTHER = "13"


class EtimsRuleError(Exception):
    """The invoice cannot be described to eTIMS as it is. The text says what to fix."""


def retry_delay_minutes(attempts: int) -> int | None:
    """How long to wait after `attempts` failures, or None when it is time to stop retrying."""
    return RETRY_MINUTES[attempts - 1] if 1 <= attempts <= len(RETRY_MINUTES) else None


def tax_code(vat_pct: float, zero_code: str) -> str:
    """The eTIMS tax code for a VAT rate. A rate of nothing uses the business's choice (exempt, zero-rated or not VAT)."""
    rate = float(vat_pct)
    if rate == 16:
        return "B"
    if rate == 8:
        return "E"
    if rate == 0:
        return zero_code
    raise EtimsRuleError(f"eTIMS has no tax code for VAT of {rate:g} percent. Use 16, 8 or 0 for this client.")


def _money(cents: int) -> float:
    return float(Decimal(cents) / 100)


def split_vat(lines_cents: list[int], vat_pct: float, vat_total_cents: int) -> list[int]:
    """Each line's share of the invoice's VAT, adding up exactly to the invoice's VAT (the last line takes the rounding)."""
    shares = [half(c * float(vat_pct) / 100) for c in lines_cents]
    if shares:
        shares[-1] = vat_total_cents - sum(shares[:-1])
    return shares


def build_sale(
    *, tin: str, branch_id: str, invoice_no: int, original_no: int | None, business_name: str, client_name: str, client_pin: str | None, client_phone: str | None,
    lines: list[dict], vat_pct: float, vat_cents: int, zero_code: str, item_code: str, item_class_code: str, pkg_unit: str, qty_unit: str,
    issued_at: datetime, credit_note: bool,
) -> dict:  # fmt: skip
    """The body KRA's saveTrnsSalesOsdc call takes. `lines` are {description, amount_cents} before VAT; lines with
    nothing to pay (the trips a monthly fee covers) are left out, since eTIMS does not take zero-priced items."""
    items = [ln for ln in lines if ln["amount_cents"] > 0]
    if not items:
        raise EtimsRuleError("The invoice has nothing to charge, so there is nothing to send to eTIMS.")
    code = tax_code(vat_pct, zero_code)
    shares = split_vat([ln["amount_cents"] for ln in items], vat_pct, vat_cents)
    stamp = issued_at.astimezone(NAIROBI)
    item_list = []
    for n, (ln, vat) in enumerate(zip(items, shares, strict=True), start=1):
        item_list.append({
            "itemSeq": n, "itemCd": item_code, "itemClsCd": item_class_code, "itemNm": ln["description"][:200], "pkgUnitCd": pkg_unit, "pkg": 1,
            "qtyUnitCd": qty_unit, "qty": 1, "prc": _money(ln["amount_cents"]), "splyAmt": _money(ln["amount_cents"]), "dcRt": 0, "dcAmt": 0,
            "taxTyCd": code, "taxblAmt": _money(ln["amount_cents"]), "taxAmt": _money(vat), "totAmt": _money(ln["amount_cents"] + vat),
        })  # fmt: skip
    taxable = sum(ln["amount_cents"] for ln in items)
    body: dict = {
        "tin": tin, "bhfId": branch_id, "invcNo": invoice_no, "orgInvcNo": original_no or 0, "custTin": client_pin, "custNm": client_name[:60],
        "salesTyCd": "N", "rcptTyCd": "R" if credit_note else "S", "pmtTyCd": "02", "salesSttsCd": "02", "cfmDt": stamp.strftime("%Y%m%d%H%M%S"),
        "salesDt": stamp.strftime("%Y%m%d"), "stockRlsDt": None, "cnclReqDt": None, "cnclDt": None, "rfdDt": stamp.strftime("%Y%m%d%H%M%S") if credit_note else None,
        "rfdRsnCd": REFUND_REASON_OTHER if credit_note else None, "totItemCnt": len(item_list), "totTaxblAmt": _money(taxable), "totTaxAmt": _money(vat_cents),
        "totAmt": _money(taxable + vat_cents), "prchrAcptcYn": "N", "remark": None, "regrId": "FleetTms", "regrNm": "FleetTms", "modrId": "FleetTms", "modrNm": "FleetTms",
        "receipt": {"custTlNo": client_phone, "prchrAcptcYn": "N", "trdeNm": business_name[:100], "topMsg": business_name[:100], "btmMsg": "Thank you for your business"},
        "itemList": item_list,
    }  # fmt: skip
    for letter, rate in TAX_RATES.items():
        on = letter == code
        body[f"taxblAmt{letter}"] = _money(taxable) if on else 0
        body[f"taxRt{letter}"] = rate
        body[f"taxAmt{letter}"] = _money(vat_cents) if on else 0
    return body


def qr_data(tin: str, branch_id: str, receipt_signature: str) -> str:
    """What the QR code on an eTIMS invoice holds: a KRA page that checks the receipt."""
    return f"https://etims.kra.go.ke/common/link/etims/receipt/indexEtimsReceiptData?Data={tin}{branch_id}{receipt_signature}"
