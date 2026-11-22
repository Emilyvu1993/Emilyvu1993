"""PDF opening, page selection and text-layer checks (pdfplumber only)."""
from __future__ import annotations

import os
import re
from contextlib import contextmanager
from typing import Iterator

import pdfplumber
from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect
from pdfminer.pdfparser import PDFSyntaxError

from .errors import (
    INVALID_PAGES,
    NO_TEXT_LAYER,
    PDF_CORRUPT,
    PDF_ENCRYPTED,
    PDF_NOT_FOUND,
    ConvertError,
)

_RANGE = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+)\s*)?$")


@contextmanager
def open_pdf(path: str) -> Iterator[pdfplumber.PDF]:
    if not os.path.isfile(path):
        raise ConvertError(PDF_NOT_FOUND, f"File not found: {path}")
    try:
        pdf = pdfplumber.open(path)
        _ = len(pdf.pages)  # force page tree parse
    except (PDFPasswordIncorrect, PDFEncryptionError) as e:
        raise ConvertError(PDF_ENCRYPTED, "PDF is password protected", str(e)) from e
    except (PDFSyntaxError, Exception) as e:  # noqa: BLE001 - any parse failure = corrupt
        if "password" in str(e).lower():
            raise ConvertError(PDF_ENCRYPTED, "PDF is password protected", str(e)) from e
        raise ConvertError(PDF_CORRUPT, "PDF cannot be parsed", f"{type(e).__name__}: {e}") from e
    try:
        yield pdf
    finally:
        pdf.close()


def parse_pages(spec: str | None, page_count: int) -> list[int]:
    """'1-3,5' (1-based, inclusive) -> [0,1,2,4]. None/'' -> all pages."""
    if spec is None or not str(spec).strip():
        return list(range(page_count))
    out: list[int] = []
    for part in str(spec).split(","):
        m = _RANGE.match(part)
        if not m:
            raise ConvertError(INVALID_PAGES, f"Invalid page range '{part.strip()}'", {"pages": spec})
        a = int(m.group(1))
        b = int(m.group(2) or a)
        if a < 1 or b < a:
            raise ConvertError(INVALID_PAGES, f"Invalid page range '{part.strip()}'", {"pages": spec})
        if a > page_count:
            raise ConvertError(
                INVALID_PAGES,
                f"Page {a} out of range (document has {page_count} pages)",
                {"pages": spec, "page_count": page_count},
            )
        for p in range(a, min(b, page_count) + 1):
            if p - 1 not in out:
                out.append(p - 1)
    return out


def page_has_text(page) -> bool:
    return any(c.get("text", "").strip() for c in page.chars)


def ensure_text_layer(pdf: pdfplumber.PDF, pages: list[int]) -> None:
    for i in pages:
        if page_has_text(pdf.pages[i]):
            return
    raise ConvertError(
        NO_TEXT_LAYER,
        "No selectable text found (scanned/image PDF is not supported)",
        {"pages_checked": [p + 1 for p in pages]},
    )


def release(page) -> None:
    """Drop cached layout objects; keeps memory flat on large PDFs."""
    try:
        page.flush_cache()
        page.get_textmap.cache_clear()
    except Exception:  # noqa: BLE001
        pass
