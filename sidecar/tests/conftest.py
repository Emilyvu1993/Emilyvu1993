"""PDF fixtures generated at test time (no binary files in git)."""
from __future__ import annotations

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.platypus import PageBreak, SimpleDocTemplate, Table, TableStyle

HEADER = ["Date", "Description", "Amount"]


def _rows(n: int, start: int = 1):
    return [[f"{(i % 28) + 1:02d}/01/2026", f"Payment #{i}", f"{i * 1000:,}.50"] for i in range(start, start + n)]


def _table(data):
    t = Table(data)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    return t


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
