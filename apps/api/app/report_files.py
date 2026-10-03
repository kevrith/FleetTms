"""Report summary as an Excel workbook or a PDF (masterplan 5.15). Takes the dict that build_summary returns."""

import io

from openpyxl import Workbook
from openpyxl.styles import Font
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def kes(cents: int) -> float:
    return cents / 100


def label(category: str) -> str:
    return category.replace("_", " ").capitalize()


def _tables(data: dict) -> list[tuple[str, list[str], list[list]]]:
    t = data["totals"]
    return [
        ("Totals", ["Measure", "Value"], [
            ["Trips completed", t["trips_completed"]], ["Distance (km)", t["distance_km"]],
            ["Fuel (litres)", t["fuel_litres"]], ["Fuel (KES)", kes(t["fuel_cents"])],
            ["Expenses (KES)", kes(t["expenses_cents"])], ["Floats sent (KES)", kes(t["floats_sent_cents"])],
        ]),
        ("Expenses by type", ["Type", "KES"], [[label(c["category"]), kes(c["cents"])] for c in data["expenses_by_category"]]),
        ("By vehicle", ["Vehicle", "Trips", "Distance (km)", "Fuel (litres)", "Fuel (KES)", "Km per litre", "Expenses (KES)"], [
            [v["registration"], v["trips"], v["distance_km"], v["fuel_litres"], kes(v["fuel_cents"]), v["km_per_litre"], kes(v["expenses_cents"])]
            for v in data["by_vehicle"]
        ]),
        ("By day", ["Day", "Trips", "Distance (km)", "Fuel (KES)", "Expenses (KES)"], [
            [d["day"].isoformat(), d["trips"], d["distance_km"], kes(d["fuel_cents"]), kes(d["expenses_cents"])] for d in data["by_day"]
        ]),
    ]  # fmt: skip


def report_xlsx(data: dict) -> bytes:
    return sections_xlsx(_tables(data))


def sections_xlsx(sections: list[tuple[str, list[str], list[list]]]) -> bytes:
    """Any report as a workbook: one sheet per section."""
    book = Workbook()
    book.remove(book.active)
    for title, header, rows in sections:
        title = title[:31].replace("/", "-").replace("\\", "-").replace("?", "").replace("*", "").replace("[", "(").replace("]", ")").replace(":", "-")
        sheet = book.create_sheet(title)
        sheet.append(header)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in rows:
            sheet.append(row)
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = max(len(str(c.value or "")) for c in column) + 4
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def report_pdf(data: dict) -> bytes:
    return sections_pdf(f"FleetTms report: {data['from'].isoformat()} to {data['to'].isoformat()}", _tables(data))


def sections_pdf(title: str, sections: list[tuple[str, list[str], list[list]]], notes: list[str] | None = None) -> bytes:
    """Any report as a PDF: a title, then each section as a table."""
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=landscape(A4), title="FleetTms report", leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    story: list = [Paragraph(title, styles["Title"])]
    for note in notes or []:
        story.append(Paragraph(note, styles["Normal"]))
    for section, header, rows in sections:
        story += [Spacer(1, 12), Paragraph(section, styles["Heading2"])]
        if not rows:
            story.append(Paragraph("Nothing in this range.", styles["Normal"]))
            continue
        shown = [[("" if v is None else f"{v:,.2f}" if isinstance(v, float) else f"{v:,}" if isinstance(v, int) else v) for v in row] for row in rows]
        table = Table([header, *shown], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("ALIGN", (1, 1), (-1, -1), "RIGHT"), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))  # fmt: skip
        story.append(table)
    doc.build(story)
    return out.getvalue()
