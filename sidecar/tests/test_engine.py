import json
import os
from decimal import Decimal

import pytest

from pdf2md import engine, errors
from pdf2md.errors import ConvertError
from pdf2md.mapping import to_number
from pdf2md.rpc import handle


def code_of(fn, *a, **kw):
    with pytest.raises(ConvertError) as ei:
        fn(*a, **kw)
    return ei.value.code


# ---------- inspect ----------
def test_inspect_detects_table(fx):
    r = engine.inspect(fx["table_single"])
    assert r["page_count"] == 1 and r["has_text"]
    assert r["tables"][0]["columns"] == ["Date", "Description", "Amount"]
    assert r["tables"][0]["row_count"] == 5


def test_inspect_scanned_has_no_text(fx):
    assert engine.inspect(fx["scanned"])["has_text"] is False


# ---------- table ----------
def test_table_single_preview_top3(fx, table_cfg, tmp_path):
    out = tmp_path / "o.md"
    r = engine.convert(fx["table_single"], table_cfg, str(out))
    assert r["record_count"] == 5
    assert len(r["preview"]) == 3
    assert r["preview"][0] == {"date": "2026-01-02", "desc": "Payment #1", "amount": "1000.50", "_page": 1}
    full = out.read_text()
    assert full.startswith("# Transactions (5)")
    assert full.count("- **") == 5
    assert r["preview_md"].count("- **") == 3


def test_table_multipage_merges_and_drops_repeated_header(fx, table_cfg, tmp_path):
    r = engine.convert(fx["table_multi"], table_cfg, str(tmp_path / "o.md"))
    assert r["record_count"] == 7
    assert "Date" not in (tmp_path / "o.md").read_text().split("\n", 1)[1]


def test_table_page_selection(fx, table_cfg, tmp_path):
    table_cfg["extraction"]["pages"] = "2"
    assert engine.convert(fx["table_multi"], table_cfg, str(tmp_path / "o.md"))["record_count"] == 3


def test_passthrough_when_no_fields(fx, table_cfg, tmp_path):
    table_cfg["fields"] = []
    table_cfg["template"] = {"record": "{{ Date }}|{{ Amount }}"}
    r = engine.convert(fx["table_single"], table_cfg, str(tmp_path / "o.md"))
    assert r["preview"][0]["Amount"] == "1,000.50"


def test_borderless_table_auto_fallback(fx, table_cfg, tmp_path):
    r = engine.convert(fx["table_borderless"], table_cfg, str(tmp_path / "o.md"))
    assert r["record_count"] == 4 and r["preview"][0]["desc"] == "Payment #1"
    table_cfg["extraction"]["table_strategy"] = "lines"
    assert code_of(engine.convert, fx["table_borderless"], table_cfg, str(tmp_path / "o.md")) == errors.TABLE_NOT_FOUND
    assert engine.inspect(fx["table_borderless"])["tables"][0]["columns"] == ["Date", "Description", "Amount"]


# ---------- block ----------
def test_block_extraction_spans_pages(fx, block_cfg, tmp_path):
    r = engine.convert(fx["blocks"], block_cfg, str(tmp_path / "o.md"))
    assert r["record_count"] == 5
    assert r["preview"][0] == {"invoice": "INV-001", "customer": "ACME 1", "total": "250.00", "_page": 1}
    assert r["preview"][0]["customer"] == "ACME 1"  # upper() is a no-op here, but transform ran
    assert "INV-005" in (tmp_path / "o.md").read_text()


def test_match_pattern_debugger(fx):
    r = engine.match_pattern(fx["blocks"], r"Total: ([\d,.]+)")
    assert r["total"] == 5 and r["hits"][0]["groups"] == ["250.00"]


# ---------- failure paths: never write output ----------
@pytest.mark.parametrize(
    "fixture,code",
    [
        ("scanned", errors.NO_TEXT_LAYER),
        ("encrypted", errors.PDF_ENCRYPTED),
        ("corrupt", errors.PDF_CORRUPT),
    ],
)
def test_bad_pdfs(fx, table_cfg, tmp_path, fixture, code):
    out = tmp_path / "o.md"
    assert code_of(engine.convert, fx[fixture], table_cfg, str(out)) == code
    assert not out.exists() and not (tmp_path / "o.md.part").exists()


def test_missing_file(table_cfg, tmp_path):
    assert code_of(engine.convert, "/nope.pdf", table_cfg, str(tmp_path / "o.md")) == errors.PDF_NOT_FOUND


