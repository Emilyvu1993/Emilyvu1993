# PDF2MD Workspace

Desktop app (Tauri + React + Python sidecar) that turns **text-based PDFs** into Markdown using
**record extraction + a Jinja template**, with a top-3 preview before anything is saved.
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
cd sidecar && ../.venv/bin/python -m pytest -q      # engine + RPC (28)
cd app/src-tauri && cargo test                      # store, atomic save, sidecar, full flow (14)
cd app && npm test && npm run typecheck             # UI utils
cd app && npm run dev & node e2e/ui-flow.mjs        # UI flows (needs playwright)
```

## Release build
`npm run tauri:build` (per OS) freezes the sidecar with PyInstaller into `src-tauri/binaries/` and bundles it.
