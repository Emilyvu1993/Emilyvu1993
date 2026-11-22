"""One record per table (e.g. per month), ruled-columns + text-rows strategy, symbol-font glyph maps."""
import copy

import pytest

from pdf2md import engine, errors, extract_sections as xs
from pdf2md.errors import ConvertError
from pdf2md.mapping import unique_keys
from pdf2md.pdfio import apply_glyph_map
from tests.conftest import GLYPHS


def code_of(fn, *a, **kw):
    with pytest.raises(ConvertError) as ei:
        fn(*a, **kw)
    return ei.value.code


def conv(pdf, cfg, tmp_path):
    out = tmp_path / "o.md"
    r = engine.convert(pdf, cfg, str(out))
    return r, out.read_text(encoding="utf-8")


def test_one_record_per_table_with_caption_and_glyphs(fx, eph_cfg, tmp_path):
    r, md = conv(fx["ephemeris_like"], eph_cfg, tmp_path)
    assert r["record_count"] == 2 and r["columns"][:3] == ["title", "page", "row_count"]
    assert [(p["title"], p["row_count"], p["page"]) for p in r["preview"]] == [("JANUARY 1994", 7, 1), ("FEBRUARY 1994", 5, 1)]
    assert md.startswith("## JANUARY 1994\\n\\n| Day | Sid.t | ☉ | ☽ |".replace("\\n", "\n"))   # header glyphs mapped, caption not the glyph row
    assert "| S 1 |" in md and "10♑20'16" in md                       # glyph placed between degrees and minutes
    assert "| S 5 |" in md and "| S 7 |" in md and "| S 8 |" not in md      # 7 + 5 rows, blank gaps ignored
    assert "|j|" not in md and "20'16" in md and "10 j" not in md and "10j" not in md


def test_word_gap_tolerance_keeps_narrow_spaces(fx, eph_cfg, tmp_path):
    _, md = conv(fx["ephemeris_like"], eph_cfg, tmp_path)
    assert "| S 1 | 64140 |" in md                                           # default 3pt joins "6" "41" "40"
    eph_cfg["extraction"]["text_x_tolerance"] = 1.5
    _, md = conv(fx["ephemeris_like"], eph_cfg, tmp_path)
    assert "| S 1 | 6 41 40 |" in md and "| S 2 | 6 42 40 |" in md


def test_fields_rename_columns_in_table_and_rows(fx, eph_cfg, tmp_path):
    eph_cfg["fields"] = [{"source": "Day", "target": "day"}, {"source": "☉", "target": "sun"}]
    r, md = conv(fx["ephemeris_like"], eph_cfg, tmp_path)
    assert md.startswith("## JANUARY 1994\n\n| day | sun |")
    assert r["preview"][0]["rows"][0] == {"day": "S 1", "sun": "10♑20'16"}
    eph_cfg["fields"] = [{"source": "Nope", "target": "x"}]
    assert code_of(conv, fx["ephemeris_like"], eph_cfg, tmp_path) == errors.FIELD_MISSING


def test_custom_template_loops_rows(fx, eph_cfg, tmp_path):
    eph_cfg["fields"] = [{"source": "Day", "target": "day"}, {"source": "☉", "target": "sun"}]
    eph_cfg["template"]["record"] = "{{ title }} ({{ row_count }})\n{% for r in rows %}{{ r.day }}={{ r.sun }};{% endfor %}\n"
    _, md = conv(fx["ephemeris_like"], eph_cfg, tmp_path)
    assert md.startswith("JANUARY 1994 (7)\nS 1=10♑20'16;S 2=11")  # first day of block 1


def test_row_mode_with_lines_text_and_safe_keys(fx, eph_cfg, tmp_path):
    eph_cfg["extraction"]["record_mode"] = "row"
    eph_cfg["template"]["record"] = "{{ Day }}|{{ col_3 }}"
    r, md = conv(fx["ephemeris_like"], eph_cfg, tmp_path)
    assert r["record_count"] == 12                                          # 7 + 5 day rows, captions are not rows
    assert r["preview"][0]["Day"] == "S 1" and r["preview"][0]["col_3"] == "10♑20'16"