def test_template_undefined_var_fails_and_writes_nothing(fx, table_cfg, tmp_path):
    table_cfg["template"]["record"] = "{{ amount }} {{ not_a_field }}"
    out = tmp_path / "o.md"
    assert code_of(engine.convert, fx["table_single"], table_cfg, str(out)) == errors.TEMPLATE_RENDER
    assert not out.exists()


def test_template_syntax(fx, table_cfg, tmp_path):
    table_cfg["template"]["record"] = "{{ amount "
    assert code_of(engine.convert, fx["table_single"], table_cfg, str(tmp_path / "o.md")) == errors.TEMPLATE_SYNTAX


def test_existing_staging_file_untouched_on_failure(fx, table_cfg, tmp_path):
    out = tmp_path / "o.md"
    out.write_text("OLD")
    table_cfg["fields"][0]["source"] = "Nope"
    assert code_of(engine.convert, fx["table_single"], table_cfg, str(out)) == errors.FIELD_MISSING
    assert out.read_text() == "OLD"


def test_transform_failure(fx, table_cfg, tmp_path):
    table_cfg["fields"][1]["transform"] = "number"  # "Payment #1" -> not a number
    assert code_of(engine.convert, fx["table_single"], table_cfg, str(tmp_path / "o.md")) == errors.TRANSFORM_FAILED


def test_invalid_regex(fx, block_cfg, tmp_path):
    block_cfg["extraction"]["start_pattern"] = "(unclosed"
    assert code_of(engine.convert, fx["blocks"], block_cfg, str(tmp_path / "o.md")) == errors.REGEX_INVALID


def test_no_records(fx, block_cfg, tmp_path):
    block_cfg["extraction"]["start_pattern"] = r"^Receipt"
    assert code_of(engine.convert, fx["blocks"], block_cfg, str(tmp_path / "o.md")) == errors.NO_RECORDS_FOUND


def test_table_not_found(fx, table_cfg, tmp_path):
    table_cfg["extraction"]["table_strategy"] = "lines"
    assert code_of(engine.convert, fx["blocks"], table_cfg, str(tmp_path / "o.md")) == errors.TABLE_NOT_FOUND
    # auto falls back to text alignment: a "table" exists but the mapped columns don't
    table_cfg["extraction"]["table_strategy"] = "auto"
    assert code_of(engine.convert, fx["blocks"], table_cfg, str(tmp_path / "o.md")) == errors.FIELD_MISSING


def test_invalid_pages(fx, table_cfg, tmp_path):
    table_cfg["extraction"]["pages"] = "9"
    assert code_of(engine.convert, fx["table_single"], table_cfg, str(tmp_path / "o.md")) == errors.INVALID_PAGES


# ---------- output modes ----------
def test_file_per_record(fx, block_cfg, tmp_path):
    block_cfg["output"] = {"mode": "file_per_record", "filename_pattern": "{{ invoice }}"}
    out = tmp_path / "stage"
    r = engine.convert(fx["blocks"], block_cfg, str(out))
    assert sorted(os.listdir(out)) == [f"INV_00{i}.md" for i in range(1, 6)]
    assert len(r["outputs"]) == 5


# ---------- units ----------
@pytest.mark.parametrize(
    "s,eu,exp",
    [("1,234.50", False, "1234.50"), ("(1,234.50)", False, "-1234.50"),
     ("1.234,50", True, "1234.50"), ("$ 12", False, "12"), ("-7.1 VND", False, "-7.1")],
)
def test_to_number(s, eu, exp):
    assert to_number(s, eu) == Decimal(exp)


# ---------- rpc ----------
def test_rpc_roundtrip(fx, table_cfg, tmp_path):
    assert handle(json.dumps({"id": 1, "method": "ping"}))["result"]["pong"]
    r = handle(json.dumps({"id": 2, "method": "convert", "params": {
        "pdf_path": fx["table_single"], "config": table_cfg, "out_tmp_path": str(tmp_path / "x.md")}}))
    assert r["id"] == 2 and r["result"]["record_count"] == 5
    e = handle(json.dumps({"id": 3, "method": "convert", "params": {
        "pdf_path": fx["scanned"], "config": table_cfg, "out_tmp_path": str(tmp_path / "y.md")}}))
    assert e["error"]["code"] == "NO_TEXT_LAYER"
    assert handle("not json")["error"]["code"] == "RPC_BAD_REQUEST"
    assert handle(json.dumps({"id": 4, "method": "nope"}))["error"]["code"] == "RPC_BAD_REQUEST"
