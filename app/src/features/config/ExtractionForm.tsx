import { useState } from "react";
import { api, toAppError } from "../../lib/api";
import { fieldsFromColumns, templateFromFields } from "../../lib/configUtils";
import type { AppError, BlockRule, InspectResult, MatchResult, OutputConfigDraft, TableRule } from "../../types/domain";

type Upd = (fn: (d: OutputConfigDraft) => OutputConfigDraft) => void;

const DEFAULT_BLOCK: BlockRule = {
  type: "block", pages: "", start_pattern: "^Invoice No: (?P<invoice>\\S+)", end_pattern: "",
  field_patterns: { customer: "Customer: (?P<value>.+)", total: "Total: ([\\d,.]+)" },
};
const DEFAULT_TABLE: TableRule = { type: "table", pages: "", header_row: 0, merge_multipage: true, table_strategy: "auto", table_index: null };

export function ExtractionForm({ fileId, draft, update, inspect }: {
  fileId: string; draft: OutputConfigDraft; update: Upd; inspect?: InspectResult | AppError;
}) {
  const ex = draft.extraction;
  const setEx = (patch: Partial<TableRule> | Partial<BlockRule>) =>
    update((d) => ({ ...d, extraction: { ...d.extraction, ...patch } as OutputConfigDraft["extraction"] }));
  const insp = inspect && "page_count" in inspect ? inspect : undefined;
  const inspErr = inspect && "code" in inspect ? inspect : undefined;

  return (
    <section className="card">
      <div className="card-head">
        <h2>1 · Extract records</h2>
        <div className="seg" role="radiogroup" aria-label="Extraction type">
          {(["table", "block"] as const).map((t) => (
            <button key={t} role="radio" aria-checked={ex.type === t} className={ex.type === t ? "on" : ""}
              onClick={() => ex.type !== t && update((d) => ({ ...d, extraction: t === "table" ? { ...DEFAULT_TABLE } : { ...DEFAULT_BLOCK } }))}>
              {t === "table" ? "Table rows" : "Text blocks (regex)"}
            </button>
          ))}
        </div>
      </div>

      {insp && (
        <p className="muted small">
          {insp.page_count} page{insp.page_count === 1 ? "" : "s"} · {insp.tables.length} table{insp.tables.length === 1 ? "" : "s"} detected in first {insp.pages_scanned}
          {!insp.has_text && <span className="warn-text"> · no text layer (scanned PDF). Conversion will fail.</span>}
        </p>
      )}
      {inspErr && <p className="warn-text small">Couldn't inspect this file: {inspErr.code}: {inspErr.message}</p>}

      <div className="form-grid">
        <label>Pages
          <input value={ex.pages ?? ""} placeholder="All pages (e.g. 1-3,5)" onChange={(e) => setEx({ pages: e.target.value })} />
        </label>
        {ex.type === "table" ? (
          <>
            <label>Table strategy
              <select value={ex.table_strategy} onChange={(e) => setEx({ table_strategy: e.target.value as TableRule["table_strategy"] })}>
                <option value="auto">Auto (ruled lines, then text)</option>
                <option value="lines">Ruled lines only</option>
                <option value="text">Text alignment (borderless)</option>
              </select>
            </label>
            <label>Header row
              <input type="number" min={0} value={ex.header_row} onChange={(e) => setEx({ header_row: Math.max(0, +e.target.value) })} />
            </label>
            <label>Table on page
              <select value={ex.table_index ?? ""} onChange={(e) => setEx({ table_index: e.target.value === "" ? null : +e.target.value })}>
                <option value="">All tables</option>
                {[0, 1, 2, 3].map((i) => <option key={i} value={i}>Table #{i + 1} only</option>)}
              </select>
            </label>
            <label className="check">
              <input type="checkbox" checked={ex.merge_multipage} onChange={(e) => setEx({ merge_multipage: e.target.checked })} />
              Merge across pages (drops repeated headers)
            </label>
          </>
        ) : (
          <BlockFields fileId={fileId} rule={ex} setEx={setEx} />
        )}
      </div>

      {ex.type === "table" && insp && insp.tables.length > 0 && (
        <div className="detected">
          <div className="eyebrow">Detected tables: click one to map its columns</div>
          {insp.tables.slice(0, 4).map((t) => (
            <button key={`${t.page}-${t.index}`} className="detected-item"
              onClick={() => update((d) => {
                const fields = fieldsFromColumns(t.columns);
                return { ...d, fields, template: d.template.record.trim() ? d.template : templateFromFields(fields, "table") };
              })}>
              <span className="mono small">p.{t.page} · #{t.index + 1} · {t.row_count} rows</span>
              <span className="cols">{t.columns.map((c) => <span key={c} className="chip">{c}</span>)}</span>
            </button>
          ))}
        </div>
      )}
      {ex.type === "block" && insp && (
        <details className="text-sample"><summary>PDF text sample</summary><pre>{insp.text_sample || "(empty)"}</pre></details>
      )}
    </section>
  );
}

function BlockFields({ fileId, rule, setEx }: { fileId: string; rule: BlockRule; setEx: (p: Partial<BlockRule>) => void }) {
  const [test, setTest] = useState<{ pattern: string; res?: MatchResult; err?: AppError } | null>(null);
  const run = async (pattern: string) => {
    setTest({ pattern });
    try { setTest({ pattern, res: await api.matchPattern(fileId, pattern, rule.pages) }); }
    catch (e) { setTest({ pattern, err: toAppError(e) }); }
  };
  const fp = Object.entries(rule.field_patterns);
  const setFp = (entries: [string, string][]) => setEx({ field_patterns: Object.fromEntries(entries) });

  return (
    <div className="span-all block-fields">
      <label>Start pattern <span className="muted">(each match starts a record; named groups become fields)</span>
        <div className="row">
          <input className="mono" value={rule.start_pattern} onChange={(e) => setEx({ start_pattern: e.target.value })} />
          <button className="btn ghost sm" onClick={() => run(rule.start_pattern)}>Test pattern</button>
        </div>
      </label>
      <label>End pattern <span className="muted">(optional; otherwise the record runs to the next start)</span>
        <input className="mono" value={rule.end_pattern ?? ""} onChange={(e) => setEx({ end_pattern: e.target.value })} />
      </label>
      <div className="eyebrow">Field patterns · first match inside each block (group “value”, first group, or whole match)</div>
      {fp.map(([k, v], i) => (
        <div className="row" key={i}>
          <input className="mono w-name" value={k} aria-label="Field name"
            onChange={(e) => setFp(fp.map((x, j) => (j === i ? [e.target.value, x[1]] : x)))} />
          <input className="mono" value={v} aria-label={`Pattern for ${k}`}
            onChange={(e) => setFp(fp.map((x, j) => (j === i ? [x[0], e.target.value] : x)))} />
          <button className="btn ghost sm" onClick={() => run(v)}>Test</button>
          <button className="icon-btn" aria-label={`Remove ${k}`} onClick={() => setFp(fp.filter((_, j) => j !== i))}>×</button>
        </div>
      ))}
      <button className="btn ghost sm" onClick={() => setFp([...fp, [`field_${fp.length + 1}`, ""]])}>+ Field pattern</button>

      {test && (
        <div className="tester" aria-live="polite">
          <div className="mono small">/{test.pattern}/</div>
          {!test.res && !test.err && <div className="muted small">Testing…</div>}
          {test.err && <div className="warn-text small">{test.err.code}: {test.err.message}</div>}
          {test.res && (
            <>
              <div className="small"><b>{test.res.total}</b> match{test.res.total === 1 ? "" : "es"}</div>
              {test.res.hits.slice(0, 5).map((h, i) => (
                <div key={i} className="hit">
                  <span className="muted small">p.{h.page}</span>{" "}
                  <mark>{h.match}</mark>{" "}
                  <span className="muted small mono">{JSON.stringify(h.groups)}</span>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