def test_default_lines_strategy_cannot_split_these_rows(fx, eph_cfg, tmp_path):
    eph_cfg["extraction"]["table_strategy"] = "lines"
    r, _ = conv(fx["ephemeris_like"], eph_cfg, tmp_path)
    assert r["preview"][0]["row_count"] < 7                                 # why lines_text exists


def test_table_index_and_pages(fx, eph_cfg, tmp_path):
    eph_cfg["extraction"]["table_index"] = 1
    r, md = conv(fx["ephemeris_like"], eph_cfg, tmp_path)
    assert r["record_count"] == 1 and r["preview"][0]["title"] == "FEBRUARY 1994"
    eph_cfg["extraction"]["pages"] = "9"
    assert code_of(conv, fx["ephemeris_like"], eph_cfg, tmp_path) == errors.INVALID_PAGES


def test_no_table_in_text_pdf(fx, eph_cfg, tmp_path):
    assert code_of(conv, fx["text_report"], eph_cfg, tmp_path) == errors.TABLE_NOT_FOUND


@pytest.mark.parametrize("bad", [
    {"record_mode": "month"}, {"text_x_tolerance": 99}, {"text_x_tolerance": "wide"}, {"glyph_map": []},
    {"glyph_map": {"": {"a": "b"}}}, {"glyph_map": {"F": {"ab": "x"}}}, {"glyph_map": {"F": {"a": 1}}}, {"glyph_map": {"F": "x"}},
    {"table_strategy": "grid"}])
def test_invalid_table_options(fx, eph_cfg, tmp_path, bad):
    eph_cfg["extraction"].update(bad)
    assert code_of(conv, fx["ephemeris_like"], eph_cfg, tmp_path) == errors.INVALID_CONFIG


def test_failure_leaves_staging_untouched(fx, eph_cfg, tmp_path):
    out = tmp_path / "o.md"
    out.write_text("OLD")
    eph_cfg["template"]["record"] = "{{ nope }}"
    assert code_of(engine.convert, fx["ephemeris_like"], eph_cfg, str(out)) == errors.TEMPLATE_RENDER
    assert out.read_text() == "OLD"


# ---------- units ----------
class _Page:
    def __init__(self, chars):
        self.chars = chars


def test_apply_glyph_map_by_font_substring():
    pg = _Page([{"fontname": "ABC+Adienst1", "text": "j"}, {"fontname": "ABC+Adienst1", "text": "z"},
                {"fontname": "Times", "text": "j"}])
    apply_glyph_map(pg, {"adienst": {"j": "♑"}})
    assert [c["text"] for c in pg.chars] == ["♑", "z", "j"]
    apply_glyph_map(pg, None)
    apply_glyph_map(pg, {})


def test_unique_keys_handles_symbols_and_duplicates():
    assert unique_keys(["☉", "☽", "Day", "Day", "Sid.t", "", "2024"]) == \
        ["col_1", "col_2", "Day", "Day_2", "Sid_t", "col_6", "f_2024"]


# ---------- sections guard against symbol-font noise ----------
def test_lone_symbols_are_not_headings(fx):
    o = engine.outline(fx["ephemeris_like"], {"heading_mode": "font", "glyph_map": GLYPHS})
    assert all(xs.WORD_RE.search(h["title"]) for h in o["headings"])
    assert o["warning"] is None


def test_many_headings_warning(fx):
    o = engine.outline(fx["many_heads"], {"heading_mode": "font"})
    assert o["total"] >= 26 and "look like" in o["warning"]  # a few margin lines are dropped as running headers
    assert engine.outline(fx["text_report"], {"heading_mode": "font"})["warning"] is None


def test_glyph_map_applies_to_sections_and_blocks(fx, tmp_path):
    ex = {"type": "block", "start_pattern": r"^(?P<d>S \d)", "glyph_map": GLYPHS}
    cfg = {"extraction": ex, "fields": [], "template": {"record": "{{ _raw }}"}}
    cfg2 = copy.deepcopy(cfg)
    cfg2["template"]["record"] = "{{ raw }}"
    r = engine.convert(fx["ephemeris_like"], cfg2, str(tmp_path / "b.md"))
    assert r["record_count"] >= 12 and "♑" in (tmp_path / "b.md").read_text(encoding="utf-8")
