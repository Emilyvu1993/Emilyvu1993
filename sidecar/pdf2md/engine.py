"""Public engine API used by the RPC layer: inspect / convert / match_pattern / validate."""
from __future__ import annotations

import os
import re
from decimal import Decimal
from typing import Any

from . import extract_block, extract_sections, extract_table
from .config import compile_regex, validate, validate_extraction
from .errors import OUTPUT_WRITE_FAILED, ConvertError
from .mapping import map_records, unique_keys
from .pdfio import ensure_text_layer, open_pdf, page_has_text, parse_pages, release
from .render import compile_templates, render_frame, render_record


_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_filename(name: str, fallback: str) -> str:
    """Filesystem-safe name that keeps Unicode letters (Vietnamese) and a readable shape."""
    s = re.sub(r"[^\w\-. ]+", "_", name, flags=re.UNICODE)
    s = re.sub(r"\s+", "_", s).strip("._ ")[:80].rstrip("._ ")
    if not s:
        return fallback
    return f"_{s}" if s.upper() in _RESERVED else s


def _md_cell(v: Any) -> str:
    return ("" if v is None else str(v)).replace("|", "\\|").replace("\n", " ")


def md_table(labels: list[str], rows: list[dict], keys: list[str]) -> str:
    head = "| " + " | ".join(_md_cell(l) for l in labels) + " |"
    sep = "|" + "|".join(" --- " for _ in keys) + "|"
    body = ["| " + " | ".join(_md_cell(r.get(k)) for k in keys) + " |" for r in rows]
    return "\n".join([head, sep, *body])


def group_by_table(records: list[dict], columns: list[str], fields: list[dict]) -> list[dict]:
    """One record per detected table: title (caption above), page, row_count, rows, table (GFM), markdown."""
    label_of = {f["target"]: f["target"] for f in fields} if fields else dict(zip(unique_keys(columns), columns))
    groups: dict[int, list[dict]] = {}
    for r in records:
        groups.setdefault(r["_table"], []).append(r)
    out = []
    for rs in groups.values():
        keys = [k for k in rs[0] if not k.startswith("_")]
        rows = [{k: r.get(k) for k in keys} for r in rs]
        title = rs[0].get("_title") or ""
        table = md_table([label_of.get(k, k) for k in keys], rows, keys)
        out.append({
            "title": title, "page": rs[0].get("_page"), "row_count": len(rows), "table": table,
            "markdown": f"## {title}\n\n{table}" if title else table, "rows": rows, "_page": rs[0].get("_page"),
        })
    return out


