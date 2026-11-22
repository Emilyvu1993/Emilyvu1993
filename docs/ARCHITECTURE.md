# PDF → Markdown Content Workspace (Desktop App)

## Context
Greenfield repo (`/home/user/Emilyvu1993` is empty, branch `claude/funny-dirac-9i11ay`). We need a desktop content-management tool that:
- Holds a **workspace** with many uploaded PDFs, but works on **one active file** at a time.
- Turns a **text-based PDF** into Markdown with **record extraction + template**: it pulls repeating records (table rows or anchor-delimited blocks), maps their fields, and renders each record through a user-defined MD template.
- Lets the user **save and reuse output configs** (extraction rules, field mapping, template).
- On **failure**: shows the error, leaves the existing output `.md` untouched, and keeps the current config.
- On **success**: shows a **preview of the top 3 records** before the user saves.

Decisions already made: Convert only, no language translation · Text PDFs only, no OCR · Tauri + React + Python sidecar.

---

## 1. Architecture

```
┌──────────── Tauri shell (Rust) ────────────┐
│ React UI (Vite + TS)                       │
│   ├─ WorkspacePanel  (file list, 1 active) │
│   ├─ ConfigEditor    (rules/mapping/tpl)   │
│   ├─ PreviewPane     (top-3 rendered MD)   │
│   └─ ErrorBanner                           │
│        │ invoke() (Tauri commands)         │
│ Rust core: workspace FS, config store,     │
│   job runner, atomic save                  │
│        │ stdin/stdout JSON-RPC             │
└────────┼───────────────────────────────────┘
         ▼
  Python sidecar (PyInstaller binary)
    pdfplumber / PyMuPDF → extract → map → render(Jinja2)
```

**Responsibility split**
- **Rust**: everything stateful, meaning file I/O, the workspace, configs, atomic writes, and the sidecar lifecycle. It is the single source of truth.
- **Python**: a pure function `(pdf_path, config) → {records, markdown} | error`. It has no side effects and writes nothing to disk. This is what makes "failure keeps the old file" trivially true.
- **React**: state and UX only.

---

## 2. Domain model (data-first)

```ts
Workspace   { id, name, root_path, files: WorkspaceFile[], active_file_id?: string }
WorkspaceFile { id, name, pdf_path (copied into workspace/pdfs/), sha256, page_count,
                status: 'new'|'converted'|'failed', last_output_path?, last_error?,
                bound_config_id? }
OutputConfig { id, name, version, created_at, updated_at,
               extraction: ExtractionRule,
               fields: FieldMapping[],
               template: { header?: string, record: string, footer?: string },  // Jinja2
               output: { mode: 'single_file'|'file_per_record', filename_pattern } }
ExtractionRule =
  | { type:'table', pages?: '1-3,5', table_index?: number, header_row: number,
      merge_multipage: boolean }
  | { type:'block', pages?, start_pattern: regex, end_pattern?: regex,
      field_patterns: { [field]: regex(named group) } }
FieldMapping { source: string (column name | regex group), target: string,
               transform?: 'trim'|'number'|'date:<fmt>'|'upper'|'lower', default?: string }
ConvertResult { ok:true, record_count, preview: Record[3], preview_md: string,
                full_md_tmp_path } | { ok:false, code, message, detail? }
```

**Persistence layout** (per workspace folder):
```
<workspace>/
  workspace.json
  pdfs/<file_id>.pdf
  configs/<config_id>.json        # saved output configs (reusable across files)
  output/<file stem>.md           # last successful output
  .tmp/                           # conversion staging; cleared on start
```

---

## 3. Core flows

**F1 Upload**: Pick several PDFs → Rust copies each into `pdfs/`, hashes it (skips duplicates), and reads the page count through the sidecar `inspect` call → appends them to `workspace.json`.

**F2 Select active file**: Exactly one is active. Switching files keeps each file's bound config and draft. A switch is blocked while a conversion is running.

**F3 Configure**: The `inspect` RPC returns detected tables (columns and the first rows) and sample text, so the user can build the rules visually. The user picks a column or pattern, maps it to a field, and edits the Jinja template with live validation. **Save config** writes `configs/*.json` and **Load config** reads one back.

**F4 Convert (preview)**:
1. UI → `convert(file_id, config)` → Rust snapshots the config → sidecar.
2. Sidecar extracts records, maps them, renders, and returns `ConvertResult`. The full MD is written **only** to `.tmp/<job_id>.md`.
3. **Success**: the UI shows the record count, a table of the top 3 records, and the top 3 rendered as MD. Nothing touches `output/` yet.
4. **Failure**: the ErrorBanner shows the code, message, and detail. `output/` and the config stay untouched. The file status becomes `failed` and `last_error` is stored.

