# PDF2MD Workspace

Desktop app (Tauri + React + Python sidecar) that turns **text-based PDFs** into Markdown using
**record extraction + a Jinja template**, with a top-3 preview before anything is saved.

## Extraction types
| Type | For | A record is |
|---|---|---|
| Table rows | statements, ledgers | one table row (ruled or borderless), **or one whole table** (e.g. one per month) |
| Text blocks (regex) | repeated forms, invoices | text from one start-pattern match to the next |
| **Text sections (headings)** | reports, contracts, legal text | one section: heading + its body |

Text sections detect headings **by font** (size / bold), **by numbering** (Phần/Chương/Mục/Điều, `I.`, `1.`, `1.1`…) or **by regex**.
Fields: `title, level, parent, heading, body, markdown, page, page_end, word_count` (`parent` = title of the enclosing heading, e.g. the suit of a card); `{{ markdown }}` is the ready-made default.
Options for real-world layouts: **Never a heading (regex)** drops lines such as a label repeated in every card
(`^(Is|Are) (it|he|she|they)\b.*upside down\?$`); a line that opens with a **bold label** (`Home:`, `Is he upside down?`) starts
its own paragraph; **bold/italic are kept** as `**bold**` / `*italic*` (switch off in the rule; wording is never changed).
**Keep tables and code blocks** (opt-in, for PDFs rendered from Markdown/HTML such as API specs): bordered tables become Markdown
tables (a table split by a page break is merged back, columns that are empty everywhere are dropped), boxed or monospace text becomes a
fenced code block (```json when it parses as JSON, indentation kept), and monospace words in text or cells become `code`. A monospace
identifier that the renderer wrapped in the middle of a word is joined back (`priceaffteratt` + `r` → `priceaffterattr`). Leave it off when
a table is only a page layout (e.g. image + text columns): those stay plain text. Borderless tables are not handled by this option.
Text is never translated: original language and diacritics are kept (Unicode normalised to NFC, switchable).
Limits: running headers/footers are recognised from repetition, so a **1-page** document cannot be cleaned;
PDFs whose fonts lack a Unicode map (e.g. legacy Vietnamese fonts) are rejected with `TEXT_ENCODING_BROKEN` instead of producing garbage.
Uploads: `.pdf` only, max 2 MB.

### Tables
- Strategies: `auto`, `lines` (ruled), `text` (borderless) and **`lines_text`** (ruled columns, rows taken from text; for tables with no horizontal rules; needs text reaching the last ruled column).
- **Record = one table**: each table keeps its own header and becomes one record with `title` (caption above it, e.g. `JANUARY 1994`), `page`, `row_count`, `table` (GFM), `markdown` and `rows` (loop in the template).
- **Symbol fonts** (`glyph_map`): characters of a font (matched by name part) are replaced by real text *before* extraction, so a glyph stays where it sits in the line (`10♑20'16`). A preset for Astrodienst ephemeris fonts is included; maps are plain JSON and editable.
- **Angle convention (Astrodienst only)**: `angle_format: {font, skip_columns}`, bundled with the Astrodienst preset, never with a generic glyph map.
  On pages that really use that font: `10♑20'16` → `10♑20′16″`, `27° 6` → `27°6′`, `2°R26` → `2°R26′`, `6 45 37` → `6°45′37″`
  (digits are kept, only symbols are added). `skip_columns` defaults to `Sid.t`: it is sidereal time (h m s), not an angle. Tables only.
- **Word gap**: lower it if narrow spaces vanish (`6 41 40` → `64140`).
Design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Behaviour
- Workspace holds many PDFs; exactly one is active at a time (switching is blocked during a conversion).
- Output configs (extraction rule, field mapping, template) are saved to `<workspace>/configs/` and reusable across files.
- **Convert** writes only to `.tmp/`; the UI shows the first 3 records. **Save** atomically promotes it to `output/` (previous file kept as `.bak`).
- On failure: error + hint shown, existing `output/` file untouched, config/draft kept (persisted before the run).
- Save is refused if the config changed after the preview (stale guard).

## Dev setup
```bash
python3 -m venv .venv && .venv/bin/pip install -r sidecar/requirements-dev.txt
cd app && npm install
npm run tauri:dev          # Windows: needs WebView2 (built into Windows 11)
npm run dev                # browser-only UI with the mock backend (no Rust/Python)
```

## Tests
```bash
cd sidecar && ../.venv/bin/python -m pytest -q      # engine + RPC + sections + table records + angles + tarot-style sections (153)
cd app/src-tauri && cargo test                      # store, atomic save, sidecar, full flows (16)
cd app && npm test && npm run typecheck             # UI utils
cd app && npm run dev & node e2e/ui-flow.mjs        # UI flows (needs playwright)
```

## Installers

**Windows: one setup `.exe`.** Download it from GitHub Actions (*Actions → Build desktop app → Run workflow* or push a tag such
as `v0.1.0`, then take the `windows-installer` artifact of the finished run). Users just double-click it:
- installs **for the current user only**: no administrator rights, no UAC prompt, no console window, no Python needed;
- Start-menu / desktop shortcut, uninstall from *Windows Settings → Apps*;
- WebView2 (the UI engine, built into Windows 11) is downloaded only if the PC lacks it, so that case needs Internet once.

The installer is **not code-signed**: Windows SmartScreen shows "Windows protected your PC" → *More info → Run anyway*;
some corporate antivirus products flag unsigned one-file executables (code signing is the real fix).

Before the artifact is published the workflow installs it silently on a clean Windows runner and checks that the app and the
sidecar are installed side by side, that the installed app is a **GUI** program (PE subsystem, so no console), that the
**installed** sidecar passes `sidecar/smoke_frozen.py`, that the app stays alive (a screenshot is attached as `app-window`),
and that uninstalling removes everything.

Build locally (per OS; PyInstaller does not cross-compile):
```bash
python -m pip install -r sidecar/requirements-dev.txt
cd app && npm ci
npm run tauri:build          # freezes the sidecar (sidecar/run_pdf2md.py), then bundles the app
python ../sidecar/smoke_frozen.py   # optional: check the frozen sidecar on its own
```
The sidecar is bundled as `pdf2md[.exe]` next to the app executable; `PDF2MD_SIDECAR_PROGRAM` overrides it for debugging.