def _json_safe(v: Any) -> Any:
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, dict):
        return {k: _json_safe(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_json_safe(x) for x in v]
    return v


def inspect(pdf_path: str, max_pages: int = 5, sample_rows: int = 3, table_strategy: str = "auto") -> dict:
    """Cheap structural scan to drive the config editor."""
    with open_pdf(pdf_path) as pdf:
        n = len(pdf.pages)
        has_text = False
        tables, text_parts = [], []
        for pi in range(min(n, max_pages)):
            page = pdf.pages[pi]
            if page_has_text(page):
                has_text = True
            for ti, tbl in enumerate(extract_table.find_tables(page, table_strategy)):
                rows = [[extract_table.clean_cell(c) for c in r] for r in tbl]
                rows = [r for r in rows if any(r)]
                if not rows:
                    continue
                tables.append({
                    "page": pi + 1,
                    "index": ti,
                    "columns": extract_table.normalize_header(rows[0]),
                    "row_count": len(rows) - 1,
                    "sample": rows[1:1 + sample_rows],
                })
            text_parts.append(page.extract_text() or "")
            release(page)
        return {
            "page_count": n,
            "pages_scanned": min(n, max_pages),
            "has_text": has_text,
            "tables": tables,
            "text_sample": "\n".join(text_parts)[:4000],
        }


def match_pattern(pdf_path: str, pattern: str, pages: str | None = None, limit: int = 20) -> dict:
    """Regex debugger for block rules: show what a pattern hits, with context."""
    rx = compile_regex(pattern, "pattern")
    with open_pdf(pdf_path) as pdf:
        sel = parse_pages(pages, len(pdf.pages))
        hits, total = [], 0
        for pno, txt in extract_block.page_texts(pdf, sel):
            for m in rx.finditer(txt):
                total += 1
                if len(hits) < limit:
                    a, b = m.start(), m.end()
                    hits.append({
                        "page": pno,
                        "match": m.group(0),
                        "groups": m.groupdict() or list(m.groups()),
                        "context": txt[max(0, a - 60):b + 60],
                    })
        return {"total": total, "hits": hits}


def outline(pdf_path: str, rule: dict, limit: int = 60) -> dict:
    """Detected headings for a `sections` rule (no template/fields needed)."""
    rule = {**rule, "type": "sections"}
    validate_extraction(rule)
    with open_pdf(pdf_path) as pdf:
        pages = parse_pages(rule.get("pages"), len(pdf.pages))
        ensure_text_layer(pdf, pages)
        return extract_sections.outline(pdf, pages, rule, limit)


def validate_config(config: dict) -> dict:
    validate(config)
    compile_templates(config["template"])
    return {"valid": True}


def _atomic_write_stream(path: str, chunks) -> None:
    tmp = f"{path}.part"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            for c in chunks:
                fh.write(c)
        os.replace(tmp, path)
    except ConvertError:
        _silent_rm(tmp)
        raise
    except OSError as e:
        _silent_rm(tmp)
        raise ConvertError(OUTPUT_WRITE_FAILED, f"Cannot write staging output: {e}", {"path": path}) from e
    except BaseException:
        _silent_rm(tmp)
        raise


def _silent_rm(p: str) -> None:
    try:
        os.remove(p)
    except OSError:
        pass


def convert(pdf_path: str, config: dict, out_tmp_path: str, preview_n: int = 3) -> dict:
    """Extract -> map -> render. Writes ONLY to out_tmp_path (staging). Never touches final output."""
    validate(config)
    compiled = compile_templates(config["template"])  # fail fast before parsing the PDF
    rule = config["extraction"]
    sep = config["template"].get("separator", "\n")
    mode = (config.get("output") or {}).get("mode", "single_file")

    with open_pdf(pdf_path) as pdf:
        pages = parse_pages(rule.get("pages"), len(pdf.pages))
        ensure_text_layer(pdf, pages)
        mod = {"table": extract_table, "block": extract_block, "sections": extract_sections}[rule["type"]]
        columns, raw = mod.extract(pdf, pages, rule)

    records = map_records(columns, raw, config.get("fields") or [])
    if rule["type"] == "table" and rule.get("record_mode", "row") == "table":
        records = group_by_table(records, columns, config.get("fields") or [])
        columns = ["title", "page", "row_count", "table", "markdown", "rows"]
    meta = {"source_file": os.path.basename(pdf_path)}

    # Render everything up-front so a failure on record N never leaves a partial file.
    header = render_frame(compiled, "header", records, meta)
    bodies = [render_record(compiled, r, i) for i, r in enumerate(records)]
    footer = render_frame(compiled, "footer", records, meta)

    outputs: list[str] = []
    if mode == "single_file":
        def chunks():
            if header:
                yield header + ("" if header.endswith("\n") else "\n")
            for i, b in enumerate(bodies):
                yield (sep if i else "") + b
            if footer:
                yield ("\n" if bodies and not bodies[-1].endswith("\n") else "") + footer
        _atomic_write_stream(out_tmp_path, chunks())
        outputs.append(out_tmp_path)
    else:
        os.makedirs(out_tmp_path, exist_ok=True)
        from .render import _env
        name_tpl = _env().from_string((config.get("output") or {}).get("filename_pattern") or "record_{{ index }}")
        used: set[str] = set()
        for i, (r, b) in enumerate(zip(records, bodies)):
            name = safe_filename(name_tpl.render(**r, index=i + 1, record=r), f"record_{i + 1}")
            while name in used:
                name += "_"
            used.add(name)
            p = os.path.join(out_tmp_path, f"{name}.md")
            _atomic_write_stream(p, iter([header + b + footer]))
            outputs.append(p)

    n = max(0, preview_n)
    preview_md = (header + ("\n" if header and not header.endswith("\n") else "")) + sep.join(bodies[:n])
    empty_fields = {
        k: sum(1 for r in records if r.get(k) in (None, ""))
        for k in (records[0].keys() if records else [])
        if not k.startswith("_")
    }
    return {
        "ok": True,
        "record_count": len(records),
        "columns": columns,
        "preview": _json_safe(records[:n]),
        "preview_md": preview_md,
        "full_md_tmp_path": out_tmp_path,
        "outputs": outputs,
        "warnings": [
            {"code": "EMPTY_VALUES", "field": k, "count": c} for k, c in empty_fields.items() if c
        ],
    }
