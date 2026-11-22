import { availableSources, fieldsFromColumns, toIdentifier } from "../../lib/configUtils";
import type { FieldMapping, OutputConfigDraft } from "../../types/domain";

type Upd = (fn: (d: OutputConfigDraft) => OutputConfigDraft) => void;

const TRANSFORMS: { v: string; label: string }[] = [
  { v: "", label: "None" }, { v: "trim", label: "Trim" }, { v: "upper", label: "UPPER" }, { v: "lower", label: "lower" },
  { v: "number", label: "Number 1,234.56" }, { v: "number:eu", label: "Number 1.234,56" },
  { v: "date:%d/%m/%Y", label: "Date dd/mm/yyyy → ISO" }, { v: "date:%m/%d/%Y", label: "Date mm/dd/yyyy → ISO" },
];

export function FieldMapper({ draft, update, detectedColumns }: { draft: OutputConfigDraft; update: Upd; detectedColumns: string[] }) {
  const sources = availableSources(draft, detectedColumns);
  const set = (fields: FieldMapping[]) => update((d) => ({ ...d, fields }));
  const patch = (i: number, p: Partial<FieldMapping>) => set(draft.fields.map((f, j) => (j === i ? { ...f, ...p } : f)));
  const targets = draft.fields.map((f) => f.target);

  return (
    <section className="card">
      <div className="card-head">
        <h2>2 · Map fields</h2>
        <div className="row">
          {sources.length > 0 && (
            <button className="btn ghost sm" onClick={() => set(fieldsFromColumns(sources.filter((s) => !s.startsWith("_"))))}>
              Map all sources
            </button>
          )}
          <button className="btn ghost sm" onClick={() => set([...draft.fields, { source: sources[0] ?? "", target: `field_${draft.fields.length + 1}` }])}>
            + Field
          </button>
        </div>
      </div>
      {draft.fields.length === 0 ? (
        <p className="muted small">No mapping: every source column is passed to the template as-is (names made identifier-safe).</p>
      ) : (
        <div className="map-table" role="table">
          <div className="map-row head" role="row">
            <span>Source</span><span>Template variable</span><span>Transform</span><span>Default if empty</span><span />
          </div>
          {draft.fields.map((f, i) => {
            const dup = targets.indexOf(f.target) !== i;
            const badId = !/^[A-Za-z_]\w*$/.test(f.target);
            const custom = f.transform && !TRANSFORMS.some((t) => t.v === f.transform);
            return (
              <div className="map-row" role="row" key={i}>
                <select value={f.source} aria-label="Source" onChange={(e) => patch(i, { source: e.target.value })}
                  className={sources.length && !sources.includes(f.source) ? "invalid" : ""}>
                  {!sources.includes(f.source) && <option value={f.source}>{f.source || "(choose)"} ⚠</option>}
                  {sources.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
                <input className={`mono ${dup || badId ? "invalid" : ""}`} value={f.target} aria-label="Template variable"
                  title={dup ? "Duplicate variable name" : badId ? "Letters, digits and _ only" : ""}
                  onChange={(e) => patch(i, { target: e.target.value })}
                  onBlur={(e) => patch(i, { target: toIdentifier(e.target.value) })} />
                <select value={f.transform ?? ""} aria-label="Transform" onChange={(e) => patch(i, { transform: e.target.value as FieldMapping["transform"] })}>
                  {custom && <option value={f.transform}>{f.transform}</option>}
                  {TRANSFORMS.map((t) => <option key={t.v} value={t.v}>{t.label}</option>)}
                </select>
                <input value={f.default ?? ""} placeholder="—" aria-label="Default"
                  onChange={(e) => {
                    const v = e.target.value;
                    const { default: _d, ...rest } = f; void _d;
                    set(draft.fields.map((x, j) => (j === i ? (v === "" ? rest : { ...f, default: v }) : x)));
                  }} />
                <button className="icon-btn" aria-label={`Remove ${f.target}`} onClick={() => set(draft.fields.filter((_, j) => j !== i))}>×</button>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
