import { useEffect, useState } from "react";
import { api, toAppError } from "../../lib/api";
import { fieldsFromColumns, templateFromFields } from "../../lib/configUtils";
import {
  DEFAULT_SECTIONS_RULE, SECTIONS_TEMPLATE,
  type AppError, type BlockRule, type InspectResult, type MatchResult, type OutlineResult, type OutputConfigDraft,
  type SectionsRule, type TableRule,
} from "../../types/domain";

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
  const setEx = (patch: Partial<TableRule> | Partial<BlockRule> | Partial<SectionsRule>) =>
    update((d) => ({ ...d, extraction: { ...d.extraction, ...patch } as OutputConfigDraft["extraction"] }));
  const switchType = (t: OutputConfigDraft["extraction"]["type"]) => {
    if (ex.type === t) return;
    const dirty = draft.fields.length > 0 || draft.template.record.trim() !== "";
    if (t === "sections" && dirty && !confirm("Switching to Text sections resets the field mapping and template. Continue?")) return;
    update((d) => {
      const extraction = t === "table" ? { ...DEFAULT_TABLE } : t === "block" ? { ...DEFAULT_BLOCK } : { ...DEFAULT_SECTIONS_RULE };
      if (t === "sections") return { ...d, extraction, fields: [], template: { ...SECTIONS_TEMPLATE } };
      // leaving sections: its fields/template don't exist in table/block data
      const leaving = d.extraction.type === "sections";
      return { ...d, extraction, ...(leaving ? { fields: [], template: d.template.record.trim() === SECTIONS_TEMPLATE.record.trim() ? { ...d.template, record: "" } : d.template } : {}) };
    });
  };
  const insp = inspect && "page_count" in inspect ? inspect : undefined;
  const inspErr = inspect && "code" in inspect ? inspect : undefined;

  return (
    <section className="card">
      <div className="card-head">
        <h2>1 · Extract records</h2>
        <div className="seg" role="radiogroup" aria-label="Extraction type">
          {(["table", "block", "sections"] as const).map((t) => (
            <button key={t} role="radio" aria-checked={ex.type === t} className={ex.type === t ? "on" : ""} onClick={() => switchType(t)}>
              {t === "table" ? "Table rows" : t === "block" ? "Text blocks (regex)" : "Text sections (headings)"}
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
      {ex.type === "table" && insp && insp.has_text && insp.tables.length === 0 && (
        <div className="banner warn small" role="status">
          No tables detected. This looks like a text document.
          <button className="link" onClick={() => switchType("sections")}>Use Text sections</button>
        </div>
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
        ) : ex.type === "block" ? (
          <BlockFields fileId={fileId} rule={ex} setEx={setEx} />
        ) : (
          <SectionsFields rule={ex} setEx={setEx} />
        )}
      </div>

      {ex.type === "sections" && <OutlinePanel fileId={fileId} rule={ex} />}

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
      {ex.type !== "table" && insp && (
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

function SectionsFields({ rule, setEx }: { rule: SectionsRule; setEx: (p: Partial<SectionsRule>) => void }) {
  const num = (v: string, d: number) => (Number.isFinite(parseFloat(v)) ? parseFloat(v) : d);
  return (
    <>
      <label>Heading detection
        <select value={rule.heading_mode} onChange={(e) => setEx({ heading_mode: e.target.value as SectionsRule["heading_mode"] })}>
          <option value="font">By font (size / bold)</option>
          <option value="numbering">By numbering (Chương, Điều, 1.1 …)</option>
          <option value="regex">By regex (advanced)</option>
        </select>
      </label>
      {rule.heading_mode === "font" && (
        <>
          <label>Heading size ≥ body ×
            <input type="number" step={0.05} min={1} max={4} value={rule.size_ratio}
              onChange={(e) => setEx({ size_ratio: Math.min(4, Math.max(1, num(e.target.value, 1.15))) })} />
          </label>
          <label className="check">
            <input type="checkbox" checked={rule.bold_headings} onChange={(e) => setEx({ bold_headings: e.target.checked })} />
            Short bold lines are headings too
          </label>
        </>
      )}
      {rule.heading_mode === "regex" && (
        <label className="span-all">Heading pattern <span className="muted">(a line that matches starts a new section)</span>
          <input className="mono" value={rule.heading_pattern ?? ""} placeholder="^\\d+\\.\\s" onChange={(e) => setEx({ heading_pattern: e.target.value })} />
        </label>
      )}
      {rule.heading_mode === "numbering" && (
        <p className="muted small span-all">
          Recognised: Phần / Chương / Mục / Điều (Part / Chapter / Section / Article), <span className="mono">I.</span>,{" "}
          <span className="mono">1.</span>, <span className="mono">1.1</span>, <span className="mono">1.1.1</span>. Levels follow the hierarchy found in the document.
        </p>
      )}
      <label>Max heading length (chars)
        <input type="number" min={1} max={500} value={rule.max_heading_chars}
          onChange={(e) => setEx({ max_heading_chars: Math.min(500, Math.max(1, Math.round(num(e.target.value, 120)))) })} />
      </label>
      <div className="span-all checks">
        <label className="check"><input type="checkbox" checked={rule.include_preamble} onChange={(e) => setEx({ include_preamble: e.target.checked })} />Keep text before the first heading</label>
        <label className="check"><input type="checkbox" checked={rule.join_lines} onChange={(e) => setEx({ join_lines: e.target.checked })} />Join wrapped lines into paragraphs</label>
        <label className="check"><input type="checkbox" checked={rule.skip_header_footer} onChange={(e) => setEx({ skip_header_footer: e.target.checked })} />Drop running headers/footers &amp; page numbers</label>
        <label className="check"><input type="checkbox" checked={rule.normalize_unicode} onChange={(e) => setEx({ normalize_unicode: e.target.checked })} />Normalise Unicode (NFC): same text, stable diacritics</label>
      </div>
    </>
  );
}

function OutlinePanel({ fileId, rule }: { fileId: string; rule: SectionsRule }) {
  const [st, setSt] = useState<{ loading: boolean; res?: OutlineResult; err?: AppError }>({ loading: true });
  const key = JSON.stringify(rule);
  useEffect(() => {
    let alive = true;
    setSt((p) => ({ ...p, loading: true }));
    const h = setTimeout(() => {
      api.outline(fileId, rule)
        .then((res) => alive && setSt({ loading: false, res }))
        .catch((e) => alive && setSt({ loading: false, err: toAppError(e) }));
    }, 450);
    return () => { alive = false; clearTimeout(h); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileId, key]);

  const { res, err, loading } = st;
  return (
    <div className="outline-panel" aria-live="polite">
      <div className="eyebrow">Detected headings {loading && <span className="muted">· updating…</span>}</div>
      {err && <div className="warn-text small">{err.code}: {err.message}</div>}
      {res && res.total === 0 && (
        <div className="warn-text small">
          No headings found. Lower the size ratio, allow bold headings, or switch detection mode.
          <div className="cols">Font sizes in this file:{" "}
            {res.font_sizes.map((f) => <span key={f.size} className="chip">{f.size}pt{f.size === res.body_size ? " (body)" : ""}</span>)}
          </div>
        </div>
      )}
      {res && res.total > 0 && (
        <>
          <div className="small muted">{res.total} heading{res.total === 1 ? "" : "s"} → {res.total} record{res.total === 1 ? "" : "s"} · body text {res.body_size}pt</div>
          <ol className="outline">
            {res.headings.map((h, i) => (
              <li key={i} style={{ paddingLeft: (h.level - 1) * 16 }}>
                <span className="lvl">H{h.level}</span> <span className="ol-title">{h.title}</span> <span className="muted small">p.{h.page}</span>
              </li>
            ))}
          </ol>
          {res.total > res.headings.length && <div className="muted small">…and {res.total - res.headings.length} more</div>}
        </>
      )}
    </div>
  );
}
