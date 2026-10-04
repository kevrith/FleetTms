"""An invoice as a PDF. A trip invoice carries its proof of delivery as a second page (the delivery note, the cargo, the
signature, who received it and where), which settles "we never received it" (masterplan 5.18)."""

import io
import uuid

from PIL import Image, ImageDraw
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Image as PdfImage
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.etims_rules import qr_data
from app.models import (
    Business,
    Client,
    EtimsSubmission,
    Invoice,
    Photo,
    PlatformEtimsSubmission,
    ProofOfDelivery,
    SubscriptionInvoice,
    Trip,
)
from app.reminders import NAIROBI

STYLES = getSampleStyleSheet()


def kes(cents: int) -> str:
    return f"KES {cents / 100:,.2f}"


def _photo_flow(photo: Photo | None, images: dict, width: int = 230) -> PdfImage | None:
    """A photo shrunk to fit the page, or None if the file is missing. `images` holds the stored bytes, by photo id."""
    data = images.get(photo.id) if photo else None
    if data is None:
        return None
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((900, 900))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70)
    buf.seek(0)
    w, h = img.size
    return PdfImage(buf, width=width, height=width * h / w)


def signature_png(strokes: list[list[list[float]]]) -> bytes:
    """The recipient's pen strokes drawn on a white box."""
    points = [p for s in strokes for p in s]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    span_x, span_y = max(max(xs) - min(xs), 1), max(max(ys) - min(ys), 1)
    w, h, pad = 600, 220, 16
    scale = min((w - 2 * pad) / span_x, (h - 2 * pad) / span_y)
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    for stroke in strokes:
        xy = [((x - min(xs)) * scale + pad, (y - min(ys)) * scale + pad) for x, y in stroke]
        if len(xy) == 1:
            xy = [xy[0], (xy[0][0] + 1, xy[0][1] + 1)]
        draw.line(xy, fill="black", width=4, joint="curve")
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _table(rows: list[list], widths: list[int], header: bool = True) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP")]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    table.setStyle(TableStyle(style))
    return table


def _qr(text: str, size: int = 90) -> Drawing:
    widget = QrCodeWidget(text)
    x0, y0, x1, y1 = widget.getBounds()
    drawing = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
    drawing.add(widget)
    return drawing


def invoice_pdf(
    invoice: Invoice, client: Client, business: str, *, pod: ProofOfDelivery | None = None, photos: dict | None = None, trip: Trip | None = None,
    pay_info: str | None = None, etims: EtimsSubmission | None = None, tin: str | None = None, branch_id: str = "00",
    images: dict | None = None,
) -> bytes:
    photos = photos or {}
    images = images or {}
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, title=f"Invoice {invoice.number}", leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40)
    s = STYLES
    story: list = [Paragraph(business, s["Title"]), Paragraph(f"Invoice {invoice.number}", s["Heading2"])]
    bill = f"{client.name}" + (f"<br/>KRA PIN {client.kra_pin}" if client.kra_pin else "")
    story += [Paragraph(f"Bill to: {bill}", s["Normal"]), Paragraph(f"Issued {invoice.issue_date.isoformat()}, due {invoice.due_date.isoformat()}", s["Normal"])]
    if invoice.period_start:
        story.append(Paragraph(f"Period: {invoice.period_start.isoformat()} to {invoice.period_end.isoformat()}", s["Normal"]))
    story.append(Spacer(1, 10))
    rows = [["Description", "Qty", "Unit", "Amount"]]
    for line in invoice.lines:
        qty = f"{float(line.quantity):,.3f}".rstrip("0").rstrip(".")
        rows.append([Paragraph(line.description, s["BodyText"]), qty, kes(line.unit_cents) if line.unit_cents else "", kes(line.amount_cents) if line.amount_cents else "Included"])
    story.append(_table(rows, [290, 55, 85, 95]))
    story.append(Spacer(1, 8))
    totals = [["Subtotal", kes(invoice.subtotal_cents)]]
    if invoice.vat_cents or float(invoice.vat_pct):
        totals.append([f"VAT {float(invoice.vat_pct):g}%", kes(invoice.vat_cents)])
    totals += [["Total", kes(invoice.total_cents)], ["Paid", kes(invoice.paid_cents)], ["Balance due", kes(max(0, invoice.total_cents - invoice.paid_cents) if invoice.status != "void" else 0)]]
    story.append(_table(totals, [380, 145], header=False))
    if pay_info and invoice.status != "void":
        story += [Spacer(1, 8), Paragraph(pay_info, s["Normal"])]
    if etims is not None and etims.status == "submitted" and etims.receipt_no:
        facts = [f"KRA eTIMS receipt no. {etims.receipt_no}"] + ([f"Control unit {etims.sdc_id}"] if etims.sdc_id else []) + ([f"Internal data {etims.internal_data}"] if etims.internal_data else [])
        block = [Paragraph("<br/>".join(facts), s["BodyText"])]
        if tin and etims.receipt_signature:
            block.insert(0, _qr(qr_data(tin, branch_id, etims.receipt_signature)))
        story += [Spacer(1, 8), Table([block], colWidths=[100, 425] if len(block) == 2 else [525])]
    if invoice.payments:
        story += [Spacer(1, 8), Paragraph("Payments received", s["Heading4"])]
        story.append(_table([["Date", "Method", "Reference", "Amount"]] + [[p.received_on.isoformat(), p.method, p.reference or "", kes(p.amount_cents)] for p in invoice.payments], [90, 90, 160, 130]))
    if invoice.status == "void":
        story += [Spacer(1, 8), Paragraph(f"VOID: {invoice.void_reason or ''}", s["Heading3"])]

    if pod is not None:
        story += [PageBreak(), Paragraph("Proof of delivery", s["Title"]), Paragraph(f"For invoice {invoice.number}", s["Normal"]), Spacer(1, 8)]
        when = pod.captured_at.astimezone(NAIROBI).strftime("%d %b %Y %H:%M")
        facts = [["Received by", pod.recipient_name], ["Confirmed", f"{when} (Nairobi time)"], ["Confirmed by", "One-time code sent to the client's phone" if pod.method == "code" else "Signature"]]
        if pod.lat is not None and pod.lng is not None:
            facts.append(["Location", f"{pod.lat:.5f}, {pod.lng:.5f}" + ("  (outside the client's site)" if "outside_site" in pod.flags else "")])
        if trip is not None and trip.loaded_weight_kg:
            facts.append(["Weight (weighbridge)", f"{trip.loaded_weight_kg / 1000:,.3f} tonnes"])
        if pod.shortage_qty:
            facts.append(["Shortage", f"{float(pod.shortage_qty):g} {pod.shortage_unit or ''}".strip()])
        if pod.damage_notes:
            facts.append(["Damage", pod.damage_notes])
        story.append(_table([[Paragraph(str(c), s["BodyText"]) for c in r] for r in facts], [140, 385], header=False))
        story.append(Spacer(1, 10))
        shown: list = []
        for caption, photo in (("Signed delivery note", photos.get(pod.note_photo_id)), ("Cargo delivered", photos.get(pod.cargo_photo_id)), ("Weighbridge ticket", photos.get(trip.weighbridge_photo_id) if trip else None)):
            flow = _photo_flow(photo, images)
            if flow is not None:
                shown.append([Paragraph(caption, s["Heading5"]), flow])
        if pod.signature:
            sig = PdfImage(io.BytesIO(signature_png(pod.signature)), width=230, height=84)
            shown.append([Paragraph("Signature", s["Heading5"]), sig])
        for pid in pod.damage_photo_ids:
            flow = _photo_flow(photos.get(uuid.UUID(pid)), images)
            if flow is not None:
                shown.append([Paragraph("Damage", s["Heading5"]), flow])
        # two to a row
        grid = [shown[i : i + 2] for i in range(0, len(shown), 2)]
        for row in grid:
            cells = [[c for c in item] for item in row]
            story.append(Table([cells], colWidths=[262] * len(cells)))
            story.append(Spacer(1, 8))
    doc.build(story)
    return out.getvalue()


