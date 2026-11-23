"""Tables and code blocks for `sections` extraction (option `keep_blocks`).

Targets PDFs rendered from Markdown/HTML, where tables and code are drawn as bordered "cards":
  * leaf cards = unique rectangles >= 85 % of the page width that contain no other card
    (the page frame and wrapper boxes are dropped, clipped fragments from a table split over a page break too);
  * a card holding a grid with >= 2 columns is a table, a card of >= 80 % monospace text is a code block;
  * pages without any card fall back to ruled tables found on the whole page, and to runs of monospace lines for code;
  * tables / code that continue on the next page (same header repeated / code split) are merged.

Cell text is rebuilt from characters with their fonts: monospace runs become `code`, and a monospace token that the renderer
wrapped in the middle of a word is joined back without a space ("priceaffteratt" + "r" -> "priceaffterattr").
"""
from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field

from .extract_sections import MONO_RE, Line, _styled_runs
from .pdfio import apply_glyph_map, release

CARD_MIN_WIDTH = 0.85       # of the page width
CARD_MIN_HEIGHT = 30.0      # smaller = a clipped fragment, ignored
EDGE_ZONE = 0.10            # a block starting in the top / ending in the bottom 10 % of a page may continue across the break
WRAP_SLACK = 24.0           # pt: a line this close to the cell's right edge was wrapped by the renderer
CODE_MONO_FRAC = 0.8


@dataclass
class Block:
    kind: str                       # "table" | "code"
    page: int
    page_height: float
    bbox: tuple[float, float, float, float]
    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    code: list[str] = field(default_factory=list)
    skip: bool = False              # continuation merged into an earlier block

    @property
    def top(self) -> float:
        return self.bbox[1]

    @property
    def bottom(self) -> float:
        return self.bbox[3]


# ---------------------------------------------------------------- geometry
def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _iou(a, b) -> float:
    inter = _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))
    union = _area(a) + _area(b) - inter
    return inter / union if union else 0.0


def _contains(a, b, tol: float = 6.0) -> bool:
    return (b[0] >= a[0] - tol and b[1] >= a[1] - tol and b[2] <= a[2] + tol and b[3] <= a[3] + tol
            and _area(a) > 1.05 * _area(b))


def find_cards(page) -> list[tuple[float, float, float, float]]:
    """Leaf cards of a page, top to bottom."""
    w, h = float(page.width), float(page.height)
    raw = []
    for o in list(page.rects) + list(page.curves):
        b = (max(0.0, o["x0"]), max(0.0, o["top"]), min(w, o["x1"]), min(h, o["bottom"]))
        if b[2] - b[0] >= CARD_MIN_WIDTH * w and b[3] - b[1] >= CARD_MIN_HEIGHT:
            raw.append(b)
    uniq: list[tuple] = []
    for b in sorted(raw, key=lambda b: (b[1], -(b[3] - b[1]))):
        if not any(_iou(b, u) > 0.8 for u in uniq):
            uniq.append(b)
    return [c for c in uniq if not any(o is not c and _contains(c, o) for o in uniq)]


# ---------------------------------------------------------------- text of a region
def _runs_of(sub, cell_x1: float | None) -> list[list]:
    """Styled runs of a region, lines joined with a space - or with nothing for a monospace token wrapped mid-word."""
    merged: list[list] = []
    prev = None
    for ln in sub.extract_text_lines(strip=True, return_chars=True):
        text = re.sub(r"\s+", " ", ln["text"]).strip()
        if not text:
            continue
        runs = [list(r) for r in (_styled_runs(ln["chars"], text, True) or [(text, False, False, False)])]
        if merged:
            tight = (cell_x1 is not None and prev is not None and merged[-1][3] and runs[0][3]
                     and cell_x1 - prev["x1"] <= WRAP_SLACK)
            if not tight:
                merged.append([" ", False, False, False])
        merged.extend(runs)
        prev = ln
    out: list[list] = []
    for r in merged:                                     # collapse neighbours with the same style
        if out and out[-1][1:] == r[1:]:
            out[-1][0] += r[0]
        else:
            out.append(r)
    return out


def _cell_md(sub, cell_x1: float) -> str:
    runs = _runs_of(sub, cell_x1)
    md = Line("", 0, 0, 0, 0, False, 0, runs=[tuple(r) for r in runs]).md(emphasis=False, code=True)
    return md.replace("|", "\\|")


