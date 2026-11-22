"""Heading-based section extraction for text documents."""
import os
import re

import pytest

from pdf2md import engine, errors, extract_sections as xs
from pdf2md.errors import ConvertError
from pdf2md.pdfio import cid_ratio
from pdf2md.rpc import handle

VI = "Tổ chức, cá nhân có quyền sử dụng đất theo quy định của pháp luật hiện hành."
needs_dejavu = pytest.mark.skipif(not os.path.isfile("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), reason="DejaVu font missing")


def code_of(fn, *a, **kw):
    with pytest.raises(ConvertError) as ei:
        fn(*a, **kw)
    return ei.value.code


def run(pdf, ex, tmp_path, template="{{ markdown }}\n", fields=None):
    cfg = {"extraction": ex, "fields": fields or [], "template": {"record": template}, "output": {"mode": "single_file"}}
    out = tmp_path / "o.md"
    r = engine.convert(pdf, cfg, str(out))
    return r, out.read_text(encoding="utf-8")


# ---------- font-based headings ----------
def test_outline_levels_and_running_text_removed(fx):
    o = engine.outline(fx["text_report"], {"heading_mode": "font"})
    assert [(h["title"], h["level"], h["page"]) for h in o["headings"]] == [
        ("Annual Report", 1, 1), ("1. Results", 1, 1), ("1.1 Revenue", 2, 1),
        ("2. Outlook", 1, 2), ("2.1 Risks", 2, 2), ("3. Appendix", 1, 3)]
    assert o["body_size"] == 10.0
    assert all("ACME" not in h["title"] and not h["title"].startswith("Page") for h in o["headings"])


def test_convert_sections_records_and_markdown(fx, tmp_path):
    r, md = run(fx["text_report"], {"type": "sections"}, tmp_path)
    assert r["record_count"] == 6
    assert r["columns"] == xs.COLUMNS
    assert [p["title"] for p in r["preview"]] == ["Annual Report", "1. Results", "1.1 Revenue"]  # top 3
    assert r["preview"][2]["level"] == 2 and r["preview"][2]["page"] == 1
    assert "ACME Confidential" not in md and "Page 2" not in md          # running header/footer dropped
    assert md.startswith("# Annual Report\n\nIntro text.")
    assert "## 1.1 Revenue" in md and "# 2. Outlook" in md
    assert "- first point\n- second point" in md                        # bullets -> tight md list, cid glyph handled
    assert "(cid:" not in md
    assert r["preview_md"].count("\n# ") + r["preview_md"].count("\n## ") + 1 == 3


def test_paragraphs_join_wrapped_lines(fx, tmp_path):
    r, _ = run(fx["text_report"], {"type": "sections"}, tmp_path)
    body = r["preview"][1]["body"]
    assert "\n" not in body and body.startswith("Lorem ipsum dolor sit amet, consectetur")
    r, _ = run(fx["text_report"], {"type": "sections", "join_lines": False}, tmp_path)
    assert "\n" in r["preview"][1]["body"]


def test_bold_only_headings_and_toggle(fx, tmp_path):
    r, _ = run(fx["text_boldheads"], {"type": "sections"}, tmp_path)
    assert [p["title"] for p in r["preview"]] == ["Scope", "Terms"]
    assert code_of(run, fx["text_boldheads"], {"type": "sections", "bold_headings": False}, tmp_path) == errors.NO_RECORDS_FOUND


def test_no_headings_gives_actionable_error(fx, tmp_path):
    with pytest.raises(ConvertError) as ei:
        run(fx["text_flat"], {"type": "sections"}, tmp_path)
    e = ei.value
    assert e.code == errors.NO_RECORDS_FOUND
    assert e.detail["body_font_size"] == 10.0 and e.detail["font_sizes"][0]["size"] == 10.0


def test_size_ratio_threshold(fx, tmp_path):
    ex = {"type": "sections", "bold_headings": False, "size_ratio": 1.5}
    o = engine.outline(fx["text_report"], ex)
    assert {h["title"] for h in o["headings"]} == {"Annual Report", "1. Results", "2. Outlook", "3. Appendix"}  # 13pt < 15
    assert code_of(engine.outline, fx["text_report"], {**ex, "size_ratio": 9}) == errors.INVALID_CONFIG


def test_pages_selection(fx, tmp_path):
    r, _ = run(fx["text_report"], {"type": "sections", "pages": "2"}, tmp_path)
    assert [p["title"] for p in r["preview"]] == ["2. Outlook", "2.1 Risks"]


def test_page_subset_still_drops_running_header(fx, tmp_path):
    r, md = run(fx["text_report"], {"type": "sections", "pages": "2-3"}, tmp_path)
    assert r["record_count"] == 3 and "ACME" not in md          # header learned from the first pages, not only the subset


# ---------- numbering (Vietnamese legal) ----------
@needs_dejavu
def test_vietnamese_numbering_keeps_original_text(fx, tmp_path):
    ex = {"type": "sections", "heading_mode": "numbering"}
    r, md = run(fx["legal_vi"], ex, tmp_path)
    assert r["record_count"] == 5
    assert [(p["title"], p["level"]) for p in r["preview"][:3]] == [
        ("Chương I QUY ĐỊNH CHUNG", 1), ("Điều 1. Phạm vi điều chỉnh", 2), ("Điều 2. Đối tượng áp dụng", 2)]
    assert VI in md                                     # diacritics intact, not translated
    assert "ACME" not in md                             # 2 pages -> repeated header detected and dropped
    assert "# Chương II QUYỀN VÀ NGHĨA VỤ" in md
    assert "Điều 3. Quyền của người sử dụng đất" in md
    raw = open(tmp_path / "o.md", "rb").read()
    assert raw.decode("utf-8") and b"\r" not in raw    # UTF-8, LF


@needs_dejavu
def test_font_mode_cannot_see_same_size_headings_but_error_is_clear(fx, tmp_path):
    # headings are 12pt on 11pt body (ratio 1.09) and bold: bold rule catches them; with it off nothing matches
    assert code_of(run, fx["legal_vi"], {"type": "sections", "bold_headings": False}, tmp_path) == errors.NO_RECORDS_FOUND


@needs_dejavu
def test_single_page_running_header_is_a_known_limit(fx, tmp_path):
    ex = {"type": "sections", "heading_mode": "numbering"}
    r, _ = run(fx["legal_vi_1page"], ex, tmp_path)
    assert r["preview"][0]["level"] == 0 and "ACME" in r["preview"][0]["body"]       # cannot tell header from content
    r, _ = run(fx["legal_vi_1page"], {**ex, "include_preamble": False}, tmp_path)
    assert r["record_count"] == 1 and "ACME" not in r["preview_md"]


@pytest.mark.parametrize(
    "text,rank",
    [("1. Giới thiệu", 11), ("1.2 Phạm vi", 12), ("1.2.3 Chi tiết", 13), ("Điều 12. Quyền", 4), ("Chương IV", 2),
     ("PHẦN I", 1), ("Mục 2", 3), ("I. TỔNG QUAN", 5), ("Article 7 Scope", 4),
     ("2024 revenue grew strongly", None), ("1. Mua hàng hóa.", None), ("I. am a sentence", None),
     ("a plain sentence", None), ("1.1 " + "x" * 200, None)],
)
def test_numbering_rank(text, rank):
    assert xs._numbering_rank(text, 120) == rank


# ---------- regex headings ----------
def test_regex_heading_mode(fx, tmp_path):
    ex = {"type": "sections", "heading_mode": "regex", "heading_pattern": r"^\d+\.\s"}
    r, _ = run(fx["text_report"], ex, tmp_path)
    assert r["record_count"] == 4  # preamble (title + intro) + 3 numbered
    assert [p["title"] for p in r["preview"]] == ["", "1. Results", "2. Outlook"] and r["preview"][0]["level"] == 0
    assert [h["title"] for h in engine.outline(fx["text_report"], ex)["headings"]] == ["1. Results", "2. Outlook", "3. Appendix"]
    assert code_of(run, fx["text_report"], {**ex, "heading_pattern": "(unclosed"}, tmp_path) == errors.REGEX_INVALID
    assert code_of(run, fx["text_report"], {"type": "sections", "heading_mode": "regex"}, tmp_path) == errors.INVALID_CONFIG


@pytest.mark.parametrize("bad", [{"heading_mode": "magic"}, {"size_ratio": "big"}, {"max_heading_chars": 0},
                                 {"bold_headings": "yes"}, {"join_lines": 1}])
def test_invalid_sections_config(fx, tmp_path, bad):
    assert code_of(run, fx["text_report"], {"type": "sections", **bad}, tmp_path) == errors.INVALID_CONFIG


# ---------- mapping / templates / modes ----------
def test_fields_and_custom_template(fx, tmp_path):
    fields = [{"source": "title", "target": "t"}, {"source": "level", "target": "lvl", "transform": "number"},
              {"source": "word_count", "target": "n", "transform": "number"}]
    r, md = run(fx["text_report"], {"type": "sections"}, tmp_path, "{{ lvl }}|{{ t }}|{{ n }}", fields)
    assert md.splitlines()[0] == "1|Annual Report|" + str(r["preview"][0]["n"])
    assert code_of(run, fx["text_report"], {"type": "sections"}, tmp_path, "{{ nope }}", fields) == errors.TEMPLATE_RENDER
    bad = [{"source": "heading_text", "target": "x"}]
    assert code_of(run, fx["text_report"], {"type": "sections"}, tmp_path, "{{ x }}", bad) == errors.FIELD_MISSING


def test_file_per_record_names_from_titles(fx, tmp_path):
    cfg = {"extraction": {"type": "sections"}, "fields": [], "template": {"record": "{{ markdown }}"},
           "output": {"mode": "file_per_record", "filename_pattern": "{{ title }}"}}
    out = tmp_path / "stage"
    r = engine.convert(fx["text_report"], cfg, str(out))
    assert len(os.listdir(out)) == 6 == len(r["outputs"])
    assert {"1.1_Revenue.md", "Annual_Report.md"} <= set(os.listdir(out))


# ---------- failure paths still write nothing ----------
@pytest.mark.parametrize("name,code", [("scanned", errors.NO_TEXT_LAYER), ("encrypted", errors.PDF_ENCRYPTED), ("corrupt", errors.PDF_CORRUPT)])
def test_bad_pdfs_for_sections(fx, tmp_path, name, code):
    out = tmp_path / "o.md"
    cfg = {"extraction": {"type": "sections"}, "fields": [], "template": {"record": "{{ markdown }}"}}
    assert code_of(engine.convert, fx[name], cfg, str(out)) == code
    assert not out.exists()


def test_table_rule_on_text_pdf_is_clear(fx, tmp_path):
    cfg = {"extraction": {"type": "table", "table_strategy": "lines"}, "fields": [], "template": {"record": "x"}}
    assert code_of(engine.convert, fx["text_report"], cfg, str(tmp_path / "o.md")) == errors.TABLE_NOT_FOUND


# ---------- encoding guard ----------
class _Page:
    def __init__(self, texts):
        self.chars = [{"text": t} for t in texts]


def test_cid_ratio_detects_undecodable_fonts():
    assert cid_ratio(_Page(["a", "b", "(cid:1)", "(cid:2)"])) == 0.5
    assert cid_ratio(_Page(["a", "b", "c", "(cid:127)"])) == 0.25
    assert cid_ratio(_Page([])) == 0.0


def test_broken_encoding_raises(monkeypatch, fx, tmp_path):
    monkeypatch.setattr("pdf2md.pdfio.cid_ratio", lambda page: 0.9)
    cfg = {"extraction": {"type": "sections"}, "fields": [], "template": {"record": "{{ markdown }}"}}
    assert code_of(engine.convert, fx["text_report"], cfg, str(tmp_path / "o.md")) == errors.TEXT_ENCODING_BROKEN


# ---------- rpc ----------
def test_rpc_outline(fx):
    import json
    r = handle(json.dumps({"id": 1, "method": "outline", "params": {"pdf_path": fx["text_report"], "rule": {"type": "sections"}}}))
    assert r["result"]["total"] == 6 and r["result"]["headings"][0]["title"] == "Annual Report"
    e = handle(json.dumps({"id": 2, "method": "outline", "params": {"pdf_path": fx["scanned"], "rule": {}}}))
    assert e["error"]["code"] == "NO_TEXT_LAYER"
    assert re.match(r"^\d+$", str(e["id"]))
