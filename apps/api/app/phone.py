import re


def normalize_phone(raw: str) -> str | None:
    """Return a Kenyan number as +2547XXXXXXXX / +2541XXXXXXXX, or None if it is not valid."""
    digits = re.sub(r"[\s\-()]", "", raw)
    digits = digits.removeprefix("+")
    if digits.startswith("0"):
        digits = "254" + digits[1:]
    elif digits[:1] in ("7", "1") and len(digits) == 9:
        digits = "254" + digits
    if re.fullmatch(r"254[71]\d{8}", digits):
        return "+" + digits
    return None


def mask_phone(phone: str) -> str:
    return phone[:5] + "****" + phone[-2:]
