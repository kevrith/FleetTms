"""The quote rules must give exactly the figures the web preview shows: both are checked against one shared file."""

import json
from pathlib import Path

import pytest

from app.quote_rules import from_dict, quote

CASES = json.loads((Path(__file__).resolve().parents[3] / "packages/business-rules/src/quote-cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_matches_the_shared_cases(case):
    got = quote(from_dict(case["input"]))
    want = case["expected"]
    assert got.keys() == want.keys()
    for key, value in want.items():
        assert got[key] == pytest.approx(value) if value is not None else got[key] is None, key
