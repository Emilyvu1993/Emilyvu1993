"""Heading-based section extraction for text documents (no tables needed).

Pipeline: PDF lines (+font size/bold) -> drop running headers/footers -> detect headings
(font | numbering | regex) -> group lines into sections -> build paragraphs -> records.

Text is never translated or reworded. Only whitespace/line-wrap is normalised, bullet glyphs
become "- ", and (optionally) Unicode is normalised to NFC so Vietnamese diacritics are stable.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from .config import compile_regex
from .errors import NO_RECORDS_FOUND, ConvertError
from .pdfio import apply_glyph_map, release

COLUMNS = ["title", "level", "parent", "heading", "body", "markdown", "page", "page_end", "word_count"]
MAX_LEVEL = 6

BOLD_RE = re.compile(r"(?i)bold|black|heavy|semibold|demi|[-,.]bd\b|\bbd\b")
ITALIC_RE = re.compile(r"(?i)italic|oblique")
WORD_RE = re.compile(r"[^\W\d_]{2,}")  # a heading contains at least one real word (not lone symbols/letters)
PAGE_NUM_RE = re.compile(r"(?i)^\W*(?:trang|page|p\.)?\s*\d+(?:\s*(?:/|of|trên)\s*\d+)?\W*$")
# bullet glyphs often have no Unicode mapping -> pdfminer emits "(cid:N)"
BULLET_RE = re.compile(r"^\s*(?:[•●▪◦·‣]|\(cid:\d+\))\s*")
NOT_HEADING_END = (".", ";", ",")

# (regex, rank). Lower rank = higher in the hierarchy. Vietnamese legal: Phần > Chương > Mục > Điều.
KEYWORD_RULES = [
    (re.compile(r"^(?:PHẦN|Phần|PART|Part)\s+(?:[IVXLCDM]+|\d+)\b"), 1),
    (re.compile(r"^(?:CHƯƠNG|Chương|CHAPTER|Chapter)\s+(?:[IVXLCDM]+|\d+)\b"), 2),
    (re.compile(r"^(?:MỤC|Mục|SECTION|Section)\s+(?:[IVXLCDM]+|\d+)\b"), 3),
    (re.compile(r"^(?:ĐIỀU|Điều|ARTICLE|Article)\s+\d+"), 4),
]
ROMAN_RE = re.compile(r"^([IVX]+)\.\s+(\S)")
DECIMAL_RE = re.compile(r"^(\d+(?:\.\d+)*)([.)])?\s+\S")


@dataclass
class Line:
    text: str
    page: int
    top: float
    bottom: float
    size: float
    bold: bool
    page_height: float
    kind: tuple | None = None  # set when the line is a heading
    runs: list = field(default_factory=list)  # [(text, bold, italic)] in reading order; [] = unstyled

    def md(self) -> str:
        """Line text with bold/italic as Markdown; spaces stay outside the markers."""
        if not self.runs:
            return self.text
        out = []
        for t, b, i in self.runs:
            core = t.strip()
            if not core or not (b or i):
                out.append(t)
                continue
            m = "***" if b and i else "**" if b else "*"
            out.append(f"{t[:len(t) - len(t.lstrip())]}{m}{core}{m}{t[len(t.rstrip()):]}")
        return re.sub(r"\s+", " ", "".join(out)).strip()


def _styled_runs(chars: list[dict], text: str, normalize: bool) -> list[tuple[str, bool, bool]]:
    """Group a line's characters into (text, bold, italic) runs. Falls back to [] (plain text) unless the
    rebuilt text equals the line text, so emphasis can never alter the wording."""
    runs: list[list] = []
    prev: dict | None = None
    for c in chars:
        t = c.get("text", "")
        if not t:
            continue
        if t.isspace():
            if runs:
                runs[-1][0] += " "           # spaces keep the style of the text before them
        else:
            if prev is not None and not prev["text"].isspace() and c["x0"] - prev["x1"] > 0.2 * c["size"] and runs:
                runs[-1][0] += " "
            fn = c.get("fontname", "")
            b, i = bool(BOLD_RE.search(fn)), bool(ITALIC_RE.search(fn))
            if runs and runs[-1][1] == b and runs[-1][2] == i:
                runs[-1][0] += t
            else:
                runs.append([t, b, i])
        prev = c
    joined = re.sub(r"\s+", " ", "".join(r[0] for r in runs)).strip()
    if joined != text:
        return []
    out: list[tuple[str, bool, bool]] = []
    for t, b, i in runs:
        t = re.sub(r"\s+", " ", t)
        if out and out[-1][0].endswith(" ") and t.startswith(" "):
            t = t[1:]
        if normalize:
            t = unicodedata.normalize("NFC", t)
        out.append((t, b, i))
    if out:
        out[0] = (out[0][0].lstrip(), out[0][1], out[0][2])
        out[-1] = (out[-1][0].rstrip(), out[-1][1], out[-1][2])
    return [r for r in out if r[0]]


def load_lines(pdf, pages: list[int], normalize: bool = True, glyph_map: dict | None = None) -> list[Line]:
    out: list[Line] = []
    for pi in pages:
        page = pdf.pages[pi]
        apply_glyph_map(page, glyph_map)
        for ln in page.extract_text_lines(strip=True, return_chars=True):
            text = re.sub(r"\s+", " ", ln["text"]).strip()
            chars = [c for c in ln["chars"] if c.get("text", "").strip()]
            if not text or not chars:
                continue
            runs = _styled_runs(ln["chars"], text, normalize)
            if normalize:
                text = unicodedata.normalize("NFC", text)
            size = Counter(round(c["size"] * 2) / 2 for c in chars).most_common(1)[0][0]
            bold = sum(1 for c in chars if BOLD_RE.search(c.get("fontname", ""))) / len(chars) >= 0.6
            out.append(Line(text, pi + 1, ln["top"], ln["bottom"], size, bold, float(page.height), runs=runs))
        release(page)
    return out


def _in_margin(l: Line) -> bool:
    return l.top < l.page_height * 0.10 or l.bottom > l.page_height * 0.90


def _run_key(l: Line) -> str:
    return re.sub(r"\d+", "#", l.text.lower())


def running_keys(ref_lines: list[Line], n_ref_pages: int) -> set[str]:
    """Margin lines (digits ignored) that repeat on at least half of the reference pages."""
    seen: dict[str, set[int]] = {}
    for l in ref_lines:
        if _in_margin(l):
            seen.setdefault(_run_key(l), set()).add(l.page)
    return {k for k, v in seen.items() if n_ref_pages >= 2 and len(v) >= max(2, 0.5 * n_ref_pages)}


def drop_running_lines(lines: list[Line], repeated: set[str]) -> list[Line]:
    """Remove page numbers and repeated headers/footers."""
    return [l for l in lines if not (_in_margin(l) and (PAGE_NUM_RE.match(l.text) or _run_key(l) in repeated))]


def body_style(lines: list[Line]) -> tuple[float, float]:
    """(most common font size by characters, share of that text that is bold)."""
    w: Counter = Counter()
    for l in lines:
        w[l.size] += len(l.text)
    size = w.most_common(1)[0][0]
    bold = sum(len(l.text) for l in lines if l.size == size and l.bold)
    return size, bold / w[size] if w[size] else 0.0


def _numbering_rank(text: str, max_chars: int) -> int | None:
    if len(text) > max_chars:
        return None
    for rx, rank in KEYWORD_RULES:
        if rx.match(text):
            return rank
    if text.endswith(NOT_HEADING_END):
        return None  # list items / sentences, not headings
    m = ROMAN_RE.match(text)
    if m and m.group(2).isupper():
        return 5
    m = DECIMAL_RE.match(text)
    if m:
        num, suffix = m.group(1), m.group(2)
        if "." in num:
            return 10 + num.count(".") + 1
        if suffix:
            return 11
    return None


def detect_headings(lines: list[Line], rule: dict, body_size: float, body_bold: float) -> None:
    mode = rule.get("heading_mode", "font")
    max_chars = int(rule.get("max_heading_chars", 120))
    ex_pat = rule.get("heading_exclude")
    ex = compile_regex(ex_pat, "extraction.heading_exclude") if ex_pat else None
    if ex:  # lines the user says are never headings (e.g. a repeated label such as "Is it upside down?")
        lines = [l for l in lines if not ex.search(l.text)]
    if mode == "font":
        ratio = float(rule.get("size_ratio", 1.15))
        use_bold = rule.get("bold_headings", True) and body_bold < 0.5
        for l in lines:
            if len(l.text) > max_chars or not WORD_RE.search(l.text):
                continue
            big = l.size >= body_size * ratio
            bold_head = use_bold and l.bold and l.size >= body_size * 0.95 and not l.text.endswith(NOT_HEADING_END)
            if big or bold_head:
                l.kind = ("font", l.size, l.bold)
    elif mode == "numbering":
        for l in lines:
            r = _numbering_rank(l.text, max_chars)
            if r is not None:
                l.kind = ("num", r)
    else:
        rx = compile_regex(rule["heading_pattern"], "extraction.heading_pattern")
        for l in lines:
            if len(l.text) <= max_chars and rx.search(l.text):
                l.kind = ("re", 0)


def level_map(lines: list[Line]) -> dict[tuple, int]:
    kinds = {l.kind for l in lines if l.kind}
    if not kinds:
        return {}
    if next(iter(kinds))[0] == "font":
        order = sorted(kinds, key=lambda k: (-k[1], -int(k[2])))  # bigger, then bold, = higher level
    else:
        order = sorted(kinds, key=lambda k: k[1])
    return {k: min(i + 1, MAX_LEVEL) for i, k in enumerate(order)}


def _keyword_only(text: str) -> bool:
    return any(rx.match(text) for rx, _ in KEYWORD_RULES[:3]) and len(text.split()) <= 2


def _starts_label(l: Line, prev: Line | None) -> bool:
    """A line that opens with a bold label ("Home:", "Is he upside down?") followed by regular text."""
    if not l.runs or not l.runs[0][1]:
        return False
    if not any((not r[1]) and r[0].strip() for r in l.runs[1:]):
        return False                                    # entirely bold: not a label + text
    label = l.runs[0][0].strip()
    if len(label) > 60 or not label.endswith((":", "?")):
        return False
    return not (prev and prev.runs and prev.runs[-1][1] and prev.runs[-1][0].strip())  # label wrapped from above


def _paragraphs(body: list[Line], join_lines: bool, emphasis: bool = True) -> str:
    paras: list[tuple[list[str], bool]] = []
    cur: list[str] = []
    cur_bullet = False
    prev: Line | None = None
    for l in body:
        txt = l.md() if emphasis else l.text
        b = BULLET_RE.match(txt)
        if b:
            txt = "- " + txt[b.end():]
        if prev is None:
            new = False
        elif b or _starts_label(l, prev):
            new = True
        elif l.page != prev.page:
            new = prev.text.rstrip().endswith((".", "!", "?", ":", ";"))
        else:
            new = (l.top - prev.bottom) > 0.5 * max(l.size, 1.0)
        if new and cur:
            paras.append((cur, cur_bullet))
            cur, cur_bullet = [], False
        if not cur:
            cur_bullet = bool(b)
        cur.append(txt)
        prev = l
    if cur:
        paras.append((cur, cur_bullet))
    sep = " " if join_lines else "\n"
    out = ""
    prev_bullet = False
    for i, (ls, is_b) in enumerate(paras):
        text = sep.join(ls)
        out += ("" if i == 0 else ("\n" if (is_b and prev_bullet) else "\n\n")) + text
        prev_bullet = is_b
    return out


def build_sections(lines: list[Line], rule: dict) -> list[dict]:
    include_pre = rule.get("include_preamble", True)
    join = rule.get("join_lines", True)
    emphasis = rule.get("emphasis", True)
    raw: list[dict] = []
    cur: dict | None = None
    pre: list[Line] = []
    prev: Line | None = None

    for l in lines:
        if l.kind:
            if (cur and cur["open"] and prev is not None and l.kind == cur["kind"] and l.kind[0] == "font"
                    and l.page == prev.page and (l.top - prev.bottom) < 0.8 * l.size):
                cur["title"] += " " + l.text  # multi-line heading
                cur["end"] = l.page
            else:
                cur = {"title": l.text, "kind": l.kind, "page": l.page, "end": l.page, "body": [], "open": True,
                       "want_title": l.kind[0] == "num" and l.kind[1] <= 3 and _keyword_only(l.text)}
                raw.append(cur)
        elif cur is None:
            pre.append(l)
        else:
            if cur["want_title"] and cur["open"] and l.page == prev.page and len(l.text) <= 120 \
                    and (l.top - prev.bottom) < 1.5 * l.size:
                cur["title"] += " " + l.text  # "Chương I" / "QUY ĐỊNH CHUNG"
                cur["want_title"] = False
            else:
                cur["body"].append(l)
                cur["open"] = False
                cur["want_title"] = False
            cur["end"] = l.page
        prev = l

    levels = level_map(lines)
    secs: list[dict] = []
    if include_pre and pre:
        secs.append({"title": "", "level": 0, "page": pre[0].page, "end": pre[-1].page, "body": pre})
    for r in raw:
        secs.append({**r, "level": levels[r["kind"]]})

    out = []
    stack: list[tuple[int, str]] = []  # (level, title) of the open ancestors
    for s in secs:
        parent = ""
        if s["level"]:
            while stack and stack[-1][0] >= s["level"]:
                stack.pop()
            parent = stack[-1][1] if stack else ""
            stack.append((s["level"], s["title"]))
        body = _paragraphs(s["body"], join, emphasis)
        heading = f"{'#' * s['level']} {s['title']}" if s["level"] else ""
        md = "\n\n".join(x for x in (heading, body) if x)
        out.append({
            "title": s["title"], "level": s["level"], "parent": parent, "heading": heading, "body": body, "markdown": md,
            "page": s["page"], "page_end": max(s["end"], s["page"]), "word_count": len(body.split()),
            "_page": s["page"],
        })
    return out


REF_PAGES = 6  # pages sampled to recognise running headers/footers, whatever subset the user selected


def analyze(pdf, pages: list[int], rule: dict):
    norm = rule.get("normalize_unicode", True)
    ref = list(range(min(len(pdf.pages), REF_PAGES)))
    wanted = set(pages)
    lines = load_lines(pdf, sorted(wanted | set(ref)) if rule.get("skip_header_footer", True) else pages, norm, rule.get("glyph_map"))
    if rule.get("skip_header_footer", True):
        repeated = running_keys([l for l in lines if l.page - 1 in ref], len(ref))
        lines = drop_running_lines([l for l in lines if l.page - 1 in wanted], repeated)
    if not lines:
        raise ConvertError(NO_RECORDS_FOUND, "No text lines found on the selected pages")
    body_size, body_bold = body_style(lines)
    detect_headings(lines, rule, body_size, body_bold)
    return lines, body_size


def size_histogram(lines: list[Line], top: int = 8) -> list[dict]:
    c: Counter = Counter()
    b: Counter = Counter()
    for l in lines:
        c[l.size] += len(l.text)
        if l.bold:
            b[l.size] += len(l.text)
    return [{"size": s, "chars": n, "bold_chars": b[s]} for s, n in sorted(c.items(), key=lambda x: -x[1])[:top]]


def extract(pdf, pages: list[int], rule: dict) -> tuple[list[str], list[dict]]:
    lines, body_size = analyze(pdf, pages, rule)
    if not any(l.kind for l in lines):
        raise ConvertError(
            NO_RECORDS_FOUND,
            "No headings detected with the current settings",
            {"heading_mode": rule.get("heading_mode", "font"), "body_font_size": body_size,
             "font_sizes": size_histogram(lines),
             "hint": "Lower size_ratio, enable bold headings, or switch heading_mode"},
        )
    return COLUMNS, build_sections(lines, rule)


def outline(pdf, pages: list[int], rule: dict, limit: int = 60) -> dict:
    """Cheap heading preview used by the UI while tuning detection."""
    lines, body_size = analyze(pdf, pages, rule)
    levels = level_map(lines)
    heads = [{"title": l.text, "level": levels[l.kind], "page": l.page, "size": l.size} for l in lines if l.kind]
    warning = None
    if len(heads) > 25 and len(heads) > 0.2 * len(lines):
        warning = (f"{len(heads)} of {len(lines)} lines look like headings. This looks like a table or form, "
                   "not prose: use the Table rows type, or raise the heading size ratio.")
    return {"body_size": body_size, "total": len(heads), "headings": heads[:limit],
            "font_sizes": size_histogram(lines), "warning": warning}