def _grid(region, table) -> list[list[str]]:
    """Rows of cell Markdown for a pdfplumber table found inside `region` (a page or a crop)."""
    x0, t0, x1, b0 = region.bbox
    rows: list[list[str]] = []
    for row in table.rows:
        cells = []
        for c in row.cells:
            if c is None:
                cells.append("")
                continue
            box = (max(x0, c[0]), max(t0, c[1]), min(x1, c[2]), min(b0, c[3]))
            cells.append(_cell_md(region.within_bbox(box), box[2]) if box[2] > box[0] and box[3] > box[1] else "")
        rows.append(cells)
    return rows


def _clean_table(rows: list[list[str]]) -> tuple[list[str], list[list[str]]] | None:
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        return None
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    keep = [j for j in range(n) if any(r[j].strip() for r in rows)]       # drop columns that are empty everywhere
    rows = [[r[j] for j in keep] for r in rows]
    if len(keep) < 2:
        return None
    return rows[0], rows[1:]


def _table_block(region, table, page_no: int, page_h: float) -> Block | None:
    cleaned = _clean_table(_grid(region, table))
    if not cleaned:
        return None
    b = table.bbox
    return Block("table", page_no, page_h, (b[0], b[1], b[2], b[3]), header=cleaned[0], rows=cleaned[1])


def _code_block(region, bbox, page_no: int, page_h: float) -> Block | None:
    lines = region.extract_text_lines(strip=True, return_chars=True)
    lines = [l for l in lines if l["text"].strip()]
    if not lines:
        return None
    widths = [c["x1"] - c["x0"] for l in lines for c in l["chars"] if c["text"].strip()]
    cw = statistics.median(widths) if widths else 6.0
    x_min = min(l["x0"] for l in lines)
    pitch = statistics.median([b["top"] - a["top"] for a, b in zip(lines, lines[1:])]) if len(lines) > 1 else 0
    out: list[str] = []
    prev = None
    for l in lines:
        if prev is not None and pitch and l["top"] - prev["top"] > 1.6 * pitch:
            out.append("")                                  # a blank line in the source
        out.append(" " * max(0, round((l["x0"] - x_min) / cw)) + re.sub(r"\s+", " ", l["text"]).strip())
        prev = l
    return Block("code", page_no, page_h, tuple(bbox), code=out)


THIN = 2.5   # pt: borders are hairlines; anything thicker in both directions is a background box


def _borders_only(o) -> bool:
    kind = o.get("object_type")
    if kind == "curve":
        return False
    if kind == "rect":      # a hairline, or an outline (stroked, not filled), is a border; a filled box is a background
        return min(o["x1"] - o["x0"], o["bottom"] - o["top"]) <= THIN or not o.get("fill")
    return True


def _tables_in(region, page_no: int, h: float) -> list[Block]:
    """Tables of a region. Renderers draw a background (a rounded "pill") behind every wrapped line of inline code,
    and the edge of such a pill looks like a row border that splits the row. So, first, only hairline borders are kept
    (backgrounds and curves are ignored); then curves are allowed back (a table framed by curves); then everything."""
    attempts = (region.filter(_borders_only),
                region.filter(lambda o: o.get("object_type") != "curve"),
                region)
    for reg in attempts:
        made = [bl for t in reg.find_tables() if (bl := _table_block(reg, t, page_no, h))]
        if made:
            return made
    return []


def page_blocks(page, page_no: int) -> list[Block]:
    h = float(page.height)
    blocks: list[Block] = []
    cards = find_cards(page)
    if cards:
        for card in cards:
            crop = page.crop(card)
            made = _tables_in(crop, page_no, h)
            if made:
                blocks += made
                continue
            chars = [c for c in crop.chars if c["text"].strip()]
            if chars and sum(1 for c in chars if MONO_RE.search(c["fontname"])) / len(chars) >= CODE_MONO_FRAC:
                bl = _code_block(crop, card, page_no, h)
                if bl:
                    blocks.append(bl)
    else:                                                    # no cards: ruled tables on the whole page
        blocks += _tables_in(page, page_no, h)
    return sorted(blocks, key=lambda b: b.top)


