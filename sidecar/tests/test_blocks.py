"""keep_blocks: tables as GFM, code blocks fenced, inline code, tables / code that continue on the next page."""
import json
import os
import re
import tempfile

import pytest

from pdf2md import blocks as bk
from pdf2md import engine, errors, extract_sections as xs
from pdf2md.errors import ConvertError
from pdf2md.pdfio import open_pdf, parse_pages

KEEP = {"type": "sections", "keep_blocks": True}


def sections(pdf, **rule):
    with open_pdf(pdf) as d:
        _, rs = xs.extract(d, parse_pages(rule.get("pages"), len(d.pages)), {**KEEP, **rule})
    return rs


def by_title(rs, title):
    return next(r for r in rs if r["title"] == title)


# ---------- structure ----------
def test_sections_and_no_leaked_table_text_as_headings(fx):
    rs = sections(fx["spec_like"])
    assert [(r["title"], r["level"], r["parent"]) for r in rs] == [
        ("Spec Doc", 1, ""), ("1 Endpoints", 2, "Spec Doc"), ("2 Request", 2, "Spec Doc"), ("Fields", 3, "2 Request"),
        ("JSON example", 3, "2 Request"), ("3 Output", 2, "Spec Doc")]


def test_table_is_gfm_with_joined_identifiers_and_no_phantom_rows(fx):
    md = by_title(sections(fx["spec_like"]), "Fields")["markdown"]
    lines = [l for l in md.splitlines() if l.startswith("|")]
    assert lines[0] == "| Field | Type | Purpose |" and lines[1] == "| --- | --- | --- |"
    names = [re.match(r"\| `([^`]+)`", l).group(1) for l in lines[2:]]
    # wrapped names are rejoined (no 'priceaffteratt r'), the table continued on page 2 is one table, no extra rows
    assert names == ["cifcode", "priceaffterattr", "registrationdate", "accomodationprovinceCode", "extraData"]
    assert "| `priceaffterattr` | Number | Appraised value, VND |" in md
    assert md.count("| Field |") == 1                                   # the header repeated on page 2 was dropped


def test_code_blocks_fenced_json_detected_and_merged_across_pages(fx):
    rs = sections(fx["spec_like"])
    ep = by_title(rs, "1 Endpoints")["body"]
    assert "```\nPOST http://host/predict\nContent-Type: application/json\n```" in ep         # not JSON: no language
    js = by_title(rs, "JSON example")["body"]
    m = re.fullmatch(r"```json\n(.*)\n```", js, re.S)
    assert m, js
    assert json.loads(m.group(1)) == {"cifcode": "2510808575", "assettype": "17", "extraData": {"loan_id": 1}}
    assert '  "cifcode": "2510808575",' in js and '    "loan_id": 1' in js                       # indentation kept
    assert js.count("```") == 2                                                               # one block, not two


def test_reading_order_and_paragraph_after_block(fx):
    body = by_title(sections(fx["spec_like"]), "1 Endpoints")["body"]
    assert body.index("```") < body.index("Intro paragraph")                                 # code first, then the paragraph


def test_off_by_default_keeps_the_flat_text(fx):
    rs = sections(fx["spec_like"], keep_blocks=False)
    md = "\n".join(r["markdown"] for r in rs)
    assert "```" not in md and "| --- |" not in md


def test_fallbacks_without_cards(fx):
    # a ruled table without any card is found on the whole page
    rs = sections(fx["table_heading"])
    md = by_title(rs, "Report")["markdown"]
    assert "| Date | Description | Amount |" in md and "| 02/01/2026 | Payment #1 | 1,000.50 |" in md
    # monospace lines without a box become one fenced block
    rs = sections(fx["mono_lines"])
    assert "```\npdf2md input.pdf\n  --pages 1-3\n  --out result.md\n```" in by_title(rs, "Usage")["body"]


@pytest.mark.parametrize("bad", [{"keep_blocks": "yes"}, {"keep_blocks": 1}])
def test_invalid_option(fx, bad):
    cfg = {"extraction": {"type": "sections", **bad}, "fields": [], "template": {"record": "{{ markdown }}"}}
    with pytest.raises(ConvertError) as ei:
        engine.convert(fx["spec_like"], cfg, os.path.join(tempfile.mkdtemp(), "o.md"))
    assert ei.value.code == errors.INVALID_CONFIG


# ---------- units ----------
def test_find_cards_drops_page_frame_and_fragments(fx):
    with open_pdf(fx["spec_like"]) as d:
        cards = [bk.find_cards(pg) for pg in d.pages]
    assert [len(c) for c in cards] == [2, 2, 1]                     # p1: code + table, p2: table + code, p3: code; frames dropped
    for page_cards in cards:
        assert all(c[3] - c[1] < 0.9 * 842 for c in page_cards)      # no page-sized frame left


def _tbl(page, header, rows, top=28.0, bottom=800.0, h=842.0):
    return bk.Block("table", page, h, (28, top, 567, bottom), header=header, rows=rows)


def _code(page, lines, top=28.0, bottom=800.0, h=842.0):
    return bk.Block("code", page, h, (28, top, 567, bottom), code=lines)


def test_merge_across_pages_rules():
    a, b = _tbl(1, ["Field", "Type"], [["a", "x"]], top=600), _tbl(2, ["`Field`", "type"], [["b", "y"]], bottom=100)
    bk.merge_across_pages({1: [a], 2: [b]})
    assert b.skip and a.rows == [["a", "x"], ["b", "y"]]                       # same header (case / ticks ignored) -> continued
    a, b = _tbl(1, ["Field", "Type"], [["a", "x"]], top=600), _tbl(2, ["Other", "Cols"], [["b", "y"]], bottom=100)
    bk.merge_across_pages({1: [a], 2: [b]})
    assert not b.skip                                                           # different header -> a new table
    a, b = _tbl(1, ["F", "T"], [["a", "x"]], top=600, bottom=500), _tbl(2, ["F", "T"], [["b", "y"]], bottom=100)
    bk.merge_across_pages({1: [a], 2: [b]})
    assert not b.skip                                                           # the first one does not reach the page bottom
    a, b = _code(1, ["{"], top=300), _code(2, ["}"], bottom=60)
    bk.merge_across_pages({1: [a], 2: [b]})
    assert b.skip and a.code == ["{", "}"]
    # chains across three pages
    a, b, c = _tbl(1, ["F", "T"], [["1", "x"]], top=600), _tbl(2, ["F", "T"], [["2", "y"]]), _tbl(3, ["F", "T"], [["3", "z"]], bottom=100)
    bk.merge_across_pages({1: [a], 2: [b], 3: [c]})
    assert a.rows == [["1", "x"], ["2", "y"], ["3", "z"]] and b.skip and c.skip


def test_render_and_fence():
    t = bk.Block("table", 1, 842, (0, 0, 1, 1), header=["", "B"], rows=[["a|b", "c"]])
    assert bk.render(t) == "|   | B |\n| --- | --- |\n| a|b | c |"
    assert bk._fence(['{"a": 1}']) == '```json\n{"a": 1}\n```'
    assert bk._fence(["x = 1", "```"]).startswith("````\n") and bk._fence(["not json"]).startswith("```\n")
