import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { templateFromFields, templateVariables, type TemplatePreset } from "../../lib/configUtils";
import type { AppError, OutputConfigDraft, TemplateSpec } from "../../types/domain";

type Upd = (fn: (d: OutputConfigDraft) => OutputConfigDraft) => void;

export function TemplateEditor({ draft, update }: { draft: OutputConfigDraft; update: Upd }) {
  const t = draft.template;
  const set = (p: Partial<TemplateSpec>) => update((d) => ({ ...d, template: { ...d.template, ...p } }));
  const vars = templateVariables(draft);
  const [check, setCheck] = useState<AppError | null>(null);

  // live validation (syntax + config schema) — debounced
  useEffect(() => {
    if (!t.record.trim()) { setCheck(null); return; }
    const h = setTimeout(() => {
      api.validateConfig(draft).then(() => setCheck(null)).catch((e: AppError) => setCheck(e));
    }, 400);
    return () => clearTimeout(h);
  }, [draft]);

  const insert = (v: string) => set({ record: `${t.record}{{ ${v} }}` });
  const preset = (p: TemplatePreset) => {
    if (t.record.trim() && !confirm("Replace the current template?")) return;
    set(templateFromFields(draft.fields, p));
  };

  return (
    <section className="card">
      <div className="card-head">
        <h2>3 · Markdown template</h2>
        <div className="row">
          <span className="muted small">Preset:</span>
          {(["table", "bullets", "sections"] as const).map((p) => (
            <button key={p} className="btn ghost sm" disabled={!draft.fields.length} onClick={() => preset(p)}>
              {p === "table" ? "MD table" : p === "bullets" ? "Bullet list" : "Sections"}
            </button>
          ))}
        </div>
      </div>

      <div className="vars">
        <span className="muted small">Record variables:</span>
        {(vars.length ? vars : ["(passthrough: source column names)"]).map((v) => (
          <button key={v} className="chip mono" disabled={!vars.length} onClick={() => insert(v)} title="Insert into record template">{v}</button>
        ))}
        <span className="chip mono ghost-chip">index</span>
        <span className="muted small">· Header/footer: <code>count</code>, <code>source_file</code>, <code>records</code> · filter <code>| md</code> escapes pipes</span>
      </div>

      <label><span>Header <span className="muted">(once, optional)</span></span>
        <textarea className="mono" rows={2} value={t.header ?? ""} onChange={(e) => set({ header: e.target.value })} />
      </label>
      <label><span>Record <span className="muted">(rendered for every record)</span></span>
        <textarea className={`mono ${check ? "invalid" : ""}`} rows={4} value={t.record}
          placeholder="- **{{ date }}** {{ description }}: {{ amount }}" onChange={(e) => set({ record: e.target.value })} />
      </label>
      {check && <div className="warn-text small" role="status">{check.code}: {check.message}</div>}
      <label><span>Footer <span className="muted">(once, optional)</span></span>
        <textarea className="mono" rows={2} value={t.footer ?? ""} onChange={(e) => set({ footer: e.target.value })} />
      </label>

      <div className="form-grid">
        <label>Output
          <select value={draft.output.mode} onChange={(e) => update((d) => ({ ...d, output: { ...d.output, mode: e.target.value as "single_file" } }))}>
            <option value="single_file">One .md file</option>
            <option value="file_per_record">One .md per record (folder)</option>
          </select>
        </label>
        {draft.output.mode === "file_per_record" && (
          <label>File name pattern
            <input className="mono" value={draft.output.filename_pattern ?? ""}
              onChange={(e) => update((d) => ({ ...d, output: { ...d.output, filename_pattern: e.target.value } }))} />
          </label>
        )}
      </div>
    </section>
  );
}
