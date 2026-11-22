import { useEffect } from "react";
import { ConfigEditor } from "./features/config/ConfigEditor";
import { ErrorBanner } from "./features/convert/ErrorBanner";
import { PreviewPane } from "./features/convert/PreviewPane";
import { WorkspacePanel } from "./features/workspace/WorkspacePanel";
import { inTauri } from "./lib/api";
import { useActiveFile, useStore } from "./store";

export default function App() {
  const ws = useStore((s) => s.workspace);
  const notice = useStore((s) => s.notice);
  const active = useActiveFile();
  const error = useStore((s) => (active ? s.errors[active.id] : undefined));
  const st = useStore.getState();

  useEffect(() => { void st.init(); }, []);
  useEffect(() => {
    if (!notice) return;
    const h = setTimeout(() => st.setNotice(null), 5000);
    return () => clearTimeout(h);
  }, [notice]);

  return (
    <div className="app">
      {!inTauri && <div className="mock-strip">Browser preview · mock backend</div>}
      {!ws ? (
        <main className="welcome">
          <div className="welcome-card">
            <div className="logo" aria-hidden>MD</div>
            <h1>PDF → Markdown workspace</h1>
            <p className="muted">Pull repeating records out of text-based PDFs, shape them with a template, preview, then save.</p>
            <button className="btn primary lg" onClick={() => st.openWorkspace()}>Open or create workspace folder</button>
          </div>
        </main>
      ) : (
        <div className="layout">
          <WorkspacePanel />
          {active ? (
            <>
              <main className="main" aria-label={`Editing ${active.name}`}>
                <header className="file-header">
                  <div>
                    <div className="eyebrow">Active file</div>
                    <h1 className="file-title">{active.name}</h1>
                  </div>
                  {active.last_output_path && <code className="muted small">→ {active.last_output_path}</code>}
                </header>
                {error && <ErrorBanner error={error} onDismiss={() => st.dismissError(active.id)} />}
                {!error && active.status === "failed" && active.last_error && (
                  <div className="banner warn small">Last attempt failed: {active.last_error.code}: {active.last_error.message}</div>
                )}
                <ConfigEditor fileId={active.id} />
              </main>
              <PreviewPane fileId={active.id} />
            </>
          ) : (
            <main className="main empty"><div className="empty-title">Add PDF files to get started</div></main>
          )}
        </div>
      )}
      {notice && <div className={`toast ${notice.kind}`} role="status" onClick={() => st.setNotice(null)}>{notice.text}</div>}
    </div>
  );
}
