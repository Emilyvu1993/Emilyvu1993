"""PDF fixtures generated at test time (no binary files in git)."""
from __future__ import annotations

import os

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HEADER = ["Date", "Description", "Amount"]


def _rows(n: int, start: int = 1):
    return [[f"{(i % 28) + 1:02d}/01/2026", f"Payment #{i}", f"{i * 1000:,}.50"] for i in range(start, start + n)]


def _table(data):
    t = Table(data)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    return t


DEJAVU = "/usr/share/fonts/truetype/dejavu/"
LOREM = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore "
         "et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut "
         "aliquip ex ea commodo consequat. ")


def _doc(path, story, font="Helvetica", bold="Helvetica-Bold"):
    def page(c, d):
        c.setFont(font, 8)
        c.drawString(50, 810, "ACME Confidential Report")        # running header
        c.drawCentredString(298, 25, f"Page {d.page}")             # page number
    SimpleDocTemplate(str(path), pagesize=A4, topMargin=70, bottomMargin=60).build(story, onFirstPage=page, onLaterPages=page)


def _styles(font="Helvetica", bold="Helvetica-Bold", h1=18, h2=13, body=10, bold_same_size=False):
    return (
        ParagraphStyle("h1", fontName=bold, fontSize=body if bold_same_size else h1, leading=(h1 + 4), spaceBefore=10, spaceAfter=6),
        ParagraphStyle("h2", fontName=bold, fontSize=body if bold_same_size else h2, leading=h2 + 4, spaceBefore=8, spaceAfter=4),
        ParagraphStyle("p", fontName=font, fontSize=body, leading=body + 3, spaceAfter=8),
    )


