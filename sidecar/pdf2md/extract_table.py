"""Table-rule extraction: rows of detected tables -> list[dict]."""
from __future__ import annotations

import re

from .errors import NO_RECORDS_FOUND, TABLE_NOT_FOUND, ConvertError
from .pdfio import apply_glyph_map, release

TEXT_SETTINGS = {"vertical_strategy": "text", "horizontal_strategy": "text"}
# columns from ruled vertical lines, rows from text baselines: for tables with no horizontal rules
LINES_TEXT_SETTINGS = {
    "vertical_strategy": "lines", "horizontal_strategy": "text",
    "snap_y_tolerance": 4, "intersection_y_tolerance": 6,
}
STRATEGIES = {"auto", "lines", "text", "lines_text"}
TITLE_LOOKUP_PT = 40  # how far above a table we look for its caption (e.g. "JANUARY 1994")


def clean_cell(v) -> str:
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v)).strip()


def normalize_header(row: list) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for i, c in enumerate(row):
        name = clean_cell(c) or f"col_{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        out.append(name)
    return out


def find_table_objs(page, strategy: str = "auto", glyph_map: dict | None = None,
                    x_tolerance: float | None = None) -> list[tuple[list[list], tuple]]:
    """[(rows, bbox)] — 'lines' = ruled; 'text' = whitespace-aligned; 'lines_text' = ruled columns +
    text rows; 'auto' = lines, then text."""
    apply_glyph_map(page, glyph_map)
    kw: dict = {}
    if x_tolerance:
        kw["x_tolerance"] = x_tolerance  # max gap (pt) that still joins characters into one word
    if strategy == "lines_text":
        settings = LINES_TEXT_SETTINGS
        kw["y_tolerance"] = 6  # symbol glyphs sit a few points off the baseline
    else:
        settings = None
    found = page.find_tables(settings) if settings else page.find_tables()
    if not found and strategy == "auto":
        found = page.find_tables(TEXT_SETTINGS)
    return [(t.extract(**kw), t.bbox) for t in found]


def find_tables(page, strategy: str = "auto", glyph_map: dict | None = None,
                x_tolerance: float | None = None) -> list[list[list]]:
    return [rows for rows, _ in find_table_objs(page, strategy, glyph_map, x_tolerance)]


def title_above(page, bbox, glyph_map: dict | None = None) -> str:
    """Closest text line above the table (its caption), '' if none."""
    top = bbox[1]
    if top <= 1:
        return ""
    try:
        region = page.crop((0, max(0.0, top - TITLE_LOOKUP_PT), float(page.width), top))
        if glyph_map:  # tall symbol glyphs of the header row poke above the table frame: not a caption
            fonts = [f.lower() for f in glyph_map]
            region = region.filter(lambda o: not (o.get("object_type") == "char"
                                                  and any(f in o.get("fontname", "").lower() for f in fonts)))
        lines = [ln.strip() for ln in (region.extract_text() or "").splitlines() if ln.strip()]
    except Exception:  # noqa: BLE001 - a missing caption must never fail the conversion
        return ""
    return re.sub(r"\s+", " ", lines[-1]) if lines else ""


def extract(pdf, pages: list[int], rule: dict) -> tuple[list[str], list[dict]]:
    if rule.get("record_mode", "row") == "table":
        return extract_per_table(pdf, pages, rule)

    header_row = rule.get("header_row", 0)
    table_index = rule.get("table_index")
    merge = rule.get("merge_multipage", True)
    strategy = rule.get("table_strategy", "auto")
    gm = rule.get("glyph_map")

    header: list[str] | None = None
    raw_header: list[str] | None = None
    records: list[dict] = []
    tables_seen = 0

    for pi in pages:
        page = pdf.pages[pi]
        tables = find_tables(page, strategy, gm, rule.get("text_x_tolerance"))
        release(page)
        chosen = tables if table_index is None else (
            [tables[table_index]] if table_index < len(tables) else []
        )
        for tbl in chosen:
            rows = [[clean_cell(c) for c in r] for r in tbl if any(clean_cell(c) for c in r)]
            if not rows:
                continue
            tables_seen += 1
            if header is None:
                if header_row >= len(rows):
                    raise ConvertError(
                        TABLE_NOT_FOUND,
                        f"header_row {header_row} out of range (first table has {len(rows)} rows)",
                        {"page": pi + 1},
                    )
                raw_header = rows[header_row]
                header = normalize_header(raw_header)
                body = rows[header_row + 1:]
            elif not merge:
                break
            else:
                # continuation table: drop a repeated header row
                body = rows[1:] if rows[0] == raw_header else rows
            for r in body:
                r = (r + [""] * len(header))[: len(header)]
                records.append(dict(zip(header, r)) | {"_page": pi + 1})
        if header is not None and not merge:
            break

    if tables_seen == 0 or header is None:
        raise ConvertError(
            TABLE_NOT_FOUND,
            "No table detected on the selected pages",
            {"pages": [p + 1 for p in pages], "table_index": table_index},
        )
    if not records:
        raise ConvertError(NO_RECORDS_FOUND, "Table found but it has no data rows", {"columns": header})
    return header, records


def extract_per_table(pdf, pages: list[int], rule: dict) -> tuple[list[str], list[dict]]:
    """Each detected table keeps its own header and becomes ONE record group (e.g. one per month).
    Rows carry _table / _title so the engine can group them."""
    header_row = rule.get("header_row", 0)
    table_index = rule.get("table_index")
    strategy = rule.get("table_strategy", "auto")
    gm = rule.get("glyph_map")

    columns: list[str] = []
    rows_out: list[dict] = []
    n_tables = 0
    for pi in pages:
        page = pdf.pages[pi]
        objs = find_table_objs(page, strategy, gm, rule.get("text_x_tolerance"))
        chosen = objs if table_index is None else ([objs[table_index]] if table_index < len(objs) else [])
        for tbl, bbox in chosen:
            rows = [[clean_cell(c) for c in r] for r in tbl if any(clean_cell(c) for c in r)]
            if not rows:
                continue
            if header_row >= len(rows):
                raise ConvertError(
                    TABLE_NOT_FOUND,
                    f"header_row {header_row} out of range (table has {len(rows)} rows)",
                    {"page": pi + 1},
                )
            header = normalize_header(rows[header_row])
            columns += [h for h in header if h not in columns]
            title = title_above(page, bbox, gm)
            for r in rows[header_row + 1:]:
                r = (r + [""] * len(header))[: len(header)]
                rows_out.append(dict(zip(header, r)) | {"_page": pi + 1, "_table": n_tables, "_title": title})
            n_tables += 1
        release(page)

    if n_tables == 0:
        raise ConvertError(
            TABLE_NOT_FOUND,
            "No table detected on the selected pages",
            {"pages": [p + 1 for p in pages], "table_index": table_index, "table_strategy": strategy},
        )
    if not rows_out:
        raise ConvertError(NO_RECORDS_FOUND, "Tables found but none has data rows", {"columns": columns})
    return columns, rows_out
