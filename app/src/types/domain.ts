// Mirrors src-tauri/src/model.rs and sidecar/pdf2md/config.py — keep in sync.

export type FileStatus = "new" | "converted" | "failed";

export interface LastError { code: string; message: string; at: string }

export interface WorkspaceFile {
  id: string;
  name: string;
  pdf_path: string;
  sha256: string;
  size_bytes: number;
  added_at: string;
  status: FileStatus;
  last_output_path?: string | null;
  last_error?: LastError | null;
  bound_config_id?: string | null;
  draft_config?: OutputConfigDraft | null;
}

export interface Workspace {
  schema_version: number;
  id: string;
  name: string;
  files: WorkspaceFile[];
  active_file_id?: string | null;
}

export type TableStrategy = "auto" | "lines" | "text" | "lines_text";

/** {"<font name substring>": {"<char>": "<replacement text>"}}: decodes symbol fonts (e.g. zodiac signs stored as letters). */
export type GlyphMap = Record<string, Record<string, string>>;

export interface TableRule {
  type: "table";
  pages?: string;
  table_index?: number | null;
  header_row: number;
  merge_multipage: boolean;
  table_strategy: TableStrategy;
  /** "row" = one record per table row; "table" = one record per table (e.g. per month). */
  record_mode?: "row" | "table";
  /** max gap (pt) that still joins characters into one word; default 3 */
  text_x_tolerance?: number | null;
  glyph_map?: GlyphMap;
}

export interface BlockRule {
  type: "block";
  pages?: string;
  start_pattern: string;
  end_pattern?: string;
  field_patterns: Record<string, string>;
  glyph_map?: GlyphMap;
}

export type HeadingMode = "font" | "numbering" | "regex";

/** Split a text document into records by heading. Fields: see SECTION_FIELDS. */
export interface SectionsRule {
  type: "sections";
  pages?: string;
  heading_mode: HeadingMode;
  size_ratio: number;
  bold_headings: boolean;
  max_heading_chars: number;
  heading_pattern?: string;
  include_preamble: boolean;
  join_lines: boolean;
  skip_header_footer: boolean;
  normalize_unicode: boolean;
  glyph_map?: GlyphMap;
}

export type ExtractionRule = TableRule | BlockRule | SectionsRule;

/** Variables of a record when record_mode = "table". Per-row values are in `rows` (loop) and `table`. */
export const TABLE_RECORD_FIELDS = ["title", "page", "row_count", "table", "markdown", "rows"];
export const TABLE_RECORD_TEMPLATE: TemplateSpec = { header: "", record: "{{ markdown }}\n", footer: "", separator: "\n" };

const SIGNS = Object.fromEntries([..."abcdefghijkl"].map((c, i) => [c, "♈♉♊♋♌♍♎♏♐♑♒♓"[i]]));

/** Astrodienst ephemeris font (adienst1): lowercase = zodiac signs, uppercase = planet header glyphs. */
export const GLYPH_PRESETS: { id: string; label: string; map: GlyphMap }[] = [
  {
    id: "astro", label: "Astrodienst ephemeris (zodiac signs + planets)",
    map: { adienst: { ...SIGNS, A: "☉", B: "☽", C: "☿", D: "♀", E: "♂", F: "♃", G: "♄", O: "♅", I: "♆", J: "♇",
      L: "☊ true", K: "☊ mean", M: "⚸", N: "⚷" } },
  },
];

export const SECTION_FIELDS = ["title", "level", "heading", "body", "markdown", "page", "page_end", "word_count"];

export const DEFAULT_SECTIONS_RULE: SectionsRule = {
  type: "sections", pages: "", heading_mode: "font", size_ratio: 1.15, bold_headings: true, max_heading_chars: 120,
  heading_pattern: "", include_preamble: true, join_lines: true, skip_header_footer: true, normalize_unicode: true,
};

/** `markdown` = heading + body, ready to use. */
export const SECTIONS_TEMPLATE: TemplateSpec = { header: "", record: "{{ markdown }}\n", footer: "", separator: "\n" };

export interface OutlineHeading { title: string; level: number; page: number; size: number }
export interface OutlineResult {
  body_size: number;
  total: number;
  headings: OutlineHeading[];
  font_sizes: { size: number; chars: number; bold_chars: number }[];
  warning?: string | null;
}

export type Transform = "" | "trim" | "upper" | "lower" | "number" | "number:eu" | `date:${string}`;

export interface FieldMapping { source: string; target: string; transform?: Transform; default?: string }

export interface TemplateSpec { header?: string; record: string; footer?: string; separator?: string }

export interface OutputSpec { mode: "single_file" | "file_per_record"; filename_pattern?: string }

/** Editor state. id present => linked to a saved config. */
export interface OutputConfigDraft {
  id?: string;
  name: string;
  version?: number;
  created_at?: string;
  updated_at?: string;
  extraction: ExtractionRule;
  fields: FieldMapping[];
  template: TemplateSpec;
  output: OutputSpec;
}

export type OutputConfig = Required<Pick<OutputConfigDraft, "id" | "version" | "created_at" | "updated_at">> &
  OutputConfigDraft;

export interface DetectedTable { page: number; index: number; columns: string[]; row_count: number; sample: string[][] }

export interface InspectResult {
  page_count: number;
  pages_scanned: number;
  has_text: boolean;
  tables: DetectedTable[];
  text_sample: string;
}

export interface PatternHit { page: number; match: string; groups: Record<string, string> | string[]; context: string }
export interface MatchResult { total: number; hits: PatternHit[] }

export interface ConvertWarning { code: string; field: string; count: number }

export interface ConvertResult {
  ok: true;
  record_count: number;
  columns: string[];
  preview: Record<string, unknown>[];
  preview_md: string;
  full_md_tmp_path: string;
  outputs: string[];
  warnings: ConvertWarning[];
}

export interface ConvertOutcome { job_id: string; config_hash: string; result: ConvertResult }

export interface SaveOutcome { output_path: string; backup_path?: string | null; file: WorkspaceFile }

export interface AddReport { added: string[]; skipped_duplicates: string[]; rejected: AppError[] }

export interface AppError { code: string; message: string; detail?: unknown }

export const DEFAULT_CONFIG: OutputConfigDraft = {
  name: "Untitled config",
  extraction: { type: "table", header_row: 0, merge_multipage: true, table_strategy: "auto", pages: "" },
  fields: [],
  template: { header: "", record: "", footer: "", separator: "\n" },
  output: { mode: "single_file", filename_pattern: "record_{{ index }}" },
};
