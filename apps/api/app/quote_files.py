"""A quote as a PDF the client can read, for email and WhatsApp (masterplan 5.17)."""

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models import Client, Quote, SavedRoute

METHODS = {"per_trip": "Per trip", "per_tonne": "Per tonne", "per_km": "Per kilometre", "monthly_contract": "Monthly contract"}


def kes(cents: int) -> str:
    return f"KES {cents / 100:,.2f}"


def quote_pdf(quote: Quote, client: Client, route: SavedRoute | None, business: str) -> bytes:
    """What the client sees: the work and the price. Costs and profit are ours and are never printed."""
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, title=f"Quote {quote.number}", leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    story: list = [Paragraph(business, styles["Title"]), Paragraph(f"Quote {quote.number}", styles["Heading2"]), Paragraph(f"For: {client.name}", styles["Normal"])]
    if quote.valid_until:
        story.append(Paragraph(f"Valid until {quote.valid_until.isoformat()}", styles["Normal"]))
    story.append(Spacer(1, 12))
    rows = [["Item", "Detail"]]
    if route:
        rows.append(["Route", f"{route.pickup} to {route.dropoff} ({quote.distance_km:,} km)"])
    if quote.cargo_description:
        rows.append(["Cargo", quote.cargo_description])
    if float(quote.weight_tonnes) > 0:
        rows.append(["Weight", f"{float(quote.weight_tonnes):,.2f} tonnes"])
    rows += [["Trips", str(quote.trips)], ["Charged", METHODS[quote.billing_method.value]]]
    if quote.pickup_at:
        rows.append(["Pickup", quote.pickup_at.strftime("%d %b %Y %H:%M")])
    if quote.deliver_by:
        rows.append(["Deliver by", quote.deliver_by.strftime("%d %b %Y %H:%M")])
    rows.append(["Price", kes(quote.price_cents)])
    table = Table(rows, colWidths=[110, 380])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
    ]))  # fmt: skip
    story.append(table)
    if quote.instructions:
        story += [Spacer(1, 12), Paragraph(f"Notes: {quote.instructions}", styles["Normal"])]
    doc.build(story)
    return out.getvalue()