# ---------------------------------------------------------------- across pages, rendering
def _same_header(a: list[str], b: list[str]) -> bool:
    norm = lambda h: [re.sub(r"[`\s]+", "", c).lower() for c in h]
    return norm(a) == norm(b)


def merge_across_pages(per_page: dict[int, list[Block]]) -> list[Block]:
    """Merge a table / code block that is split by a page break into the block it continues."""
    tail: dict[tuple[int, str], Block] = {}          # (page, kind) -> the block that owns the last part on that page
    out: list[Block] = []
    for page_no in sorted(per_page):
        blocks = per_page[page_no]
        for i, b in enumerate(blocks):
            out.append(b)
            prev = tail.get((page_no - 1, b.kind))
            starts_at_top = b.top <= EDGE_ZONE * b.page_height
            if prev is not None and starts_at_top and i == 0:
                if b.kind == "table" and _same_header(prev.header, b.header):
                    prev.rows += b.rows
                    b.skip = True
                elif b.kind == "code":
                    prev.code += b.code
                    b.skip = True
            owner = prev if b.skip else b
            if b.bottom >= (1 - EDGE_ZONE) * b.page_height:
                tail[(page_no, b.kind)] = owner
    return out


def _fence(code: list[str]) -> str:
    text = "\n".join(code)
    lang = ""
    try:
        json.loads(text)
        lang = "json"
    except ValueError:
        pass
    fence = "```"
    while fence in text:
        fence += "`"
    return f"{fence}{lang}\n{text}\n{fence}"


def render(b: Block) -> str:
    if b.kind == "code":
        return _fence(b.code)
    n = len(b.header)
    head = "| " + " | ".join(c if c else " " for c in b.header) + " |"
    sep = "|" + "|".join(" --- " for _ in range(n)) + "|"
    body = ["| " + " | ".join((r + [""] * n)[:n]) + " |" for r in b.rows]
    return "\n".join([head, sep, *body])


# ---------------------------------------------------------------- entry point
def _inside(l: Line, b: Block) -> bool:
    cy, cx = (l.top + l.bottom) / 2, (l.x0 + l.x1) / 2
    return b.bbox[1] - 2 <= cy <= b.bbox[3] + 2 and b.bbox[0] - 2 <= cx <= b.bbox[2] + 2


def _mono_runs_as_blocks(lines: list[Line]) -> list[Line]:
    """No cards: consecutive monospace lines (>= 80 % mono glyphs) become one fenced code block."""
    out: list[Line] = []
    group: list[Line] = []

    def flush() -> None:
        if not group:
            return
        cw = max(group[0].size, 1.0) * 0.6
        x_min = min(g.x0 for g in group)
        code = [" " * max(0, round((g.x0 - x_min) / cw)) + g.text for g in group]
        out.append(Line("", group[0].page, group[0].top, group[-1].bottom, group[0].size, False, group[0].page_height,
                        block=_fence(code)))
        group.clear()

    for l in lines:
        if l.block is None and l.mono_frac >= CODE_MONO_FRAC and (not group or (
                l.page == group[-1].page and l.top - group[-1].bottom < 1.5 * max(l.size, 1.0))):
            group.append(l)
            continue
        flush()
        if l.block is None and l.mono_frac >= CODE_MONO_FRAC:
            group.append(l)
        else:
            out.append(l)
    flush()
    return out


def apply(pdf, pages: list[int], lines: list[Line], rule: dict) -> list[Line]:
    """Replace the lines of tables / code blocks with one Markdown block line each, in reading order."""
    gm = rule.get("glyph_map")
    per_page: dict[int, list[Block]] = {}
    for pi in pages:
        page = pdf.pages[pi]
        apply_glyph_map(page, gm)
        per_page[pi + 1] = page_blocks(page, pi + 1)
        release(page)
    blocks = merge_across_pages(per_page)

    kept = [l for l in lines if not any(b.page == l.page and _inside(l, b) for b in blocks)]
    kept = _mono_runs_as_blocks(kept)                       # code that is not inside a card
    synthetic = [Line("", b.page, b.top, b.bottom, 0.0, False, b.page_height, block=render(b)) for b in blocks if not b.skip]
    return sorted(kept + synthetic, key=lambda l: (l.page, l.top))
