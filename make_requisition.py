"""
Build a Material Requisition PDF from the quotation JSON.

    python make_requisition.py 1942.json 1942

Fields the quotation gives us are filled in. Everything else - engineer,
supervisor, SR / LPO / WO / TO numbers, item codes, remarks - is left blank
because it does not exist yet when the quotation is written. Print it and
fill those in by hand, same as the paper form.

Setup:
    pip install reportlab
"""

import datetime
import json
import pathlib
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROWS = 22
LOGO = "logo.png"


def resource_path(name):
    """Find a bundled file whether running as a plain script or as a
    PyInstaller --onefile exe. --add-data files are unpacked into a
    temporary _MEIPASS folder at startup; use that when it exists."""
    base = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).resolve().parent))
    return base / name
DOC_REF = "SSD-QP-20-F05-R01"
REV_DATE = "07 Oct 2025"

TITLE = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=14,
                       textColor=colors.HexColor("#c55a11"), alignment=1)
CLASSIFY = ParagraphStyle("classify", fontName="Helvetica", fontSize=7,
                          textColor=colors.HexColor("#2e75b6"), alignment=2)
CELL = ParagraphStyle("cell", fontName="Helvetica", fontSize=8, leading=10)
LABEL = ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=8, leading=10)


def supply_lines(line_items):
    """Material is every BOQ row starting 'Supply of'. Relocation,
    installation and testing are labour, and never appear here."""
    return [
        item
        for item in line_items or []
        if str(item.get("description", "")).strip().lower().startswith("supply of")
    ]


def clean_qty(value):
    text = str(value).strip()
    return int(text) if text.isdigit() else text


def tidy(description):
    """'Supply of Smoke Detector (SIGA-OSD)' -> 'Smoke Detector (SIGA-OSD)'."""
    text = str(description).strip()
    return text[10:].strip() if text.lower().startswith("supply of") else text


def letterhead():
    logo = resource_path(LOGO)
    left = RLImage(str(logo), width=52 * mm, height=13 * mm) if logo.exists() else Paragraph("", CELL)
    table = Table([[left, Paragraph("Classification: Internal", CLASSIFY)]], colWidths=[90 * mm, 96 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, 0), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def footer(canvas, doc):
    canvas.saveState()
    width, _ = A4
    y = 28 * mm

    canvas.setStrokeColor(colors.HexColor("#e06c3b"))
    canvas.setLineWidth(1)
    canvas.line(12 * mm, y, width - 12 * mm, y)

    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.black)
    canvas.drawString(12 * mm, y - 6 * mm, f"Doc. Ref.: {DOC_REF}")
    canvas.drawString(12 * mm, y - 9.5 * mm, f"Rev. Date: {REV_DATE}")

    canvas.setFont("Helvetica-Bold", 6.5)
    canvas.drawString(105 * mm, y - 4 * mm, "MAINTENANCE:")
    canvas.drawString(152 * mm, y - 4 * mm, "PROJECTS:")

    canvas.setFont("Helvetica", 6.5)
    maint = ["+971 4 207 2800  /  +971 4 207 2860", "alarabia.maint@al-majid.com",
             "www.alarabiasafetysecurity.com", "P.O. Box 60204, Dubai - UAE"]
    proj = ["+971 4 285 1145  /  +971 4 284 4601", "firenet@al-majid.com",
            "www.alarabiasafetysecurity.com", "P.O. Box 60204, Dubai - UAE"]
    for n, line in enumerate(maint):
        canvas.drawString(105 * mm, y - (7.2 + n * 3.0) * mm, line)
    for n, line in enumerate(proj):
        canvas.drawString(152 * mm, y - (7.2 + n * 3.0) * mm, line)

    canvas.setFont("Helvetica-Bold", 6.5)
    canvas.setFillColor(colors.HexColor("#1f6f6f"))
    canvas.drawString(55 * mm, y - 7 * mm, "A Proud Affiliate of")
    canvas.setFillColor(colors.black)
    canvas.drawString(55 * mm, y - 10.2 * mm, "Member of Juma Al Majid")
    canvas.drawString(55 * mm, y - 13.4 * mm, "Holding Group LLC")

    canvas.setFillColor(colors.HexColor("#2e8b8b"))
    canvas.rect(55 * mm, 4 * mm, width - 67 * mm, 3.5 * mm, stroke=0, fill=1)
    canvas.restoreState()


def header_table(data, job_no, date):
    rows = [
        ["Job Number", job_no, "Date", date],
        ["Customer Name", data.get("customer_name", ""), "Service Request (SR) Number", ""],
        ["Project details", data.get("project_name", ""), "Local Purchase Order (LPO) Number", ""],
        ["Engineer Name", "", "Work Order (WO) Number", ""],
        ["Supervisor Name", "", "Transfer Order (TO) Number", ""],
    ]
    body = [
        [Paragraph(r[0], LABEL), Paragraph(str(r[1]), CELL),
         Paragraph(r[2], LABEL), Paragraph(str(r[3]), CELL)]
        for r in rows
    ]
    table = Table(body, colWidths=[35 * mm, 55 * mm, 45 * mm, 45 * mm], rowHeights=8 * mm)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#808080")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f2f2f2")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f2f2f2")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def items_table(items):
    head = [Paragraph(h, LABEL) for h in ("S. N", "Description", "Item Code", "Qty", "Remarks")]
    body = [head]
    for n in range(1, ROWS + 1):
        if n <= len(items):
            item = items[n - 1]
            body.append([
                Paragraph(str(n), CELL),
                Paragraph(tidy(item.get("description")), CELL),
                Paragraph("", CELL),
                Paragraph(str(clean_qty(item.get("qty"))), CELL),
                Paragraph("", CELL),
            ])
        else:
            body.append([Paragraph(str(n), CELL), "", "", "", ""])

    table = Table(
        body,
        colWidths=[12 * mm, 75 * mm, 30 * mm, 20 * mm, 43 * mm],
        rowHeights=[7 * mm] + [6.6 * mm] * ROWS,
        repeatRows=1,
    )
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#808080")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f2f2")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (3, 0), (3, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def signature_table():
    body = [[Paragraph(t, LABEL) for t in ("Requested By", "Checked By", "Approved By")]]
    table = Table(body, colWidths=[60 * mm, 60 * mm, 60 * mm], rowHeights=15 * mm)
    table.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, colors.HexColor("#808080")),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    return table


def build(data, job_no, out_path, date=None):
    date = date if date is not None else datetime.date.today().strftime("%d/%m/%y")
    items = supply_lines(data.get("line_items"))

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=10 * mm, bottomMargin=34 * mm,
        title=f"Material Requisition {job_no}",
    )

    story = [
        letterhead(),
        Spacer(1, 4 * mm),
        Paragraph("<u>Material Requisition</u>", TITLE),
        Spacer(1, 4 * mm),
        header_table(data, job_no, date),
        Spacer(1, 4 * mm),
        items_table(items),
        Spacer(1, 4 * mm),
        signature_table(),
    ]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return len(items)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("usage: python make_requisition.py <json file> <job number>")

    src = pathlib.Path(sys.argv[1])
    job_no = sys.argv[2]

    data = json.loads(src.read_text(encoding="utf-8"))
    out = src.with_name(f"requisition_{job_no}.pdf")

    count = build(data, job_no, out)
    print(f"{count} material lines written")
    print(f"SAVED -> {out.resolve()}")
