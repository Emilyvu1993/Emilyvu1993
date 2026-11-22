import { SECTION_FIELDS, type FieldMapping, type OutputConfigDraft, type TemplateSpec } from "../types/domain";

/** Stable stringify (sorted keys) — mirrors the Rust conversion hash inputs. */
export function stableStringify(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(stableStringify).join(",")}]`;
  if (v && typeof v === "object") {
    const o = v as Record<string, unknown>;
    return `{${Object.keys(o).sort().filter((k) => o[k] !== undefined)
      .map((k) => `${JSON.stringify(k)}:${stableStringify(o[k])}`).join(",")}}`;
  }
  return JSON.stringify(v ?? null);
}

/** Only the parts that change output (same as Rust model::conversion_payload). */
export function conversionKey(c: OutputConfigDraft): string {
  return stableStringify({ extraction: c.extraction, fields: c.fields, template: c.template, output: c.output });
}

export function toIdentifier(s: string): string {
  let id = s.trim().toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d")
    .replace(/\W+/g, "_").replace(/^_+|_+$/g, "");
  if (!id || /^\d/.test(id)) id = `f_${id}`;
  return id;
}

export function fieldsFromColumns(cols: string[]): FieldMapping[] {
  const used = new Set<string>();
  return cols.map((c) => {
    let t = toIdentifier(c);
    while (used.has(t)) t += "_";
    used.add(t);
    return { source: c, target: t, transform: "trim" };
  });
}

export type TemplatePreset = "bullets" | "table" | "sections";

export function templateFromFields(fields: FieldMapping[], preset: TemplatePreset): TemplateSpec {
  const t = fields.map((f) => f.target);
  if (!t.length) return { header: "", record: "", footer: "", separator: "\n" };
  switch (preset) {
    case "table":
      return {
        header: `| ${fields.map((f) => f.source).join(" | ")} |\n|${t.map(() => " --- ").join("|")}|`,
        record: `| ${t.map((x) => `{{ ${x} | md }}`).join(" | ")} |`,
        footer: "",
        separator: "\n",
      };
    case "sections":
      return {
        header: "# {{ source_file }}\n",
        record: `## {{ ${t[0]} }}\n${t.slice(1).map((x) => `- **${x}**: {{ ${x} }}`).join("\n")}\n`,
        footer: "",
        separator: "\n",
      };
    default:
      return {
        header: "",
        record: `- ${t.map((x) => `**${x}**: {{ ${x} }}`).join(" · ")}`,
        footer: "",
        separator: "\n",
      };
  }
}

export function availableSources(c: OutputConfigDraft, detectedColumns: string[]): string[] {
  if (c.extraction.type === "sections") return [...SECTION_FIELDS, "_page"];
  if (c.extraction.type === "block") {
    const groups = [...c.extraction.start_pattern.matchAll(/\(\?P<(\w+)>/g)].map((m) => m[1]);
    return [...new Set([...groups, ...Object.keys(c.extraction.field_patterns), "_raw", "_page"])];
  }
  return [...detectedColumns, "_page"];
}

export function templateVariables(c: OutputConfigDraft): string[] {
  if (c.fields.length) return c.fields.map((f) => f.target);
  return c.extraction.type === "sections" ? SECTION_FIELDS : [];
}
