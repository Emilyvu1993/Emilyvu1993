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


def _spec_pdf(path):
    """Mimics a Markdown-rendered API spec: page frame, rounded code cards, ruled tables whose field names are monospace
    on grey backgrounds (rect pills for wrapped names -> phantom edge between the two lines; curve pill for the others),
    a table and a JSON block that continue on the next page."""
    H = 842
    c = canvas.Canvas(str(path), pagesize=A4)
    Y = lambda top: H - top

    def txt(x, top, s, font="Helvetica", size=10.5):
        c.setFillColorRGB(0, 0, 0)
        c.setFont(font, size)
        c.drawString(x, Y(top + size), s)

    def frame():
        c.setLineWidth(0.5)
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.rect(28, Y(814), 539, 786, stroke=1, fill=0)

    def code_card(top, bottom, lines, step=15):
        c.setStrokeColorRGB(0.6, 0.6, 0.6)
        c.roundRect(28, Y(bottom), 539, bottom - top, 6, stroke=1, fill=0)
        for i, ln in enumerate(lines):
            txt(40, top + 10 + i * step, ln, "Courier", 10.5)

    def table(top, rows):
        """rows = [(cells, height)], cells[0] may contain '|' = a wrapped monospace name; first row is the header."""
        col = [28, 140, 258, 567]       # narrow first column: a 14-char monospace token fills it, so the renderer wraps it
        total = sum(h for _, h in rows)
        c.setLineWidth(0.5)
        c.setStrokeColorRGB(0.6, 0.6, 0.6)
        c.rect(28, Y(top + total), 539, total, stroke=1, fill=0)
        y = top
        for ri, (cells, h) in enumerate(rows):
            if ri:
                c.line(28, Y(y), 567, Y(y))
            for ci, cell in enumerate(cells):
                if ri == 0:
                    txt(col[ci] + 8, y + 5, cell, "Helvetica-Bold")
                elif ci == 0:
                    parts = cell.split("|")
                    for k, part in enumerate(parts):
                        c.setFillColorRGB(0.93, 0.93, 0.93)
                        if len(parts) > 1:                                   # wrapped name: a box pill per line
                            c.rect(30, Y(y + 3 + 15 * (k + 1)), 106, 15, stroke=0, fill=1)
                        else:                                                # single line: a rounded (curve) pill
                            c.roundRect(34, Y(y + 18), 80, 15, 4, stroke=0, fill=1)
                        txt(40, y + 5 + 15 * k, part, "Courier")
                else:
                    txt(col[ci] + 8, y + 5, cell)
            y += h
        for x in col[1:-1]:
            c.line(x, Y(top), x, Y(top + total))

    body = "Intro paragraph about the request. It is long enough to be the most common text size of the document. "
    # page 1
    frame()
    txt(40, 45, "Spec Doc", "Helvetica-Bold", 22.5)
    txt(40, 95, "1 Endpoints", "Helvetica-Bold", 16.5)
    code_card(130, 190, ["POST http://host/predict", "Content-Type: application/json"])
    txt(40, 210, body)
    txt(40, 226, body)
    txt(40, 260, "2 Request", "Helvetica-Bold", 16.5)
    txt(40, 295, "Fields", "Helvetica-Bold", 13.5)
    rows1 = [(["Field", "Type", "Purpose"], 22), (["cifcode", "String", "Customer id (CIF)"], 22),
             (["priceaffteratt|r", "Number", "Appraised value, VND"], 38),
             (["registrationda|te", "Number", "Registration date, epoch ms"], 38)]
    table(790 - sum(h for _, h in rows1), rows1)
    c.showPage()
    # page 2: the table continues (header repeated), then the first half of a JSON block that runs to the page bottom
    frame()
    rows2 = [(["Field", "Type", "Purpose"], 22), (["accomodationpr|ovinceCode", "String", "Province code, 2 chars"], 38),
             (["extraData", "JSON Object", "Free tracking data"], 22)]
    table(28, rows2)
    txt(40, 150, "JSON example", "Helvetica-Bold", 13.5)
    code_card(185, 790, ["{", '  "cifcode": "2510808575",', '  "assettype": "17",', '  "extraData": {'])
    c.showPage()
    # page 3: the JSON continues at the top, then another section
    frame()
    code_card(28, 100, ['    "loan_id": 1', "  }", "}"])
    txt(40, 150, "3 Output", "Helvetica-Bold", 16.5)
    txt(40, 190, body)
    txt(40, 206, body)
    c.showPage()
    c.save()
    return path


