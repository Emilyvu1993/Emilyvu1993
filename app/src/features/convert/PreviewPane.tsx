import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { conversionKey } from "../../lib/configUtils";
import { useStore } from "../../store";

function cell(v: unknown): { text: string; full?: string } {
  if (Array.isArray(v)) return { text: `[${v.length} items]`, full: JSON.stringify(v).slice(0, 2000) };
  const t = v == null ? "" : String(v);
  return t.length > 80 ? { text: t.slice(0, 80) + "…", full: t } : { text: t };
}

export function PreviewPane({ fileId }: { fileId: string }) {
  const preview = useStore((s) => s.previews[fileId]);
  const draft = useStore((s) => s.drafts[fileId]);
  const busy = useStore((s) => s.busy);
  const file = useStore((s) => s.workspace?.files.find((f) => f.id === fileId));
  const [tab, setTab] = useState<"rendered" | "markdown" | "data">("rendered");
  const { saveOutput, discardPreview } = useStore.getState();

  if (busy === "convert") {
    return <section className="preview"><div className="empty"><div className="spinner" aria-hidden />Converting…</div></section>;
  }
  if (!preview) {
    return (
      <section className="preview">
        <div className="empty">
          <div className="empty-title">No preview yet</div>
          <p className="muted small">Set up the config, then click <b>Convert &amp; preview</b>. You'll see the first 3 records before anything is saved.</p>
          {file?.last_output_path && <p className="muted small">Last saved output: <code>{file.last_output_path}</code></p>}
        </div>
      </section>
    );
  }

  const { result } = preview.outcome;
  const stale = draft ? conversionKey(draft) !== preview.key : false;
  const cols = Object.keys(result.preview[0] ?? {}).filter((k) => !k.startsWith("_"));

  return (
    <section className="preview" aria-label="Preview">
      <div className="preview-head">
        <div>
          <div className="eyebrow">Preview · top {result.preview.length} of {result.record_count.toLocaleString()} records</div>
          <div className="preview-title">Conversion succeeded</div>
        </div>
        <div className="tabs" role="tablist">
          {(["rendered", "markdown", "data"] as const).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
              {t === "rendered" ? "Rendered" : t === "markdown" ? "Markdown" : "Data"}
            </button>
          ))}
        </div>
      </div>

      {result.warnings.length > 0 && (
        <div className="banner warn small">
          Empty values: {result.warnings.map((w) => `${w.field} (${w.count})`).join(", ")}
        </div>
      )}
      {stale && (
        <div className="banner warn small" role="status">The config changed after this preview. Convert again before saving.</div>
      )}

      <div className="preview-body">
        {tab === "rendered" && <div className="md"><Markdown remarkPlugins={[remarkGfm]}>{result.preview_md}</Markdown></div>}
        {tab === "markdown" && <pre className="md-src">{result.preview_md}</pre>}
        {tab === "data" && (
          <div className="table-wrap">
            <table className="grid">
              <thead><tr><th>#</th>{cols.map((c) => <th key={c}>{c}</th>)}<th>page</th></tr></thead>
              <tbody>
                {result.preview.map((r, i) => (
                  <tr key={i}><td>{i + 1}</td>{cols.map((c) => { const x = cell(r[c]); return <td key={c} title={x.full}>{x.text}</td>; })}<td>{String(r._page ?? "")}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="preview-actions">
        <button className="btn ghost" onClick={() => discardPreview(fileId)}>Discard</button>
        <button className="btn primary" disabled={stale || busy === "save"} onClick={() => saveOutput(fileId)}>
          {busy === "save" ? "Saving…" : `Save ${result.record_count.toLocaleString()} records to .md`}
        </button>
      </div>
    </section>
  );
}