**F5 Save**: The user confirms → Rust atomically renames `.tmp/<job>.md` → `output/<name>.md` (write-temp + rename, with an optional `.bak` of the previous file) → status `converted`.
Save is only possible from a successful job whose config hash matches the current config, which blocks saving a stale preview.

**Error codes** (sidecar → UI):
`PDF_ENCRYPTED`, `PDF_CORRUPT`, `NO_TEXT_LAYER` (scanned PDF, out of scope), `NO_RECORDS_FOUND`, `TABLE_NOT_FOUND`, `REGEX_INVALID`, `FIELD_MISSING`, `TEMPLATE_SYNTAX`, `TEMPLATE_RENDER`, `TIMEOUT`, `SIDECAR_CRASH`.

---

## 4. Sidecar RPC contract (JSON lines over stdio)
```
→ {"id":1,"method":"inspect","params":{"pdf_path":"..."}}
← {"id":1,"result":{"page_count":12,"has_text":true,
     "tables":[{"page":2,"index":0,"columns":["Date","Desc","Amount"],"sample":[[...]]}],
     "text_sample":"..."}}
→ {"id":2,"method":"convert","params":{"pdf_path","config","out_tmp_path","preview_n":3}}
← {"id":2,"result":{ConvertResult}}  |  {"id":2,"error":{"code","message","detail"}}
```
Timeout: 120s per job, enforced by Rust. If the sidecar crashes, Rust restarts it and returns `SIDECAR_CRASH`.

---

## 5. Project structure
```
app/
  src/                      # React
    features/workspace/  WorkspacePanel.tsx, useWorkspace.ts
    features/config/     ConfigEditor.tsx, TemplateEditor.tsx (Monaco), FieldMapper.tsx
    features/convert/    PreviewPane.tsx, ErrorBanner.tsx
    lib/api.ts           # typed invoke wrappers
    types/domain.ts      # mirrors §2
  src-tauri/src/
    main.rs, commands.rs   # Tauri commands
    workspace.rs, config_store.rs, job.rs, sidecar.rs, fs_atomic.rs
sidecar/
  pdf2md/  rpc.py, inspect.py, extract_table.py, extract_block.py,
           mapping.py, render.py, errors.py
  tests/   fixtures/*.pdf, test_*.py
  build.spec  (PyInstaller)
```

**Libraries**: pdfplumber (tables), PyMuPDF (text/metadata, fast), Jinja2 (`StrictUndefined` so a missing field is an error), React + Zustand, Monaco, react-markdown, Tauri v2 (`shell` sidecar, `dialog`, `fs`).

---

## 6. Delivery phases
1. **Skeleton**: Tauri + React scaffold, Python sidecar packaged, `ping` RPC end to end.
2. **Workspace**: F1/F2 (upload many, one active), workspace.json persistence.
3. **Extraction engine (Python)**: table and block rules, mapping, rendering, error codes. Unit tests against fixtures.
4. **Config UI + store**: inspect-driven editor, save/load/duplicate configs.
5. **Convert / preview / save**: F4/F5 with tmp staging, atomic save, and the stale-preview guard.
6. **Hardening**: timeouts, crash restart, large PDFs (stream pages), packaging for Win/macOS.

---

## 7. Verification
- **Python unit tests** (`pytest sidecar/tests`): fixtures for a single-page table, a multi-page table, a block/regex statement, an encrypted PDF, a scanned PDF (→ `NO_TEXT_LAYER`), and a template with a missing field (→ `TEMPLATE_RENDER`).
- **Rust tests**: `fs_atomic` (old file survives an injected failure), config round-trip, the stale-preview guard.
- **E2E** (Playwright against `tauri dev`, or WebdriverIO + tauri-driver):
  1. Upload 3 PDFs, then select one and confirm only it is active.
  2. Build a config and save it. Restart the app and confirm the config is still there.
  3. Convert successfully: the preview shows exactly 3 records, and `output/` is unchanged until Save.
  4. Break the template and convert: the error appears, the old `output/*.md` has the same bytes as before, and the config editor still holds the user's edits.
  5. Save, then confirm `output/*.md` holds every record.

---

## Open points / pushback
- **Block/regex extraction** is where most real-world failures come from. The `inspect` RPC needs to show raw text with matches highlighted so users can debug their rules. Without it, error rates will be high.
- **Output mode**: the default is `single_file`. `file_per_record` is included in the model but can be deferred to later.
- If scanned PDFs show up later, add an OCR step (`ocrmypdf`) inside the sidecar. The contract does not change.
