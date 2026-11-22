import { useStore } from "../../store";
import type { WorkspaceFile } from "../../types/domain";

const STATUS_LABEL: Record<WorkspaceFile["status"], string> = { new: "New", converted: "Saved", failed: "Failed" };

function fmtSize(b: number) {
  return b > 1_048_576 ? `${(b / 1_048_576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`;
}

export function WorkspacePanel() {
  const ws = useStore((s) => s.workspace)!;
  const busy = useStore((s) => s.busy);
  const { addFiles, selectFile, removeFile, openWorkspace } = useStore.getState();

  return (
    <aside className="sidebar" aria-label="Workspace files">
      <div className="sidebar-head">
        <div>
          <div className="eyebrow">Workspace</div>
          <div className="ws-name" title={ws.name}>{ws.name}</div>
        </div>
        <button className="btn ghost sm" onClick={() => openWorkspace()} title="Open another workspace">Switch</button>
      </div>

      <button className="btn primary block" onClick={addFiles} disabled={busy === "files"}>
        {busy === "files" ? "Adding…" : "+ Add PDF files"}
      </button>

      <div className="file-list" role="radiogroup" aria-label="Active file">
        {ws.files.length === 0 && <p className="muted small pad">No files yet. Add one or more PDFs; you work on one at a time.</p>}
        {ws.files.map((f) => {
          const active = f.id === ws.active_file_id;
          return (
            <div key={f.id} className={`file-item ${active ? "active" : ""}`}>
              <button
                role="radio"
                aria-checked={active}
                className="file-main"
                onClick={() => !active && selectFile(f.id)}
                disabled={busy === "convert" && !active}
                title={busy === "convert" && !active ? "Conversion running" : f.name}
              >
                <span className="file-icon" aria-hidden>PDF</span>
                <span className="file-text">
                  <span className="file-name">{f.name}</span>
                  <span className="file-meta">
                    <span className={`badge ${f.status}`}>{STATUS_LABEL[f.status]}</span>
                    {fmtSize(f.size_bytes)}
                  </span>
                </span>
              </button>
              <button
                className="icon-btn"
                aria-label={`Remove ${f.name}`}
                onClick={() => confirm(`Remove “${f.name}” from the workspace? Saved Markdown output is kept.`) && removeFile(f.id)}
                disabled={busy === "convert"}
              >×</button>
            </div>
          );
        })}
      </div>
      <div className="sidebar-foot muted small">{ws.files.length} file{ws.files.length === 1 ? "" : "s"} · one active at a time</div>
    </aside>
  );
}
