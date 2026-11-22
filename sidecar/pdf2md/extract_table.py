"""Table-rule extraction: rows of detected tables -> list[dict]."""
from __future__ import annotations

import re

from .errors import NO_RECORDS_FOUND, TABLE_NOT_FOUND, ConvertError
from .pdfio import release


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


TEXT_SETTINGS = {"vertical_strategy": "text", "horizontal_strategy": "text"}
STRATEGIES = {"auto", "lines", "text"}


def find_tables(page, strategy: str = "auto") -> list[list[list]]:
    """'lines' = ruled tables; 'text' = whitespace-aligned (borderless); 'auto' = lines, then text."""
    if strategy in ("auto", "lines"):
        t = page.extract_tables()
        if t or strategy == "lines":
            return t
    return page.extract_tables(TEXT_SETTINGS)


def extract(pdf, pages: list[int], rule: dict) -> tuple[list[str], list[dict]]:
    header_row = rule.get("header_row", 0)
    table_index = rule.get("table_index")
    merge = rule.get("merge_multipage", True)

    header: list[str] | None = None
    raw_header: list[str] | None = None
    records: list[dict] = []
    tables_seen = 0

    for pi in pages:
        page = pdf.pages[pi]
        tables = find_tables(page, rule.get("table_strategy", "auto"))
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
