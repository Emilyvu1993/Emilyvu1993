"""Astrodienst angle convention: only when configured AND the page uses that font; tables only."""
import pytest

from pdf2md import engine, errors
from pdf2md.angles import convert_body, format_angle, page_uses_font, skip_set
from pdf2md.errors import ConvertError

ANGLE = {"font": "Courier", "skip_columns": ["Sid.t"]}   # "Courier" plays the Astrodienst font in the fixture


def code_of(fn, *a, **kw):
    with pytest.raises(ConvertError) as ei:
        fn(*a, **kw)
    return ei.value.code


def conv(pdf, cfg, tmp_path):
    out = tmp_path / "o.md"
    r = engine.convert(pdf, cfg, str(out))
    return r, out.read_text(encoding="utf-8")


@pytest.mark.parametrize("raw,want", [
    ("10♑20'16", "10♑20′16″"), ("11°21'24", "11°21′24″"), ("18♌17", "18♌17′"), ("27° 6", "27°6′"),
    ("27♒ 0", "27♒0′"), ("2°R26", "2°R26′"), ("0°R 1", "0°R1′"), ("29°D57", "29°D57′"),
    ("6 45 37", "6°45′37″"), ("6 1 5", "6°1′5″"), ("10♑20′16", "10♑20′16″"),
])
def test_format_angle_converts(raw, want):
    assert format_angle(raw) == want


@pytest.mark.parametrize("raw", ["S 1", "M10", "64140", "1,234.50", "10 20", "", "Day", "☉", "2024-01-05", "12°", "100 200 300",
                                 "3 4 5 6", "10♑", "a 6 45 37"])
def test_format_angle_leaves_other_text_alone(raw):
    assert format_angle(raw) == raw


def test_helpers():
    assert skip_set({"skip_columns": [" Sid.t ", "DAY"]}) == {"sid.t", "day"}
    assert convert_body(["Day", "Sid.t", "Sun"], [["S 1", "6 41 40", "10°20'16"]], {"sid.t"}) == [["S 1", "6 41 40", "10°20′16″"]]

    class P:
        chars = [{"fontname": "ABC+Adienst1"}, {"fontname": "Times"}]
    assert page_uses_font(P, "adienst") and not page_uses_font(P, "nofont")


# ---------- through the engine ----------
def test_converts_positions_and_keeps_sid_t(fx, eph_cfg, tmp_path):
    eph_cfg["extraction"].update(text_x_tolerance=1.5, angle_format=ANGLE)
    r, md = conv(fx["ephemeris_like"], eph_cfg, tmp_path)
    assert "10♑20′16″" in md and "11°21′24″" in md                       # sign+min+sec, deg+min+sec
    assert "20°5′" in md                                                  # "20° 5": space dropped, minute mark added
    assert "| S 1 | 6 41 40 |" in md                                       # Sid.t is sidereal time: untouched
    assert "| S 1 |" in md and "'" not in md                              # day labels intact, no ASCII minute marks left
    assert r["preview"][0]["rows"][0]["col_3"] == "10♑20′16″"


def test_skip_columns_empty_converts_sid_t_too_and_is_case_insensitive(fx, eph_cfg, tmp_path):
    eph_cfg["extraction"].update(text_x_tolerance=1.5, angle_format={"font": "Courier", "skip_columns": []})
    _, md = conv(fx["ephemeris_like"], eph_cfg, tmp_path)
    assert "| S 1 | 6°41′40″ |" in md
    eph_cfg["extraction"]["angle_format"] = {"font": "courier", "skip_columns": ["SID.T"]}
    _, md = conv(fx["ephemeris_like"], eph_cfg, tmp_path)
    assert "| S 1 | 6 41 40 |" in md and "10♑20′16″" in md


def test_row_mode_too(fx, eph_cfg, tmp_path):
    eph_cfg["extraction"].update(record_mode="row", text_x_tolerance=1.5, angle_format=ANGLE)
    eph_cfg["template"]["record"] = "{{ Day }}|{{ Sid_t }}|{{ col_3 }}|{{ col_4 }}"
    r, md = conv(fx["ephemeris_like"], eph_cfg, tmp_path)
    assert md.splitlines()[0] == "S 1|6 41 40|10♑20′16″|20°5′"
    assert r["record_count"] == 12


def test_not_applied_without_the_font_or_without_the_rule(fx, eph_cfg, tmp_path):
    _, md = conv(fx["ephemeris_like"], eph_cfg, tmp_path)                 # generic glyph_map only: no convention
    assert "10♑20'16" in md and "′" not in md and "″" not in md
    eph_cfg["extraction"]["angle_format"] = {"font": "nofont", "skip_columns": []}
    _, md = conv(fx["ephemeris_like"], eph_cfg, tmp_path)                 # configured, but the page lacks that font
    assert "10♑20'16" in md and "′" not in md


def test_fields_see_converted_values(fx, eph_cfg, tmp_path):
    eph_cfg["extraction"].update(record_mode="row", text_x_tolerance=1.5, angle_format=ANGLE)
    eph_cfg["fields"] = [{"source": "☉", "target": "sun"}, {"source": "Sid.t", "target": "sid"}]
    eph_cfg["template"]["record"] = "{{ sun }}|{{ sid }}"
    _, md = conv(fx["ephemeris_like"], eph_cfg, tmp_path)
    assert md.splitlines()[0] == "10♑20′16″|6 41 40"


@pytest.mark.parametrize("af", [{}, {"font": ""}, {"font": 3}, {"font": "x", "skip_columns": "Sid.t"},
                                {"font": "x", "skip_columns": [1]}, "adienst"])
def test_invalid_angle_format(fx, eph_cfg, tmp_path, af):
    eph_cfg["extraction"]["angle_format"] = af
    assert code_of(conv, fx["ephemeris_like"], eph_cfg, tmp_path) == errors.INVALID_CONFIG


def test_angle_format_rejected_for_other_types(fx, tmp_path):
    cfg = {"extraction": {"type": "sections", "angle_format": ANGLE}, "fields": [], "template": {"record": "{{ markdown }}"}}
    assert code_of(engine.convert, fx["text_report"], cfg, str(tmp_path / "o.md")) == errors.INVALID_CONFIG
