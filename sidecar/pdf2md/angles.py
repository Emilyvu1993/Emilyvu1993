"""Astrodienst ephemeris angle notation -> degree / minute / second symbols.

This is a convention of ONE symbol font (Astrodienst), not of symbol fonts in general:
it is only applied when `extraction.angle_format` is configured AND the page really uses that font.

    10♑20'16  -> 10♑20′16″      sign + minutes + seconds
    11°21'24  -> 11°21′24″
    18♌17     -> 18♌17′         degrees + sign + minutes
    27° 6     -> 27°6′          alignment space dropped, digits kept
    2°R26     -> 2°R26′         retrograde / direct flag kept
    6 45 37   -> 6°45′37″       three numbers
Anything else is returned unchanged.
"""
from __future__ import annotations

import re

SIGNS = "♈♉♊♋♌♍♎♏♐♑♒♓"
DEG, MIN, SEC = "°", "′", "″"

# degrees, then a degree mark or a zodiac sign, optional R/D flag, minutes, optional 'seconds
_POSITION = re.compile(rf"^(\d{{1,3}})([{DEG}{SIGNS}])\s*([RD])?\s*(\d{{1,2}})(?:\s*['{MIN}]\s*(\d{{1,2}}))?$")
_THREE = re.compile(r"^(\d{1,3})\s+(\d{1,2})\s+(\d{1,2})$")


def format_angle(text: str) -> str:
    t = text.strip()
    m = _POSITION.match(t)
    if m:
        d, mark, flag, mi, se = m.groups()
        return f"{d}{mark}{flag or ''}{mi}{MIN}" + (f"{se}{SEC}" if se is not None else "")
    m = _THREE.match(t)
    if m:
        d, mi, se = m.groups()
        return f"{d}{DEG}{mi}{MIN}{se}{SEC}"
    return text


def skip_set(angle: dict) -> set[str]:
    return {str(c).strip().lower() for c in (angle.get("skip_columns") or [])}


def convert_row(header: list[str], row: list[str], skip: set[str]) -> list[str]:
    return [c if h.strip().lower() in skip else format_angle(c) for h, c in zip(header, row)]


def convert_body(header: list[str], rows: list[list[str]], skip: set[str]) -> list[list[str]]:
    return [convert_row(header, r, skip) for r in rows]


def page_uses_font(page, font: str) -> bool:
    """True if any glyph on the page comes from a font whose name contains `font` (case-insensitive)."""
    f = font.lower()
    return any(f in c.get("fontname", "").lower() for c in page.chars)
