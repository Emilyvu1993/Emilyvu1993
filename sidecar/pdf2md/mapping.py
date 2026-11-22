"""Field mapping + transforms. Numbers use Decimal (no float drift on money)."""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .errors import FIELD_MISSING, TRANSFORM_FAILED, ConvertError

# Only currency decoration may be stripped; anything else left over = error (no silent coercion).
_CCY = re.compile(r"^(?:[A-Z]{3}|[$€£¥₫đ])\s*|\s*(?:[A-Z]{3}|[$€£¥₫đ])$")
_NUM_OK = re.compile(r"^[+-]?(?:\d[\d.,\s]*)$")


def to_number(v: str, eu: bool = False) -> Decimal:
    s = str(v).strip()
    neg = s.startswith("(") and s.endswith(")")  # accounting negative: (1,234.00)
    if neg:
        s = s[1:-1].strip()
    prev = None
    while prev != s:
        prev, s = s, _CCY.sub("", s).strip()
    if not _NUM_OK.match(s):
        raise ValueError(f"not a number: {v!r}")
    s = s.replace(" ", "")
    if eu:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    d = Decimal(s)
    return -d if neg else d


def apply_transform(value: Any, transform: str | None) -> Any:
    if value is None or not transform:
        return value
    if transform == "trim":
        return str(value).strip()
    if transform == "upper":
        return str(value).upper()
    if transform == "lower":
        return str(value).lower()
    if transform in ("number", "number:eu"):
        if str(value).strip() == "":
            return None
        return to_number(value, eu=transform == "number:eu")
    if transform.startswith("date:"):
        fmt = transform[5:]
        in_fmt, _, out_fmt = fmt.partition(">")
        return datetime.strptime(str(value).strip(), in_fmt).strftime(out_fmt or "%Y-%m-%d")
    raise ValueError(f"unknown transform {transform}")


def sanitize_key(k: str) -> str:
    s = re.sub(r"\W+", "_", k.strip()).strip("_")
    if not s or s[0].isdigit():
        s = f"f_{s}"
    return s


def map_records(columns: list[str], records: list[dict], fields: list[dict]) -> list[dict]:
    if not fields:
        # passthrough: expose every source column under an identifier-safe name
        return [{sanitize_key(k): v for k, v in r.items()} for r in records]

    available = set(columns) | {"_raw", "_page"}
    missing = [f["source"] for f in fields if f["source"] not in available]
    if missing:
        raise ConvertError(
            FIELD_MISSING,
            f"Source field(s) not found: {', '.join(missing)}",
            {"missing": missing, "available": columns},
        )

    out = []
    for idx, r in enumerate(records):
        m: dict = {}
        for f in fields:
            v = r.get(f["source"])
            if (v is None or v == "") and "default" in f:
                v = f["default"]
            try:
                m[f["target"]] = apply_transform(v, f.get("transform"))
            except (ValueError, InvalidOperation, ArithmeticError) as e:
                raise ConvertError(
                    TRANSFORM_FAILED,
                    f"Record {idx + 1}: cannot apply '{f.get('transform')}' to field '{f['source']}'",
                    {"record_index": idx, "value": v, "error": str(e), "page": r.get("_page")},
                ) from e
        m["_page"] = r.get("_page")
        out.append(m)
    return out
