#!/usr/bin/env python3
"""Smoke test for the FROZEN sidecar executable, driven exactly like the Rust client does
(JSON lines over stdio, UTF-8 forced through PYTHONIOENCODING). Exits non-zero on any failure, so a broken
installer is never published.

    python sidecar/smoke_frozen.py [path/to/pdf2md[.exe]]

Needs reportlab (sidecar/requirements-dev.txt) only to generate the test PDFs.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_EXE = HERE / "dist" / ("pdf2md.exe" if os.name == "nt" else "pdf2md")
checks = 0


def fail(msg: str) -> "None":
    print(f"SMOKE FAILED: {msg}", file=sys.stderr)
    sys.exit(1)


def check(cond: bool, msg: str) -> None:
    global checks
    if not cond:
        fail(msg)
    checks += 1
    print(f"  ok  {msg}")


def make_pdfs(d: Path) -> dict[str, Path]:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle

    h = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=16, leading=20, spaceBefore=8, spaceAfter=6)
    p = ParagraphStyle("p", fontName="Helvetica", fontSize=10, leading=13, spaceAfter=8)
    body = "Plain prose about the topic, long enough to wrap onto more than one line of the page. " * 3
    text = d / "text.pdf"
    SimpleDocTemplate(str(text), pagesize=A4).build([
        Paragraph("1. Overview", h), Paragraph(body, p), Paragraph("2. Details", h), Paragraph(body, p), PageBreak(),
        Paragraph("3. Findings", h), Paragraph(body, p)])
    tab = d / "table.pdf"
    t = Table([["Date", "Description", "Amount"]] + [[f"0{i}/01/2026", f"Item {i}", f"{i * 100:,}.00"] for i in range(1, 6)])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    SimpleDocTemplate(str(tab), pagesize=A4).build([t])
    return {"text": text, "table": tab}


class Rpc:
    def __init__(self, exe: Path) -> None:
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}   # what the Rust client sets
        self.p = subprocess.Popen([str(exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.watchdog = threading.Timer(300, self.p.kill)                              # hard stop: never hang CI
        self.watchdog.daemon = True                                                    # must not keep the interpreter alive
        self.watchdog.start()
        self.n = 0

    def call(self, method: str, **params):
        self.n += 1
        self.p.stdin.write((json.dumps({"id": self.n, "method": method, "params": params}, ensure_ascii=False) + "\n").encode("utf-8"))
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line:
            fail(f"sidecar exited during '{method}': {self.p.stderr.read().decode('utf-8', 'replace')[-1500:]}")
        try:
            r = json.loads(line.decode("utf-8"))
        except ValueError:
            fail(f"'{method}': sidecar wrote something that is not JSON: {line[:200]!r}")
        check(r.get("id") == self.n, f"{method}: response id matches")
        return r

    def close(self) -> None:
        self.watchdog.cancel()
        try:
            self.p.stdin.close()
            self.p.wait(timeout=10)
        except Exception:  # noqa: BLE001
            self.p.kill()


def main() -> None:
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_EXE
    if not exe.is_file():
        fail(f"executable not found: {exe}")
    print(f"frozen sidecar: {exe} ({exe.stat().st_size / 1_048_576:.1f} MB)")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "tài liệu"                      # non-ASCII + space: the UTF-8 / path round trip
        work.mkdir()
        pdfs = make_pdfs(work)
        rpc = Rpc(exe)
        try:
            r = rpc.call("ping")
            check(r.get("result", {}).get("pong") is True, "ping")

            r = rpc.call("inspect", pdf_path=str(pdfs["text"]))["result"]
            check(r["page_count"] == 2 and r["has_text"], "inspect text PDF (2 pages, has text)")
            r = rpc.call("inspect", pdf_path=str(pdfs["table"]))["result"]
            check(r["tables"] and r["tables"][0]["columns"] == ["Date", "Description", "Amount"], "inspect finds the table columns")

            out = work / "đầu ra.md"
            cfg = {"extraction": {"type": "sections"}, "fields": [], "output": {"mode": "single_file"},
                   "template": {"header": "Báo cáo tiếng Việt – đã kiểm tra\n\n", "record": "{{ markdown }}\n"}}
            r = rpc.call("convert", pdf_path=str(pdfs["text"]), config=cfg, out_tmp_path=str(out), preview_n=3)["result"]
            check(r["record_count"] == 3 and [x["title"] for x in r["preview"]] == ["1. Overview", "2. Details", "3. Findings"],
                  "convert sections: 3 records, top-3 preview")
            md = out.read_text(encoding="utf-8")
            check(md.startswith("Báo cáo tiếng Việt – đã kiểm tra") and "# 1. Overview" in md, "UTF-8 config and path survive the round trip")

            cfg = {"extraction": {"type": "table", "table_strategy": "lines", "record_mode": "table"}, "fields": [],
                   "output": {"mode": "single_file"}, "template": {"record": "{{ markdown }}\n"}}
            r = rpc.call("convert", pdf_path=str(pdfs["table"]), config=cfg, out_tmp_path=str(work / "t.md"))["result"]
            check(r["record_count"] == 1 and r["preview"][0]["row_count"] == 5, "convert table: one record per table, 5 rows")

            e = rpc.call("convert", pdf_path=str(work / "missing.pdf"), config=cfg, out_tmp_path=str(work / "x.md"))
            check(e.get("error", {}).get("code") == "PDF_NOT_FOUND", "errors come back as coded errors")
            check(not (work / "x.md").exists(), "a failed conversion writes nothing")
        finally:
            rpc.close()
    print(f"SMOKE OK ({checks} checks)")


if __name__ == "__main__":
    main()
