// In-memory stand-in for the Tauri backend so the UI can run in a plain browser
// (design review, Playwright). Behaviour mirrors service.rs at a coarse level.
import type {
  AppError, ConvertOutcome, FieldMapping, InspectResult, OutlineResult, OutputConfig, OutputConfigDraft, Workspace, WorkspaceFile,
} from "../types/domain";
import { conversionKey } from "./configUtils";

type Rec = Record<string, string>;

const TABLE_ROWS: Rec[] = Array.from({ length: 42 }, (_, i) => ({
  Date: `${String((i % 28) + 1).padStart(2, "0")}/10/2026`,
  Description: ["Salary credit", "Card payment – Coffee", "Transfer to savings", "Utility bill", "ATM withdrawal"][i % 5],
  Amount: `${((i + 1) * 137_250).toLocaleString("en-US")}.00`,
  Balance: `${(50_000_000 - i * 91_000).toLocaleString("en-US")}.00`,
}));
const BLOCK_RECS: Rec[] = Array.from({ length: 12 }, (_, i) => ({
  invoice: `INV-${String(i + 1).padStart(4, "0")}`,
  customer: ["ACME Co.", "Globex Ltd", "Initech JSC"][i % 3],
  total: `${((i + 1) * 2_150_000).toLocaleString("en-US")}`,
  _raw: `Invoice No: INV-${String(i + 1).padStart(4, "0")}\nCustomer: …`,
}));

const KIND: Record<string, "table" | "block" | "scanned" | "text"> = {
  "bank-statement-oct.pdf": "table", "invoices-q3.pdf": "block", "scanned-receipt.pdf": "scanned", "annual-report.pdf": "text",
};

// Text document: headings (size 18/13 = level 1/2, 10pt bold = "bold" heading, numbered like legal text)
const DOC_HEADINGS = [
  { title: "Tổng quan", level: 1, size: 18, bold: true, page: 1 }, { title: "Bối cảnh thị trường", level: 2, size: 13, bold: true, page: 1 },
  { title: "Kết quả kinh doanh", level: 1, size: 18, bold: true, page: 2 }, { title: "Doanh thu", level: 2, size: 13, bold: true, page: 2 },
  { title: "Chi phí", level: 2, size: 13, bold: true, page: 3 }, { title: "Rủi ro và triển vọng", level: 1, size: 18, bold: true, page: 4 },
  { title: "Ghi chú", level: 2, size: 10, bold: true, page: 5 },
];
const NUMBERED = ["Chương I QUY ĐỊNH CHUNG", "Điều 1. Phạm vi điều chỉnh", "Điều 2. Đối tượng áp dụng", "Chương II QUYỀN VÀ NGHĨA VỤ"];
const VI = "Nội dung giữ nguyên ngôn ngữ gốc của tài liệu, không dịch. ";

function mockOutline(rule: Record<string, any>): OutlineResult {
  const font_sizes = [{ size: 10, chars: 8200, bold_chars: 140 }, { size: 13, chars: 220, bold_chars: 220 }, { size: 18, chars: 120, bold_chars: 120 }];
  let heads: { title: string; level: number; page: number; size: number }[];
  if (rule.heading_mode === "numbering") {
    heads = NUMBERED.map((t, i) => ({ title: t, level: t.startsWith("Chương") ? 1 : 2, page: 1 + (i > 2 ? 1 : 0), size: 11 }));
  } else if (rule.heading_mode === "regex") {
    let rx: RegExp;
    try { rx = new RegExp(rule.heading_pattern || "(?!)"); } catch (e) { throw err("REGEX_INVALID", `Invalid regex in extraction.heading_pattern: ${(e as Error).message}`); }
    heads = DOC_HEADINGS.filter((h) => rx.test(h.title)).map((h) => ({ title: h.title, level: 1, page: h.page, size: h.size }));
  } else {
    const ratio = Number(rule.size_ratio ?? 1.15);
    heads = DOC_HEADINGS.filter((h) => h.size >= 10 * ratio || (rule.bold_headings && h.bold))
      .map((h) => ({ title: h.title, level: h.level, page: h.page, size: h.size }));
  }
  return { body_size: 10, total: heads.length, headings: heads, font_sizes };
}

