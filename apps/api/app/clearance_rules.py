"""Whether a trip may start with the documents its driver and vehicle have (masterplan 5.1). Pure rules, server side only: the web and the
phone show what the server worked out and never recompute it. A document is valid through its expiry date and blocks from the next day."""

from datetime import date

MODES = ("off", "warn", "block")
DRIVER_DOCS = ("driving_licence",)
VEHICLE_DOCS = ("insurance", "inspection", "ntsa_licence", "tlb_licence", "permit")
SOON_DAYS = 14  # this close to running out, the driver and owner are told on the trip itself
LABELS = {
    "insurance": "Insurance", "inspection": "Inspection", "ntsa_licence": "NTSA licence", "tlb_licence": "TLB licence",
    "permit": "Permit", "driving_licence": "Driving licence",
}  # fmt: skip


def status_of(expires_on: date | None, today: date, trip_ends_on: date | None = None) -> tuple[str, int | None]:
    """missing, expired, today (the last valid day), soon, ends_during_trip (runs out before the planned end) or ok; and the days left."""
    if expires_on is None:
        return "missing", None
    left = (expires_on - today).days
    if left < 0:
        return "expired", left
    if trip_ends_on is not None and expires_on < trip_ends_on:
        return "ends_during_trip", left
    if left == 0:
        return "today", left
    return ("soon" if left <= SOON_DAYS else "ok"), left


def assess(*, mode: str, today: date, items: list[dict], trip_ends_on: date | None = None) -> dict:
    """`items` are the documents the business requires for this trip: {doc_type, subject ("driver" or "vehicle"), name, expires_on or None}.
    In block mode an expired or missing one stops the trip; in warn mode the same things are said but never stop it; off says nothing."""
    if mode not in MODES or mode == "off":
        return {"mode": "off", "blocked": False, "issues": []}
    issues = []
    for item in items:
        status, left = status_of(item["expires_on"], today, trip_ends_on)
        if status == "ok":
            continue
        issues.append({
            "doc_type": item["doc_type"], "label": LABELS.get(item["doc_type"], item["doc_type"]), "subject": item["subject"], "name": item["name"],
            "status": status, "expires_on": item["expires_on"], "days_left": left, "blocking": mode == "block" and status in ("expired", "missing"),
        })  # fmt: skip
    return {"mode": mode, "blocked": any(i["blocking"] for i in issues), "issues": issues}


def sentence(issue: dict) -> str:
    """One issue in plain words: 'Driving licence for John Mwangi expired on 2026-10-01.'"""
    what = f"{issue['label']} for {issue['name']}"
    when = issue["expires_on"].isoformat() if issue["expires_on"] else ""
    return {
        "missing": f"{what} is not recorded.",
        "expired": f"{what} expired on {when}.",
        "today": f"{what} runs out today ({when}).",
        "soon": f"{what} runs out on {when} ({issue['days_left']} days).",
        "ends_during_trip": f"{what} runs out on {when}, before this trip is planned to end.",
    }[issue["status"]]
