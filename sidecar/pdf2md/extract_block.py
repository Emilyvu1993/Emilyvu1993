"""Block-rule extraction: anchor-delimited text blocks -> list[dict]."""
from __future__ import annotations

from .config import compile_regex
from .errors import NO_RECORDS_FOUND, ConvertError
from .pdfio import apply_glyph_map, release


def page_texts(pdf, pages: list[int], glyph_map: dict | None = None) -> list[tuple[int, str]]:
    out = []
    for pi in pages:
        page = pdf.pages[pi]
        apply_glyph_map(page, glyph_map)
        out.append((pi + 1, page.extract_text() or ""))
        release(page)
    return out


def _pick(m) -> str | None:
    if m is None:
        return None
    gd = {k: v for k, v in m.groupdict().items() if v is not None}
    if "value" in gd:
        v = gd["value"]
    elif gd:
        v = next(iter(gd.values()))
    elif m.re.groups:
        v = m.group(1)
    else:
        v = m.group(0)
    return v.strip() if v is not None else None


def extract(pdf, pages: list[int], rule: dict) -> tuple[list[str], list[dict]]:
    start = compile_regex(rule["start_pattern"], "extraction.start_pattern")
    end = compile_regex(rule["end_pattern"], "extraction.end_pattern") if rule.get("end_pattern") else None
    fps = {k: compile_regex(v, f"extraction.field_patterns.{k}") for k, v in (rule.get("field_patterns") or {}).items()}

    # Join pages so blocks may span page breaks; keep offsets -> page map.
    parts, offsets, pos = [], [], 0
    for pno, txt in page_texts(pdf, pages, rule.get("glyph_map")):
        offsets.append((pos, pno))
        parts.append(txt)
        pos += len(txt) + 1
    text = "\n".join(parts)

    def page_at(off: int) -> int:
        p = offsets[0][1]
        for o, pno in offsets:
            if o <= off:
                p = pno
        return p

    starts = list(start.finditer(text))
    if not starts:
        raise ConvertError(
            NO_RECORDS_FOUND,
            "start_pattern matched nothing on the selected pages",
            {"start_pattern": rule["start_pattern"], "text_sample": text[:500]},
        )

    columns = list(start.groupindex.keys()) + [k for k in fps if k not in start.groupindex] + ["_raw"]
    records: list[dict] = []
    for i, m in enumerate(starts):
        b_end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        block = text[m.start():b_end]
        if end:
            em = end.search(block, m.end() - m.start())
            if em:
                block = block[: em.end()]
        rec: dict = {k: (v.strip() if v else None) for k, v in m.groupdict().items()}
        for k, rx in fps.items():
            rec[k] = _pick(rx.search(block))
        rec["_raw"] = block.strip()
        rec["_page"] = page_at(m.start())
        records.append(rec)
    return columns, records
