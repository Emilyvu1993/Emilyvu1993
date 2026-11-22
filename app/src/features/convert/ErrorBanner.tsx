import { useEffect, useRef, useState } from "react";
import { errorHint } from "../../lib/errorHints";
import type { AppError } from "../../types/domain";

export function ErrorBanner({ error, onDismiss }: { error: AppError; onDismiss: () => void }) {
  const [open, setOpen] = useState(false);
  const hint = errorHint(error.code);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.scrollIntoView?.({ block: "center" }); }, [error]);
  return (
    <div className="banner error" role="alert" ref={ref}>
      <div className="banner-body">
        <div className="banner-title">
          Conversion failed <code className="code-chip">{error.code}</code>
        </div>
        <div>{error.message}</div>
        {hint && <div className="banner-hint">{hint}</div>}
        <div className="banner-keep">Your existing output file and this config were not changed.</div>
        {error.detail != null && (
          <>
            <button className="link" onClick={() => setOpen(!open)}>{open ? "Hide details" : "Show details"}</button>
            {open && <pre className="detail">{JSON.stringify(error.detail, null, 2)}</pre>}
          </>
        )}
      </div>
      <button className="icon-btn" aria-label="Dismiss error" onClick={onDismiss}>×</button>
    </div>
  );
}