def subscription_invoice_pdf(
    invoice: SubscriptionInvoice, business: Business, *, description: str, net_cents: int, vat_cents: int, vat_pct: float, seller_pin: str | None,
    branch_id: str = "00", etims: PlatformEtimsSubmission | None = None,
) -> bytes:
    """What FleetTms charges a business for its subscription or a text bundle. Once paid it is the tax invoice, with KRA's receipt on it."""
    out = io.BytesIO()
    paid = invoice.status == "paid"
    doc = SimpleDocTemplate(out, pagesize=A4, title=f"Invoice {invoice.number}", leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40)
    s = STYLES
    story: list = [Paragraph("FleetTms", s["Title"]), Paragraph(("Tax invoice " if paid else "Invoice ") + invoice.number, s["Heading2"])]
    if seller_pin:
        story.append(Paragraph(f"Seller KRA PIN {seller_pin}", s["Normal"]))
    bill = business.name + (f"<br/>KRA PIN {business.kra_pin}" if business.kra_pin else "")
    story += [Paragraph(f"Bill to: {bill}", s["Normal"]), Paragraph(f"Issued {invoice.created_at.astimezone(NAIROBI).date().isoformat()}, due {invoice.due_date.isoformat()}", s["Normal"]), Spacer(1, 10)]
    story.append(_table([["Description", "Amount"], [Paragraph(description, s["BodyText"]), kes(net_cents)]], [400, 125]))
    story.append(Spacer(1, 8))
    totals = [["Subtotal", kes(net_cents)]]
    if vat_pct > 0:
        totals.append([f"VAT {vat_pct:g}%", kes(vat_cents)])
    totals += [["Total", kes(invoice.total_cents)], ["Paid" if paid else "Balance due", kes(invoice.total_cents)]]
    story.append(_table(totals, [400, 125], header=False))
    if paid and invoice.paid_at:
        how = {"mpesa": "M-Pesa", "bank": "bank transfer", "card": "card", "manual": "recorded by hand"}.get(invoice.payment_method or "", invoice.payment_method or "")
        story += [Spacer(1, 8), Paragraph(f"Paid {invoice.paid_at.astimezone(NAIROBI).strftime('%d %b %Y')} by {how}" + (f", reference {invoice.mpesa_code}" if invoice.mpesa_code else ""), s["Normal"])]
    if etims is not None and etims.status == "submitted" and etims.receipt_no:
        facts = [f"KRA eTIMS receipt no. {etims.receipt_no}"] + ([f"Control unit {etims.sdc_id}"] if etims.sdc_id else []) + ([f"Internal data {etims.internal_data}"] if etims.internal_data else [])
        block = [Paragraph("<br/>".join(facts), s["BodyText"])]
        if seller_pin and etims.receipt_signature:
            block.insert(0, _qr(qr_data(seller_pin, branch_id, etims.receipt_signature)))
        story += [Spacer(1, 8), Table([block], colWidths=[100, 425] if len(block) == 2 else [525])]
    elif paid and etims is not None:
        story += [Spacer(1, 8), Paragraph("This invoice is being sent to KRA. Download it again shortly for the KRA receipt.", s["Normal"])]
    doc.build(story)
    return out.getvalue()
