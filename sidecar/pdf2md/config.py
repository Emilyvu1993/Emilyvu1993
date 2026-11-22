"""OutputConfig validation. Mirrors app/src/types/domain.ts — keep in sync."""
from __future__ import annotations

import re
from typing import Any

from .errors import INVALID_CONFIG, REGEX_INVALID, ConvertError

TRANSFORM_RE = re.compile(r"^(trim|upper|lower|number|number:eu|date:.+)$")
OUTPUT_MODES = {"single_file", "file_per_record"}


def _req(d: dict, key: str, path: str) -> Any:
    if key not in d:
        raise ConvertError(INVALID_CONFIG, f"Missing '{path}{key}'")
    return d[key]


def compile_regex(pattern: str, where: str) -> re.Pattern:
    try:
        return re.compile(pattern, re.MULTILINE)
    except re.error as e:
        raise ConvertError(REGEX_INVALID, f"Invalid regex in {where}: {e}", {"pattern": pattern, "where": where}) from e


def validate(cfg: Any) -> dict:
    if not isinstance(cfg, dict):
        raise ConvertError(INVALID_CONFIG, "Config must be an object")

    ex = _req(cfg, "extraction", "")
    if not isinstance(ex, dict):
        raise ConvertError(INVALID_CONFIG, "'extraction' must be an object")
    t = ex.get("type")
    if t == "table":
        hr = ex.get("header_row", 0)
        if not isinstance(hr, int) or hr < 0:
            raise ConvertError(INVALID_CONFIG, "'extraction.header_row' must be an integer >= 0")
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
    else:
        raise ConvertError(INVALID_CONFIG, "'extraction.type' must be 'table' or 'block'")

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