@pytest.fixture(scope="session")
def fx(tmp_path_factory):
    d = tmp_path_factory.mktemp("fx")
    paths = {}

    p = d / "table_single.pdf"
    SimpleDocTemplate(str(p), pagesize=A4).build([_table([HEADER] + _rows(5))])
    paths["table_single"] = str(p)

    p = d / "table_multi.pdf"
    SimpleDocTemplate(str(p), pagesize=A4).build(
        [_table([HEADER] + _rows(4)), PageBreak(), _table([HEADER] + _rows(3, start=5))]
    )
    paths["table_multi"] = str(p)

    p = d / "table_borderless.pdf"
    SimpleDocTemplate(str(p), pagesize=A4).build([Table([HEADER] + _rows(4))])
    paths["table_borderless"] = str(p)

    p = d / "blocks.pdf"
    c = canvas.Canvas(str(p), pagesize=A4)
    y = 800
    for i in range(1, 5):
        for line in [f"Invoice No: INV-{i:03d}", f"Customer: ACME {i}", f"Total: {i * 250:,}.00 VND", "----"]:
            c.drawString(50, y, line)
            y -= 18
    c.showPage()
    c.drawString(50, 800, "Invoice No: INV-005")
    c.drawString(50, 782, "Customer: ACME 5")
    c.drawString(50, 764, "Total: 1,250.00 VND")
    c.save()
    paths["blocks"] = str(p)

    p = d / "scanned.pdf"
    c = canvas.Canvas(str(p), pagesize=A4)
    c.rect(50, 50, 300, 300, fill=1)
    c.save()
    paths["scanned"] = str(p)

    p = d / "encrypted.pdf"
    w = PdfWriter()
    for pg in PdfReader(paths["table_single"]).pages:
        w.add_page(pg)
    w.encrypt(user_password="secret", owner_password="owner")
    with open(p, "wb") as fh:
        w.write(fh)
    paths["encrypted"] = str(p)

    # ---- text documents ----
    h1, h2, pp = _styles()
    story = [Paragraph("Annual Report", h1), Paragraph("Intro text. " + LOREM, pp)]
    story += [Paragraph("1. Results", h1), Paragraph(LOREM * 6, pp), Paragraph("1.1 Revenue", h2), Paragraph(LOREM * 3, pp),
              Paragraph("&bull; first point", pp), Paragraph("&bull; second point", pp)]
    story += [PageBreak(), Paragraph("2. Outlook", h1), Paragraph(LOREM * 5, pp), Paragraph("2.1 Risks", h2), Paragraph(LOREM * 4, pp)]
    story += [PageBreak(), Paragraph("3. Appendix", h1), Paragraph(LOREM * 2, pp)]
    p = d / "text_report.pdf"
    _doc(p, story)
    paths["text_report"] = str(p)

    h1, h2, pp = _styles(bold_same_size=True)
    p = d / "text_boldheads.pdf"
    _doc(p, [Paragraph("Scope", h1), Paragraph(LOREM, pp), PageBreak(), Paragraph("Terms", h1), Paragraph(LOREM, pp)])
    paths["text_boldheads"] = str(p)

    p = d / "text_flat.pdf"
    _doc(p, [Paragraph(LOREM * 3, ParagraphStyle("f", fontName="Helvetica", fontSize=10, leading=13)) for _ in range(3)])
    paths["text_flat"] = str(p)

    if os.path.isfile(DEJAVU + "DejaVuSans.ttf"):
        pdfmetrics.registerFont(TTFont("DJ", DEJAVU + "DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont("DJ-B", DEJAVU + "DejaVuSans-Bold.ttf"))
        h1, h2, pp = _styles("DJ", "DJ-B", h1=12, h2=12, body=11)  # same size & bold: numbering mode only
        vn = "Tổ chức, cá nhân có quyền sử dụng đất theo quy định của pháp luật hiện hành. "
        p = d / "legal_vi.pdf"
        _doc(p, [
            Paragraph("Chương I", h1), Paragraph("QUY ĐỊNH CHUNG", h1),
            Paragraph("Điều 1. Phạm vi điều chỉnh", h2), Paragraph(vn * 3, pp),
            Paragraph("Điều 2. Đối tượng áp dụng", h2), Paragraph(vn * 2 + "1. Cá nhân; 2. Tổ chức.", pp),
            PageBreak(), Paragraph("Chương II", h1), Paragraph("QUYỀN VÀ NGHĨA VỤ", h1),
            Paragraph("Điều 3. Quyền của người sử dụng đất", h2), Paragraph(vn * 4, pp),
        ], "DJ", "DJ-B")
        paths["legal_vi"] = str(p)
        p = d / "legal_vi_1page.pdf"
        _doc(p, [Paragraph("Điều 1. Phạm vi điều chỉnh", h2), Paragraph(vn * 2, pp)], "DJ", "DJ-B")
        paths["legal_vi_1page"] = str(p)

    p = d / "corrupt.pdf"
    p.write_bytes(b"%PDF-1.7\nthis is not really a pdf\n%%EOF")
    paths["corrupt"] = str(p)
    return paths


@pytest.fixture
def table_cfg():
    return {
        "extraction": {"type": "table", "header_row": 0, "merge_multipage": True},
        "fields": [
            {"source": "Date", "target": "date", "transform": "date:%d/%m/%Y"},
            {"source": "Description", "target": "desc"},
            {"source": "Amount", "target": "amount", "transform": "number"},
        ],
        "template": {
            "header": "# Transactions ({{ count }})\n",
            "record": "- **{{ date }}** {{ desc | md }}: {{ amount }}",
        },
        "output": {"mode": "single_file"},
    }


@pytest.fixture
def block_cfg():
    return {
        "extraction": {
            "type": "block",
            "start_pattern": r"^Invoice No: (?P<invoice>INV-\d+)",
            "field_patterns": {"customer": r"Customer: (?P<value>.+)", "total": r"Total: ([\d,.]+)"},
        },
        "fields": [
            {"source": "invoice", "target": "invoice"},
            {"source": "customer", "target": "customer", "transform": "upper"},
            {"source": "total", "target": "total", "transform": "number"},
        ],
        "template": {"record": "## {{ invoice }}\n- Customer: {{ customer }}\n- Total: {{ total }}\n"},
    }


@pytest.fixture
def sec_cfg():
    return {
        "extraction": {"type": "sections", "heading_mode": "font"},
        "fields": [],
        "template": {"record": "{{ markdown }}\n"},
        "output": {"mode": "single_file"},
    }
