"""Stable error codes shared with the Rust core and UI. Do not rename codes."""
from __future__ import annotations

from typing import Any

PDF_NOT_FOUND = "PDF_NOT_FOUND"
PDF_ENCRYPTED = "PDF_ENCRYPTED"
PDF_CORRUPT = "PDF_CORRUPT"
NO_TEXT_LAYER = "NO_TEXT_LAYER"
TEXT_ENCODING_BROKEN = "TEXT_ENCODING_BROKEN"
INVALID_CONFIG = "INVALID_CONFIG"
INVALID_PAGES = "INVALID_PAGES"
TABLE_NOT_FOUND = "TABLE_NOT_FOUND"
NO_RECORDS_FOUND = "NO_RECORDS_FOUND"
REGEX_INVALID = "REGEX_INVALID"
FIELD_MISSING = "FIELD_MISSING"
TRANSFORM_FAILED = "TRANSFORM_FAILED"
TEMPLATE_SYNTAX = "TEMPLATE_SYNTAX"
TEMPLATE_RENDER = "TEMPLATE_RENDER"
OUTPUT_WRITE_FAILED = "OUTPUT_WRITE_FAILED"
RPC_BAD_REQUEST = "RPC_BAD_REQUEST"
INTERNAL = "INTERNAL"


class ConvertError(Exception):
    def __init__(self, code: str, message: str, detail: Any = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail is not None:
            d["detail"] = self.detail
        return d