def _mono_pdf(path):
    """No cards at all: a paragraph and consecutive monospace lines (code without a box)."""
    H = 842
    c = canvas.Canvas(str(path), pagesize=A4)
    Y = lambda top: H - top
    c.setFont("Helvetica-Bold", 16.5)
    c.drawString(40, Y(60), "Usage")
    c.setFont("Helvetica", 10.5)
    for i in range(3):
        c.drawString(40, Y(100 + 15 * i), "Run the converter from a terminal with the options below, then read the output file. " * 1)
    c.setFont("Courier", 10.5)
    for i, ln in enumerate(["pdf2md input.pdf", "  --pages 1-3", "  --out result.md"]):
        c.drawString(40, Y(180 + 15 * i), ln)
    c.setFont("Helvetica", 10.5)
    c.drawString(40, Y(260), "That is all.")
    c.showPage()
    c.save()
    return path


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

    # ---- ephemeris-like: vertical rules only, caption above, symbol font glyphs inline ----
    from reportlab.pdfbase.pdfmetrics import stringWidth

    def month_table(c, top, caption, n_rows):
        xs = [50, 100, 170, 245, 300, 340]
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, top + 8, caption)
        bottom = top - 20 - n_rows * 12 - 12
        for x in xs:
            c.line(x, top + 2, x, bottom)
        for y in (top + 2, top - 14, bottom):
            c.line(xs[0], y, xs[-1], y)
        c.setFont("Helvetica", 8)
        c.drawString(54, top - 10, "Day")
        c.drawString(104, top - 10, "Sid.t")
        c.setFont("Courier", 10)                       # symbol-font header glyphs: A = Sun, B = Moon
        c.drawString(205, top - 11, "A")
        c.drawString(270, top - 11, "B")
        c.setFont("Helvetica", 8)
        c.drawString(304, top - 10, "Day")
        y = top - 28
        for i in range(n_rows):
            if i and i % 4 == 0:
                y -= 6                                  # blank gap between day blocks, no horizontal rule
            c.setFont("Helvetica", 8)
            c.drawString(54, y, f"S {i + 1}")
            x = 104                                     # "6 41 40": groups separated by a narrow gap, no space char
            for part in ("6", f"{41 + i}", "40"):
                c.drawString(x, y, part)
                x += stringWidth(part, "Helvetica", 8) + 2.2
            x = 174
            if i % 3 == 0:                              # sign changes: degree + glyph + minutes, glyph is taller
                c.drawString(x, y, "10")
                x += stringWidth("10", "Helvetica", 8)
                c.setFont("Courier", 10)
                c.drawString(x, y - 1.5, "j")
                x += stringWidth("j", "Courier", 10)
                c.setFont("Helvetica", 8)
                c.drawString(x, y, "20'16")
            else:
                c.drawString(x, y, f"1{i}\u00b021'24")
            c.drawString(249, y, f"2{i}\u00b0 5")
            c.drawString(304, y, f"S {i + 1}")
            y -= 12
        return bottom

    p = d / "ephemeris_like.pdf"
    c = canvas.Canvas(str(p), pagesize=A4)
    b = month_table(c, 780, "JANUARY 1994", 7)
    month_table(c, b - 40, "FEBRUARY 1994", 5)
    c.showPage()
    c.save()
    paths["ephemeris_like"] = str(p)

    # many short bold lines: not prose, must trigger the "looks like a table" warning
    h1, _, pp = _styles(h1=12, body=8)
    p = d / "many_heads.pdf"
    _doc(p, [x for i in range(30) for x in (Paragraph(f"Heading {i}", h1), Paragraph("plain body text " * 4, pp))])
    paths["many_heads"] = str(p)

    # ---- tarot-like: bordered 2-column table (empty image column), group headings, bold labels ----
    from reportlab.platypus import Table as RLTable

    b = ParagraphStyle("tb", fontName="Helvetica", fontSize=10, leading=12)
    grp = ParagraphStyle("tg", fontName="Helvetica", fontSize=24, leading=28, spaceBefore=10, spaceAfter=6)
    txt = "A fairly long sentence about the meaning of this card, wrapping over more than a single line of the cell. "

    def major(title, tag):
        return [Paragraph(f"<b>{title} says:</b> <b><i>{tag}</i></b>", b), Paragraph(txt * 2, b),
                Paragraph(f"<b>Home:</b> {txt}", b), Paragraph(f"<b>Love and Relationships:</b> {txt}", b),
                Paragraph(f"<b><i>Is he upside down?</i></b> {txt}", b)]

    def minor(title):
        return [Paragraph(f"<b>{title}</b>", b), Paragraph(txt * 2, b), Spacer(1, 10),
                Paragraph("<b><i>Is it upside down?</i></b>", b), Paragraph(txt, b)]

    def card_table(cards):
        t = RLTable([[Spacer(1, 30), c] for c in cards], colWidths=[60, 400])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
        return t

    p = d / "tarot_like.pdf"
    _doc(p, [Paragraph("The Major Arcana", grp),
             card_table([major("0 The Fool", "Look before you leap!"), major("I The Magician", "Go, go go!"),
                         major("The Chariot", "You can move on")]),
             PageBreak(), Paragraph("Suit of Wands", grp),
             card_table([minor("Ace of Wands"), minor("Two of Wands"), minor("Three of Wands")])])
    paths["tarot_like"] = str(p)

    # ---- spec-like: bordered cards for code and tables, inline-code "pills", split table + split JSON ----
    paths["spec_like"] = str(_spec_pdf(d / "spec_like.pdf"))
    paths["mono_lines"] = str(_mono_pdf(d / "mono_lines.pdf"))
    h1, _, pp = _styles()
    p = d / "table_heading.pdf"
    _doc(p, [Paragraph("Report", h1), Paragraph(LOREM * 2, pp), _table([HEADER] + _rows(3))])
    paths["table_heading"] = str(p)

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


GLYPHS = {"Courier": {"A": "\u2609", "B": "\u263d", "j": "\u2651"}}


@pytest.fixture
def eph_cfg():
    return {
        "extraction": {"type": "table", "table_strategy": "lines_text", "record_mode": "table", "header_row": 0,
                       "glyph_map": GLYPHS},
        "fields": [],
        "template": {"record": "{{ markdown }}\n"},
        "output": {"mode": "single_file"},
    }
