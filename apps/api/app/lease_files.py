"""A lease statement as a PDF, to send to the lessor or lessee: period, what the charge was built from, offsets, payments and the
balance. Clear numbers up front keep arguments out of it (masterplan 5.23)."""

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

STYLES = getSampleStyleSheet()
LABELS = {"charge": "Charge", "offset": "Offset", "payment": "Payment", "adjustment": "Adjustment"}
USAGE = {"trips": "Trips", "km": "Kilometres", "revenue_cents": "Revenue", "profit_cents": "Profit"}


def kes(cents: int) -> str:
    return f"KES {cents / 100:,.2f}"


def _table(rows: list[list], widths: list[int], header: bool = True) -> Table:
    t = Table(rows, colWidths=widths)
    style = [("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("ALIGN", (-1, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP")]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    t.setStyle(TableStyle(style))
    return t


def statement_pdf(st: dict, business: str) -> bytes:
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, title=f"Lease statement {st['vehicle']} {st['month']:%B %Y}", leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40)
    s = STYLES
    owed_to = "us" if st["direction"] == "out" else st["party"]
    story: list = [
        Paragraph(business, s["Title"]),
        Paragraph(f"Lease statement: {st['vehicle']}, {st['month']:%B %Y}", s["Heading2"]),
        Paragraph(f"{'Lessee' if st['direction'] == 'out' else 'Lessor'}: {st['party']}", s["Normal"]),
        Spacer(1, 10),
    ]
    if st["usage"]:
        story += [Paragraph("What the charge was based on", s["Heading4"]), _table([["Measure", "Value"]] + [[USAGE[k], kes(v) if k.endswith("_cents") else f"{v:,}"] for k, v in st["usage"].items()], [380, 145])]
        story.append(Spacer(1, 8))
    rows = [["Description", "Type", "Amount"], ["Balance brought forward", "", kes(st["opening_balance_cents"])]]
    for ln in st["lines"]:
        rows.append([Paragraph(ln["description"], s["BodyText"]), LABELS[ln["kind"]], kes(ln["amount_cents"])])
    rows.append(["Balance at the end of the month", "", kes(st["closing_balance_cents"])])
    story.append(_table(rows, [330, 80, 115]))
    story += [Spacer(1, 8), Paragraph(f"Balance now owed {'to ' + owed_to if st['direction'] == 'in' else 'by the lessee'}: <b>{kes(st['balance_cents'])}</b>", s["Normal"])]
    if st["overdue_cents"]:
        story.append(Paragraph(f"Of which overdue: {kes(st['overdue_cents'])}", s["Normal"]))
    if st["deposit_cents"]:
        story.append(Paragraph(f"Security deposit held: {kes(st['deposit_cents'])}", s["Normal"]))
    if st["trips"]:
        story += [Spacer(1, 8), Paragraph("Trips this month", s["Heading4"]), _table([["Delivered", "Route", "Km"]] + [[t["delivered_at"].strftime("%d %b"), t["route"], f"{t['distance_km']:,}"] for t in st["trips"]], [90, 345, 90])]
    doc.build(story)
    return out.getvalue()
