"""Sections in a tarot-style document: stand-alone labels, bold labels, emphasis, parent group."""
import re

import pytest

from pdf2md import engine, errors, extract_sections as xs
from pdf2md.errors import ConvertError

EXCLUDE = r"^(Is|Are) (it|he|she|they)\b.*upside down\?$"


def code_of(fn, *a, **kw):
    with pytest.raises(ConvertError) as ei:
        fn(*a, **kw)
    return ei.value.code


def recs(pdf, **rule):
    cfg = {"extraction": {"type": "sections", **rule}, "fields": [], "template": {"record": "{{ markdown }}\n"}}
    import tempfile, os
    out = os.path.join(tempfile.mkdtemp(), "o.md")
    r = engine.convert(pdf, cfg, out)
    return r, open(out, encoding="utf-8").read()


def sections(pdf, **rule):
    from pdf2md.pdfio import open_pdf, parse_pages
    with open_pdf(pdf) as d:
        _, rs = xs.extract(d, parse_pages(rule.get("pages"), len(d.pages)), {"type": "sections", **rule})
    return rs


def test_without_exclusion_stand_alone_labels_become_records(fx):
    titles = [r["title"] for r in sections(fx["tarot_like"])]
    assert titles.count("Is it upside down?") == 3          # the problem on the real file (56 there)
    assert len(titles) == 2 + 3 + 3 + 3


def test_exclusion_keeps_groups_and_cards_only(fx):
    rs = sections(fx["tarot_like"], heading_exclude=EXCLUDE)
    assert [(r["title"], r["level"], r["parent"]) for r in rs] == [
        ("The Major Arcana", 1, ""), ("0 The Fool says: Look before you leap!", 2, "The Major Arcana"),
        ("I The Magician says: Go, go go!", 2, "The Major Arcana"), ("The Chariot says: You can move on", 2, "The Major Arcana"),
        ("Suit of Wands", 1, ""), ("Ace of Wands", 2, "Suit of Wands"), ("Two of Wands", 2, "Suit of Wands"),
        ("Three of Wands", 2, "Suit of Wands")]
    assert xs.COLUMNS[:3] == ["title", "level", "parent"]


def test_labels_start_their_own_paragraph_and_keep_emphasis(fx):
    fool = sections(fx["tarot_like"], heading_exclude=EXCLUDE)[1]
    paras = fool["body"].split("\n\n")
    assert len(paras) == 4
    assert paras[1].startswith("**Home:** A fairly long sentence")
    assert paras[2].startswith("**Love and Relationships:** ")
    assert paras[3].startswith("***Is he upside down?*** ")
    assert "**" not in paras[0]                              # unlabelled text stays plain
    ace = sections(fx["tarot_like"], heading_exclude=EXCLUDE)[5]
    assert ace["body"].split("\n\n")[1].startswith("***Is it upside down?*** A fairly")   # label + its text, after the blank gap


def test_emphasis_off_is_plain_but_same_wording(fx):
    on = sections(fx["tarot_like"], heading_exclude=EXCLUDE)
    off = sections(fx["tarot_like"], heading_exclude=EXCLUDE, emphasis=False)
    assert not any("*" in r["body"] for r in off)
    norm = lambda t: re.sub(r"\s+", " ", t.replace("*", "")).strip()
    assert [norm(r["body"]) for r in on] == [norm(r["body"]) for r in off]
    assert off[1]["body"].split("\n\n")[1].startswith("Home: A fairly")     # label paragraphs are independent of emphasis


def test_markdown_output_and_top3(fx):
    r, md = recs(fx["tarot_like"], heading_exclude=EXCLUDE)
    assert r["record_count"] == 8 and [p["title"] for p in r["preview"]][:2] == ["The Major Arcana", "0 The Fool says: Look before you leap!"]
    assert "# The Major Arcana\n\n" in md and "\n## 0 The Fool says: Look before you leap!\n\n" in md
    assert r["preview"][1]["parent"] == "The Major Arcana"


def test_parent_available_to_fields_and_template(fx, tmp_path):
    cfg = {"extraction": {"type": "sections", "heading_exclude": EXCLUDE},
           "fields": [{"source": "title", "target": "t"}, {"source": "parent", "target": "grp"}],
           "template": {"record": "{{ grp }}|{{ t }}"}}
    out = tmp_path / "o.md"
    engine.convert(fx["tarot_like"], cfg, str(out))
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "|The Major Arcana" and lines[1] == "The Major Arcana|0 The Fool says: Look before you leap!"


def test_exclusion_applies_in_every_mode(fx):
    rx = {"heading_mode": "regex", "heading_pattern": r"says:|of Wands|upside down", "heading_exclude": r"upside down"}
    assert not any("upside down" in r["title"] for r in sections(fx["tarot_like"], **rx))
    assert any("upside down" in r["title"] for r in sections(fx["tarot_like"], **{**rx, "heading_exclude": ""}))


@pytest.mark.parametrize("bad,code", [({"heading_exclude": "(unclosed"}, errors.REGEX_INVALID),
                                      ({"heading_exclude": 5}, errors.INVALID_CONFIG),
                                      ({"emphasis": "yes"}, errors.INVALID_CONFIG)])
def test_invalid_options(fx, tmp_path, bad, code):
    assert code_of(recs, fx["tarot_like"], **bad) == code


def test_outline_reflects_exclusion(fx):
    assert engine.outline(fx["tarot_like"], {"heading_mode": "font"})["total"] == 11
    assert engine.outline(fx["tarot_like"], {"heading_mode": "font", "heading_exclude": EXCLUDE})["total"] == 8


# ---------- units ----------
def _c(text, font, x0, size=10):
    return {"text": text, "fontname": font, "x0": x0, "x1": x0 + 5, "size": size}


def test_styled_runs_and_md():
    chars = [_c("H", "Calibri-Bold", 0), _c("i", "Calibri-Bold", 5), _c(":", "Calibri-Bold", 10), _c(" ", "Calibri", 15),
             _c("o", "Calibri", 20), _c("k", "Calibri-Italic", 25)]
    runs = xs._styled_runs(chars, "Hi: ok", True)
    assert runs == [("Hi: ", True, False, False), ("o", False, False, False), ("k", False, True, False)]   # (text, bold, italic, mono)
    assert xs.Line("Hi: ok", 1, 0, 1, 10, False, 800, runs=runs).md() == "**Hi:** o*k*"
    assert xs.Line("x", 1, 0, 1, 10, False, 800).md() == "x"                         # no runs: plain
    assert xs._styled_runs(chars, "something else", True) == []                      # never alter the wording
    bi = [_c("a", "X-BoldOblique", 0), _c("b", "X-BoldOblique", 5)]
    assert xs.Line("ab", 1, 0, 1, 10, True, 800, runs=xs._styled_runs(bi, "ab", True)).md() == "***ab***"


def test_label_not_started_when_it_wraps_from_the_line_above():
    mk = lambda runs: xs.Line("t", 1, 0, 1, 10, False, 800, runs=runs)
    label = mk([("Home:", True, False), (" text", False, False)])
    assert xs._starts_label(label, None)
    assert not xs._starts_label(label, mk([("see ", False, False), ("Is he", True, True)]))   # label continues
    assert not xs._starts_label(mk([("All bold:", True, False)]), None)                       # no regular text after it
    assert not xs._starts_label(mk([("A long bold phrase without colon", True, False), (" x", False, False)]), None)
