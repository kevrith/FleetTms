from datetime import date

import pytest

from app import document_rules as d

TODAY = date(2026, 10, 3)


@pytest.mark.parametrize(("raw", "expected"), [("kca123a", "KCA 123A"), ("KCA  123 A", "KCA 123A"), ("kca-123a", "KCA 123A"), ("GKA 001", "GKA001"), (None, None), ("", None)])
def test_a_number_plate_is_tidied(raw, expected):
    assert d.plate(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), [("qwe1234567", "QWE1234567"), ("QWE 123 4567", "QWE1234567"), ("short", None), (None, None)])
def test_an_mpesa_code_is_ten_letters_and_digits(raw, expected):
    assert d.mpesa_code(raw) == expected


def test_numbers_dates_and_text_are_cleaned_whatever_the_receipt_wrote():
    f = d.normalise("fuel_receipt", {"litres": "120.5 L", "price_per_litre": "KES 185.00", "amount": "22,292.50", "date": "03/10/2026", "station": "  Total   ", "fuel_type": None, "ignored": "x"})
    assert f == {"station": "Total", "fuel_type": None, "litres": 120.5, "price_per_litre": 185.0, "amount": 22292.5, "receipt_no": None, "mpesa_code": None, "date": "2026-10-03"}
    w = d.normalise("weighbridge_ticket", {"gross_kg": "45,200 kg", "tare_kg": 14000.4, "net_kg": "31200", "registration": "kca123a", "date": "2026-10-03T08:00:00+03:00"})
    assert w["gross_kg"] == 45200 and w["tare_kg"] == 14000 and w["net_kg"] == 31200 and w["registration"] == "KCA 123A" and w["date"] == "2026-10-03"
    assert d.normalise("logbook", {"year": "2018", "registration": "KCA123A"})["year"] == 2018 and d.normalise("fuel_receipt", {"litres": "n/a"})["litres"] is None


def test_a_fuel_receipt_that_does_not_add_up_is_pointed_out():
    f = d.normalise("fuel_receipt", {"litres": 100, "price_per_litre": 185, "amount": 20000, "date": "2026-10-03"})
    got = d.check("fuel_receipt", f, today=TODAY)
    assert got["missing"] == [] and len(got["warnings"]) == 1 and "100 litres at 185 is 18,500.00, but the total read is 20,000.00" in got["warnings"][0]
    assert d.check("fuel_receipt", d.normalise("fuel_receipt", {"litres": 100, "price_per_litre": 18.5, "amount": 1850}), today=TODAY)["warnings"][0].startswith("A price of 18.5 a litre")
    assert d.check("fuel_receipt", d.normalise("fuel_receipt", {"litres": 5000, "amount": 900000}), today=TODAY)["warnings"][0].startswith("5000 litres is more than a tank holds")
    assert "in the future" in d.check("fuel_receipt", d.normalise("fuel_receipt", {"litres": 10, "amount": 1850, "date": "2026-12-01"}), today=TODAY)["warnings"][0]
    assert "more than 30 days old" in d.check("fuel_receipt", d.normalise("fuel_receipt", {"litres": 10, "amount": 1850, "date": "2026-08-01"}), today=TODAY)["warnings"][0]
    assert d.check("fuel_receipt", d.normalise("fuel_receipt", {"station": "Total"}), today=TODAY)["missing"] == ["litres", "amount"]


def test_a_weighbridge_ticket_is_checked_against_itself_and_the_vehicle():
    f = d.normalise("weighbridge_ticket", {"gross_kg": 45200, "tare_kg": 14000, "net_kg": 30000, "registration": "KCB 222B"})
    got = d.check("weighbridge_ticket", f, registration="KCA 123A", gvw_limit_kg=44000)
    assert len(got["warnings"]) == 3
    assert "Gross 45,200 less tare 14,000 is 31,200 kg, but the net read is 30,000 kg" in got["warnings"][0] and "over this vehicle's legal limit of 44,000 kg" in got["warnings"][1] and "for KCB 222B, but you chose KCA 123A" in got["warnings"][2]
    ok = d.normalise("weighbridge_ticket", {"gross_kg": 43000, "tare_kg": 14000, "net_kg": 29000, "registration": "kca123a"})
    assert d.check("weighbridge_ticket", ok, registration="KCA 123A", gvw_limit_kg=44000)["warnings"] == []


def test_insurance_dates_and_the_logbook_year_are_checked():
    f = d.normalise("insurance_certificate", {"policy_no": "P1", "valid_from": "2026-06-01", "valid_to": "2026-05-01"})
    assert d.check("insurance_certificate", f, today=TODAY)["warnings"][0].startswith("The cover ends before it starts")
    old = d.normalise("insurance_certificate", {"policy_no": "P1", "valid_from": "2025-01-01", "valid_to": "2025-12-31"})
    assert d.check("insurance_certificate", old, today=TODAY)["warnings"] == ["This certificate has already expired."]
    assert d.check("insurance_certificate", d.normalise("insurance_certificate", {"insurer": "Jubilee"}), today=TODAY)["missing"] == ["policy_no", "valid_to"]
    assert "not possible" in d.check("logbook", d.normalise("logbook", {"registration": "KCA123A", "year": 1890}), today=TODAY)["warnings"][0]
