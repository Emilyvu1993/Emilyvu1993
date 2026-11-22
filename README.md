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
Fields: `title, level, heading, body, markdown, page, page_end, word_count`; `{{ markdown }}` is the ready-made default.
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
npm run tauri:dev          # needs Linux: libwebkit2gtk-4.1-dev, libgtk-3-dev, librsvg2-dev
npm run dev                # browser-only UI with the mock backend (no Rust/Python)
```

## Tests
```bash
cd sidecar && ../.venv/bin/python -m pytest -q      # engine + RPC + sections + table records + angles (129)
cd app/src-tauri && cargo test                      # store, atomic save, sidecar, full flows (16)
cd app && npm test && npm run typecheck             # UI utils
cd app && npm run dev & node e2e/ui-flow.mjs        # UI flows (needs playwright)
```

## Release build
`npm run tauri:build` (per OS) freezes the sidecar with PyInstaller into `src-tauri/binaries/` and bundles it.
