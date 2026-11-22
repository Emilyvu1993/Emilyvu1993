"""OutputConfig validation. Mirrors app/src/types/domain.ts — keep in sync."""
from __future__ import annotations

import re
from typing import Any

from .errors import INVALID_CONFIG, REGEX_INVALID, ConvertError

TRANSFORM_RE = re.compile(r"^(trim|upper|lower|number|number:eu|date:.+)$")
OUTPUT_MODES = {"single_file", "file_per_record"}
HEADING_MODES = {"font", "numbering", "regex"}
SECTION_BOOLS = ("bold_headings", "include_preamble", "join_lines", "skip_header_footer", "normalize_unicode")


def _req(d: dict, key: str, path: str) -> Any:
    if key not in d:
        raise ConvertError(INVALID_CONFIG, f"Missing '{path}{key}'")
    return d[key]


def compile_regex(pattern: str, where: str) -> re.Pattern:
    try:
        return re.compile(pattern, re.MULTILINE)
    except re.error as e:
        raise ConvertError(REGEX_INVALID, f"Invalid regex in {where}: {e}", {"pattern": pattern, "where": where}) from e


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_sections(ex: dict) -> None:
    mode = ex.get("heading_mode", "font")
    if mode not in HEADING_MODES:
        raise ConvertError(INVALID_CONFIG, f"'extraction.heading_mode' must be one of {sorted(HEADING_MODES)}")
    r = ex.get("size_ratio", 1.15)
    if not _is_num(r) or not 1.0 <= r <= 4.0:
        raise ConvertError(INVALID_CONFIG, "'extraction.size_ratio' must be a number between 1.0 and 4.0")
    m = ex.get("max_heading_chars", 120)
    if not isinstance(m, int) or isinstance(m, bool) or not 1 <= m <= 500:
        raise ConvertError(INVALID_CONFIG, "'extraction.max_heading_chars' must be an integer between 1 and 500")
    for k in SECTION_BOOLS:
        if k in ex and not isinstance(ex[k], bool):
            raise ConvertError(INVALID_CONFIG, f"'extraction.{k}' must be true or false")
    if mode == "regex":
        hp = ex.get("heading_pattern")
        if not isinstance(hp, str) or not hp:
            raise ConvertError(INVALID_CONFIG, "'extraction.heading_pattern' is required when heading_mode is 'regex'")
        compile_regex(hp, "extraction.heading_pattern")


def validate_extraction(ex: Any) -> None:
    if not isinstance(ex, dict):
        raise ConvertError(INVALID_CONFIG, "'extraction' must be an object")
    t = ex.get("type")
    if t == "table":
        hr = ex.get("header_row", 0)
        if not isinstance(hr, int) or hr < 0:
            raise ConvertError(INVALID_CONFIG, "'extraction.header_row' must be an integer >= 0")
        if ex.get("table_strategy", "auto") not in ("auto", "lines", "text"):
            raise ConvertError(INVALID_CONFIG, "'extraction.table_strategy' must be auto, lines or text")
        ti = ex.get("table_index")
        if ti is not None and (not isinstance(ti, int) or ti < 0):
            raise ConvertError(INVALID_CONFIG, "'extraction.table_index' must be an integer >= 0")
    elif t == "block":
        sp = _req(ex, "start_pattern", "extraction.")
        if not isinstance(sp, str) or not sp:
            raise ConvertError(INVALID_CONFIG, "'extraction.start_pattern' must be a non-empty string")
        compile_regex(sp, "extraction.start_pattern")
        if ex.get("end_pattern"):
            compile_regex(ex["end_pattern"], "extraction.end_pattern")
        fp = ex.get("field_patterns", {}) or {}
        if not isinstance(fp, dict):
            raise ConvertError(INVALID_CONFIG, "'extraction.field_patterns' must be an object")
        for k, v in fp.items():
            compile_regex(v, f"extraction.field_patterns.{k}")
    elif t == "sections":
        validate_sections(ex)
    else:
        raise ConvertError(INVALID_CONFIG, "'extraction.type' must be 'table', 'block' or 'sections'")


def validate(cfg: Any) -> dict:
    if not isinstance(cfg, dict):
        raise ConvertError(INVALID_CONFIG, "Config must be an object")

    validate_extraction(_req(cfg, "extraction", ""))

    fields = cfg.get("fields", []) or []
    if not isinstance(fields, list):
        raise ConvertError(INVALID_CONFIG, "'fields' must be an array")
    targets: set[str] = set()
    for i, f in enumerate(fields):
        if not isinstance(f, dict) or not f.get("source") or not f.get("target"):
            raise ConvertError(INVALID_CONFIG, f"'fields[{i}]' needs 'source' and 'target'")
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", f["target"]):
            raise ConvertError(
                INVALID_CONFIG,
                f"'fields[{i}].target' must be an identifier (letters, digits, _), got '{f['target']}'",
            )
        if f["target"] in targets:
            raise ConvertError(INVALID_CONFIG, f"Duplicate target field '{f['target']}'")
        targets.add(f["target"])
        tr = f.get("transform")
        if tr and not TRANSFORM_RE.match(tr):
            raise ConvertError(INVALID_CONFIG, f"'fields[{i}].transform' unknown: '{tr}'")

    tpl = _req(cfg, "template", "")
    if not isinstance(tpl, dict) or not isinstance(tpl.get("record"), str) or not tpl["record"].strip():
        raise ConvertError(INVALID_CONFIG, "'template.record' must be a non-empty string")

    out = cfg.get("output", {}) or {}
    if out.get("mode", "single_file") not in OUTPUT_MODES:
        raise ConvertError(INVALID_CONFIG, f"'output.mode' must be one of {sorted(OUTPUT_MODES)}")
    return cfg