const state = {
  ws: null as Workspace | null,
  configs: new Map<string, OutputConfig>(),
  jobs: new Map<string, { fileId: string; key: string; md: string }>(),
  outputs: new Map<string, string>(),
  busy: false,
};

const err = (code: string, message: string, detail?: unknown): AppError => ({ code, message, detail });
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));
const uid = () => crypto.randomUUID();
const ws = () => { if (!state.ws) throw err("NO_WORKSPACE", "Open or create a workspace first"); return state.ws; };
const file = (id: string) => {
  const f = ws().files.find((x) => x.id === id);
  if (!f) throw err("FILE_NOT_IN_WORKSPACE", `File ${id} is not in this workspace`);
  return f;
};
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));

function transform(v: string | undefined, t?: string): string {
  if (v == null) return "";
  if (!t || t === "trim") return v.trim();
  if (t === "upper") return v.toUpperCase();
  if (t === "lower") return v.toLowerCase();
  if (t.startsWith("number")) {
    const n = v.replace(/,/g, "");
    if (!/^-?\d+(\.\d+)?$/.test(n)) throw err("TRANSFORM_FAILED", `Cannot apply '${t}' to '${v}'`);
    return n;
  }
  return v;
}

function render(tpl: string, ctx: Record<string, string>, part: string, i?: number): string {
  const s = tpl.replace(/\{\{\s*(\w+)\s*(\|\s*md\s*)?\}\}/g, (_, name: string, md?: string) => {
    if (!(name in ctx)) {
      throw err("TEMPLATE_RENDER", `Template '${part}': '${name}' is undefined${i != null ? ` (record ${i + 1})` : ""}`,
        { part, record_index: i ?? null, available_fields: Object.keys(ctx).sort() });
    }
    return md ? String(ctx[name]).replace(/\|/g, "\\|") : String(ctx[name]);
  });
  if (/\{\{|\{%/.test(s)) throw err("TEMPLATE_SYNTAX", `Template '${part}' syntax error`, { part });
  return s;
}

function convert(fileId: string, cfg: OutputConfigDraft): ConvertOutcome {
  const f = file(fileId);
  const kind = KIND[f.name] ?? "table";
  if (kind === "scanned") throw err("NO_TEXT_LAYER", "No selectable text found (scanned/image PDF is not supported)");
  if (!cfg.template.record.trim()) throw err("INVALID_CONFIG", "'template.record' must be a non-empty string");
  const type = cfg.extraction.type;
  let raw: Rec[];
  if (type === "sections") {
    const o = mockOutline(cfg.extraction as unknown as Record<string, unknown>);
    if (kind !== "text" || o.total === 0) {
      throw err("NO_RECORDS_FOUND", "No headings detected with the current settings",
        { body_font_size: o.body_size, font_sizes: o.font_sizes, hint: "Lower size_ratio, enable bold headings, or switch heading_mode" });
    }
    raw = o.headings.map((h, i) => {
      const body = VI.repeat(3 + (i % 3));
      const heading = `${"#".repeat(h.level)} ${h.title}`;
      return { title: h.title, level: String(h.level), heading, body, markdown: `${heading}\n\n${body.trim()}`, page: String(h.page),
        page_end: String(h.page), word_count: String(body.split(/\s+/).filter(Boolean).length) };
    });
  } else if (kind === "text") {
    throw type === "table" ? err("TABLE_NOT_FOUND", "No table detected on the selected pages") : err("NO_RECORDS_FOUND", "start_pattern matched nothing on the selected pages");
  } else {
    if (type !== (kind === "table" ? "table" : "block")) {
      throw kind === "table"
        ? err("NO_RECORDS_FOUND", "start_pattern matched nothing on the selected pages")
        : err("TABLE_NOT_FOUND", "No table detected on the selected pages");
    }
    raw = kind === "table" ? TABLE_ROWS : BLOCK_RECS;
  }
  const cols = Object.keys(raw[0]);
  const fields: FieldMapping[] = cfg.fields.length ? cfg.fields : cols.map((c) => ({ source: c, target: c }));
  const missing = fields.filter((m) => !cols.includes(m.source) && m.source !== "_page").map((m) => m.source);
  if (missing.length) throw err("FIELD_MISSING", `Source field(s) not found: ${missing.join(", ")}`, { missing, available: cols });
  const recs = raw.map((r, i) => {
    const o: Record<string, string> = {};
    for (const m of fields) {
      try { o[m.target] = transform(m.source === "_page" ? "1" : r[m.source], m.transform); }
      catch (e) { throw { ...(e as AppError), message: `Record ${i + 1}: ${(e as AppError).message}` }; }
    }
    return o;
  });
  // record_mode "table": one record per table (the mock splits the statement into two "months")
  const grouped = kind === "table" && type === "table" && (cfg.extraction as { record_mode?: string }).record_mode === "table";
  const esc = (v: string) => v.replace(/\|/g, "\\|");
  const keys = fields.map((m) => m.target);
  const out: Record<string, string>[] = grouped
    ? [recs.slice(0, 21), recs.slice(21)].map((g, n) => {
        const title = n === 0 ? "OCTOBER 2026 00:00 UT" : "NOVEMBER 2026 00:00 UT";
        const table = [`| ${keys.map(esc).join(" | ")} |`, `|${keys.map(() => " --- ").join("|")}|`,
          ...g.map((r) => `| ${keys.map((k) => esc(r[k] ?? "")).join(" | ")} |`)].join("\n");
        return { title, page: String(n + 1), row_count: String(g.length), table, markdown: `## ${title}\n\n${table}`, rows: JSON.stringify(g) };
      })
    : recs;
  const meta = { source_file: f.name, count: String(out.length) };
  const header = cfg.template.header ? render(cfg.template.header, meta, "header") : "";
  const bodies = out.map((r, i) => render(cfg.template.record, { ...r, index: String(i + 1) }, "record", i));
  const footer = cfg.template.footer ? render(cfg.template.footer, meta, "footer") : "";
  const sep = cfg.template.separator ?? "\n";
  const nl = (s: string) => (s && !s.endsWith("\n") ? s + "\n" : s);
  const job_id = uid();
  state.jobs.set(job_id, { fileId, key: conversionKey(cfg), md: nl(header) + bodies.join(sep) + (footer ? "\n" + footer : "") });
  const empty = grouped ? [] : fields.map((m) => ({ code: "EMPTY_VALUES", field: m.target, count: out.filter((r) => !r[m.target]).length }))
    .filter((w) => w.count);
  return {
    job_id, config_hash: conversionKey(cfg),
    result: {
      ok: true, record_count: out.length, columns: cols, preview: out.slice(0, 3).map((r) => ({ ...r, _page: 1 })),
      preview_md: nl(header) + bodies.slice(0, 3).join(sep), full_md_tmp_path: `.tmp/${job_id}.md`,
      outputs: [`.tmp/${job_id}.md`], warnings: empty,
    },
  };
}

const INSPECT: Record<string, InspectResult> = {
  text: { page_count: 6, pages_scanned: 5, has_text: true, tables: [], text_sample: "Tổng quan\nBáo cáo thường niên năm 2026 …\nKết quả kinh doanh …" },
  table: {
    page_count: 4, pages_scanned: 4, has_text: true, text_sample: "Statement of account – October 2026\n…",
    tables: [{ page: 1, index: 0, columns: Object.keys(TABLE_ROWS[0]), row_count: 14, sample: TABLE_ROWS.slice(0, 3).map(Object.values) }],
  },
  block: {
    page_count: 3, pages_scanned: 3, has_text: true, tables: [],
    text_sample: BLOCK_RECS.slice(0, 4).map((r) => `Invoice No: ${r.invoice}\nCustomer: ${r.customer}\nTotal: ${r.total} VND\n----`).join("\n"),
  },
  scanned: { page_count: 1, pages_scanned: 1, has_text: false, tables: [], text_sample: "" },
};

export async function mockInvoke<T>(cmd: string, a: Record<string, any> = {}): Promise<T> {
  await delay(cmd === "convert" ? 700 : 60);
  const r = ((): unknown => {
    switch (cmd) {
      case "last_workspace_path": return null;
      case "open_workspace":
        state.ws ??= { schema_version: 1, id: uid(), name: "Finance content", files: [], active_file_id: null };
        return clone(state.ws);
      case "get_workspace": return clone(ws());
      case "add_files": {
        const w = ws(); const added: string[] = []; const skipped: string[] = []; const rejected: AppError[] = [];
        for (const p of a.paths as string[]) {
          const name = p.split("/").pop()!;
          if (!/\.pdf$/i.test(name)) { rejected.push(err("NOT_A_PDF", `${name}: only .pdf files are accepted`)); continue; }
          if (w.files.some((f) => f.name === name)) { skipped.push(p); continue; }
          const f: WorkspaceFile = { id: uid(), name, pdf_path: `pdfs/${name}`, sha256: name, size_bytes: 120_000 + name.length * 9_000,
            added_at: new Date().toISOString(), status: "new" };
          w.files.push(f); added.push(f.id);
        }
        w.active_file_id ??= added[0] ?? null;
        return { report: { added, skipped_duplicates: skipped, rejected }, workspace: clone(w) };
      }
      case "remove_file": {
        const w = ws(); w.files = w.files.filter((f) => f.id !== a.fileId);
        if (w.active_file_id === a.fileId) w.active_file_id = w.files[0]?.id ?? null;
        return clone(w);
      }
      case "set_active_file":
        if (state.busy) throw err("BUSY", "Wait for the running conversion to finish before switching files");
        file(a.fileId); ws().active_file_id = a.fileId; return clone(ws());
      case "save_draft": file(a.fileId).draft_config = clone(a.draft); return null;
      case "bind_config": file(a.fileId).bound_config_id = a.configId; return clone(file(a.fileId));
      case "list_configs": return [...state.configs.values()].sort((x, y) => y.updated_at.localeCompare(x.updated_at));
      case "save_config": {
        const now = new Date().toISOString();
        const old = a.config.id ? state.configs.get(a.config.id) : undefined;
        const c: OutputConfig = { ...clone(a.config), id: old?.id ?? uid(), version: (old?.version ?? 0) + 1,
          created_at: old?.created_at ?? now, updated_at: now };
        state.configs.set(c.id, c); return c;
      }
      case "delete_config": state.configs.delete(a.configId); return null;
      case "inspect_file": return INSPECT[KIND[file(a.fileId).name] ?? "table"];
      case "match_pattern": {
        let rx: RegExp;
        try { rx = new RegExp(String(a.pattern).replace(/\(\?P</g, "(?<"), "gm"); }
        catch (e) { throw err("REGEX_INVALID", `Invalid regex in pattern: ${(e as Error).message}`); }
        const text = INSPECT.block.text_sample;
        const hits = [...text.matchAll(rx)].slice(0, 20).map((m) => ({ page: 1, match: m[0], groups: m.groups ?? m.slice(1),
          context: text.slice(Math.max(0, m.index! - 40), m.index! + m[0].length + 40) }));
        return { total: hits.length, hits };
      }
      case "outline_file": {
        if (KIND[file(a.fileId).name] === "scanned") throw err("NO_TEXT_LAYER", "No selectable text found (scanned/image PDF is not supported)");
        const o = mockOutline(a.rule);
        return KIND[file(a.fileId).name] === "text" ? o : { ...o, total: 0, headings: [] };
      }
      case "validate_config": return { valid: true };
      case "convert": {
        if (state.busy) throw err("BUSY", "A conversion is already running");
        file(a.fileId).draft_config = clone(a.config);
        try { return convert(a.fileId, a.config); }
        catch (e) {
          const f = file(a.fileId); const ae = e as AppError;
          f.status = "failed"; f.last_error = { code: ae.code, message: ae.message, at: new Date().toISOString() };
          throw e;
        }
      }
      case "save_output": {
        const j = state.jobs.get(a.jobId); state.jobs.delete(a.jobId);
        if (!j) throw err("JOB_NOT_FOUND", "Preview expired. Convert again.");
        if (j.key !== conversionKey(a.config)) throw err("STALE_PREVIEW", "Config changed after the preview. Convert again before saving.");
        const f = file(j.fileId); const out = `output/${f.name.replace(/\.pdf$/i, "")}.md`;
        const had = state.outputs.has(out); state.outputs.set(out, j.md);
        Object.assign(f, { status: "converted", last_output_path: out, last_error: null, bound_config_id: a.config.id ?? f.bound_config_id });
        return { output_path: `/mock/workspace/${out}`, backup_path: had ? `/mock/workspace/${out}.bak` : null, file: clone(f) };
      }
      case "discard_preview": state.jobs.delete(a.jobId); return null;
      default: throw err("RPC_BAD_REQUEST", `mock: unknown command ${cmd}`);
    }
  })();
  return r as T;
}
