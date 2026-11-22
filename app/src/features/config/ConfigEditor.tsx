import { useStore } from "../../store";
import { ExtractionForm } from "./ExtractionForm";
import { FieldMapper } from "./FieldMapper";
import { TemplateEditor } from "./TemplateEditor";

export function ConfigEditor({ fileId }: { fileId: string }) {
  const draft = useStore((s) => s.drafts[fileId]);
  const configs = useStore((s) => s.configs);
  const inspect = useStore((s) => s.inspect[fileId]);
  const busy = useStore((s) => s.busy);
  const st = useStore.getState();
  if (!draft) return null;

  const update = (fn: Parameters<typeof st.updateDraft>[1]) => st.updateDraft(fileId, fn);
  const saved = configs.find((c) => c.id === draft.id);
  const detectedColumns = inspect && "tables" in inspect ? [...new Set(inspect.tables.flatMap((t) => t.columns))] : [];

  return (
    <div className="editor">
      <div className="config-bar card">
        <label className="grow">Config
          <select value={draft.id ?? ""} onChange={(e) => (e.target.value ? st.loadConfig(fileId, e.target.value) : st.newConfig(fileId))}>
            <option value="">— Unsaved config —</option>
            {configs.map((c) => <option key={c.id} value={c.id}>{c.name} · v{c.version}</option>)}
          </select>
        </label>
        <label className="grow">Name
          <input value={draft.name} onChange={(e) => update((d) => ({ ...d, name: e.target.value }))} />
        </label>
        <div className="row end">
          <button className="btn" onClick={() => st.saveConfig(fileId, false)}>{saved ? "Save" : "Save config"}</button>
          {saved && <button className="btn ghost" onClick={() => st.saveConfig(fileId, true)}>Save as new</button>}
          {saved && (
            <button className="btn ghost danger" onClick={() => confirm(`Delete config “${saved.name}”?`) && st.deleteConfig(fileId, saved.id)}>
              Delete
            </button>
          )}
        </div>
      </div>

      <ExtractionForm fileId={fileId} draft={draft} update={update} inspect={inspect} />
      <FieldMapper draft={draft} update={update} detectedColumns={detectedColumns} />
      <TemplateEditor draft={draft} update={update} />

      <div className="convert-bar">
        <span className="muted small">Converting never overwrites your saved .md. You review the preview first.</span>
        <button className="btn primary lg" onClick={() => st.convert(fileId)} disabled={!!busy || !draft.template.record.trim()}>
          {busy === "convert" ? "Converting…" : "Convert & preview"}
        </button>
      </div>
    </div>
  );
}
