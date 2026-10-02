import pytest

from app.phone import normalize_phone


@pytest.mark.parametrize(
    "raw",
    ["0712345678", "+254712345678", "254712345678", "712345678", "0712 345 678", "0112345678"],
)
def test_kenyan_numbers_normalise(raw):
    assert normalize_phone(raw) in ("+254712345678", "+254112345678")


@pytest.mark.parametrize("raw", ["", "12345", "0612345678", "+1 202 555 0100", "07123456789"])
def test_invalid_numbers_rejected(raw):
    assert normalize_phone(raw) is None
